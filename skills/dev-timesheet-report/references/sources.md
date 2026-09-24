# Source adapters

How each source is queried, what it contributes, and how to normalize it into
the event schema in `config.md`. Every adapter is **read-only** — this skill
never writes worklogs, comments or any other record back.

## Six rules every adapter must follow

These are the ones that, when broken, produce a report that looks right and is
wrong. Read them before writing any adapter.

### 1. Render every timestamp in the machine's local timezone

Sources report time in different forms: Jira returns an offset
(`2026-09-22T09:14:03.000+0300`), GitHub returns UTC (`...T06:14:03Z`),
Confluence returns either. **Convert to the machine's local timezone, then
derive `date` and `time` from that.**

One convention, applied everywhere, is the whole point. Without it a code
review at 00:30 local is recorded under the previous day in UTC while the
commit from that same sitting is recorded under today — one evening's work
split across two dates, with no error anywhere to notice. `collect_git`
defaults to `--tz local` for exactly this reason; do not pass `--tz commit`
unless the user explicitly wants commits rendered in the offset they were made
in.

**Filter the range on the rendered date**, never on the raw timestamp, so the
filter and the display can never disagree about which day something belongs to.

### 2. Page through everything — never stop at the first response

Every API here truncates by default, and a truncated timesheet is a short
timesheet that looks complete.

| Source | Paging mechanism |
|---|---|
| Jira `/search/jql` | `nextPageToken` in the response; repeat with `nextPageToken=` until absent or `isLast` is true. Older `/search`: `startAt` + `maxResults` + `total` |
| Jira `/comment` | `startAt` + `maxResults` + `total` |
| Confluence `/content/search` | `start` + `limit`; follow `_links.next` until absent |
| GitHub | `--paginate` with `gh`, or the `Link: rel="next"` header over REST |
| GitLab | `--paginate` with `glab`, or `X-Next-Page` over REST |
| Bitbucket | a `next` URL in the body; follow until absent |

**Jira's default page size is 50.** A fortnight of a busy project exceeds that
easily, and the first page arrives looking perfectly normal.

If you impose a safety cap to avoid a runaway fetch, say so in the Step 7
status block — "stopped at N results, report may be incomplete" — rather than
quietly returning what you have.

### 3. Expect to be rate-limited, and never let it truncate silently

Paging is what trips limits, so this is rule 2's twin. The one that bites is
**GitHub's search API: 30 requests per minute**, far below the 5,000/hour core
REST limit — and the per-PR follow-up call for review timestamps means a busy
week makes a lot of requests.

Every API here signals the same way: **HTTP 429**, usually with a `Retry-After`
header. Jira and Confluence also return 429 under tenant load, and GitHub adds
undocumented secondary limits that surface as 403 with a rate-limit message
rather than 429.

What to do:

- **Honor `Retry-After`** when present; otherwise back off before retrying, and
  retry a small number of times rather than hammering.
- **Batch instead of looping** where the API allows it — one JQL `key IN (...)`
  for every title beats one request per ticket, which is why titles are fetched
  that way.
- **If you still cannot finish, report it.** Partial data with "GitHub: rate
  limited after 240 of ~400 PRs" in the status block is honest. The same data
  presented as a complete week is the failure this whole file exists to
  prevent.

### 4. Do not report the same commit twice

A commit can arrive from the local clone *and* from a code host. `build_report`
de-duplicates `commit` events that share a `ref`, preferring the local-git copy
(it has the true author date), so **any adapter emitting commit events must put
the commit SHA in `ref`**. Without it the same commit counts twice in
`evidence` and lists both sources, as though two separate things happened.

### 5. Never print or store a token

Read it from the configured env var at call time. If the var is unset, that is
a source-level failure, not a reason to prompt for a secret in chat.

### 6. A source that fails must be reported, not skipped

A timesheet missing a day's work is worse than no timesheet, because it looks
complete. Render what succeeded and print a per-source status line so a short
report is visibly short.

## Preflight: what access each source actually has

Resolve this **before** querying, and record the result for the Step 7 status
block. There are three access paths and they are checked in this order.

**1. MCP.** Use an MCP tool only if one is actually present in this session —
check the tools available to you, do not assume. MCP availability varies per
session and per user, so this is never a precondition: no MCP means fall
through to the next path, not an error. The skill cannot install one; only the
user can configure it in Claude Code.

**2. CLI.** `gh` or `glab` being on `PATH` does not mean it can talk to the
host. Check authentication, not presence:

```
gh auth status          # exit 0 = usable
glab auth status        # exit 0 = usable
```

A CLI that exists but is logged out falls through to the token path.

**3. Token.** Read the env var named in the config. Never prompt for a secret
in chat, and never write one to the config file.

If all three fail for a source, that source reports **"not configured"** and is
named in the status block. It must never return zero results silently: a report
that is short because a token is missing is indistinguishable from a quiet
week, which is the worst failure this skill has.

## 1. Local git repositories

Run the bundled collector — do not hand-parse `git log`:

```
python3 "<SKILL_DIR>/scripts/collect_git.py" \
  --repo "C:/work/web-app" --repo "C:/work/api" \
  --since 2026-09-01 --until 2026-09-07 \
  --author "dev@work.example" --author "Dev Name" \
  --ticket-prefix ABC --ticket-prefix OPS \
  --tz local
```

Fall back to `python`, `py -3`, then `node "<SKILL_DIR>/scripts/collect_git.mjs"`
with identical flags. Output is `{"events": [...], "skipped": [...]}`; surface
every `skipped` entry in the run's status lines.

Contributes `commit` events. Ticket ids come from the subject, body and branch
name. This is the only source that works with no network and no credentials, so
it is also the fallback when everything else fails.

## 2. Jira (board)

Supplies **ticket titles** (needed by every row) and the non-code evidence that
justifies labels other than Coding.

### Titles

Batch them; this is the slowest part of a run. One JQL call covers every key:

```
GET /rest/api/3/search/jql?jql=key IN (ABC-1,ABC-2,...)&fields=summary,issuetype
```

### The title cache

Titles are the slowest part of a run and the most repeated: people regenerate
the same week several times while tuning labels and columns. Cache them.

**Location:** `~/.dev-timesheet-report/cache/titles.json`. Create the directory
if it does not exist.

**Shape** — keyed by whatever appears in `ticket_ids`, so Jira keys and
Confluence page ids share one file (they cannot collide):

```json
{
  "ABC-1234": { "title": "Fix login redirect loop", "ticket_type": "Bug", "fetched": "2026-09-24" },
  "393217":   { "title": "RFC: auth redesign", "ticket_type": "Page", "fetched": "2026-09-24" }
}
```

Store `ticket_type` alongside the title — it comes from the same response, and
caching one without the other means refetching for the `Type` column.

**Invalidation: none automatic.** A renamed ticket showing its old title is a
cosmetic staleness; refetching every run to avoid it is not worth the
round trip. Refresh on an explicit ask ("refresh titles", "the titles are
stale") by deleting the file or the affected keys. A cache *miss* always
fetches, so new tickets are never stale.

**The cache is a convenience, never a dependency.** If the file is missing,
unreadable or malformed, ignore it and fetch — do not fail the run, and do not
report it as a source error. A corrupt cache should be overwritten on the next
successful fetch.

**Never cache anything else here.** No event data, no changelog, nothing
time-bounded — a cached *activity* record would silently answer the wrong
question when the range changes. Titles and issue types only, because they are
properties of the ticket rather than of the period being reported.

### Activity

```
GET /rest/api/3/search/jql
  ?jql=(assignee = <accountId> OR ...) AND updated >= "<since>"
  &expand=changelog
  &fields=summary,issuetype
```

Walk `changelog.histories`, keep entries whose `author.accountId` matches
`identity.jira_account_id` and whose `created` falls in the range:

| Changelog item | Event |
|---|---|
| `field: "status"` | `jira_transition`, with `status_to` = `toString` |
| `field: "assignee"`, `to` = the user | `jira_assigned` |

**Keep `issuetype` — do not drop it.** Both queries above already request it.
Put `fields.issuetype.name` on every Jira event as `ticket_type` (`Bug`,
`Task`, `Story`, or whatever the project actually defines). It feeds the
optional `Type` column and the `ticket_type` rule condition, and it is free
because the field is already in the response. Cache it next to the title.

Commits and PRs do not know the issue type; only the board does. That is fine —
a row merges the type from whichever of its events carried one.

Comments are a **separate call** (`/rest/api/3/issue/{key}/comment`) — budget
two requests per ticket, or set `board.fetch.comments = false` and accept
transitions-only as the cheap default. Worklogs are not fetched at all: a
worklog is a record about work rather than work, so it would be dropped anyway.

**Auth:** Basic, `email:api_token` base64-encoded, from `board.email_env` and
`board.token_env`.

**MCP path:** when `board.access` is `auto`/`mcp` and a Jira MCP tool is
available in the session, use it for title lookup and ad-hoc queries — it needs
no token. Do not make the core flow depend on it; MCP availability changes per
session, so REST stays the fallback.

**Notes:** the older `/rest/api/3/search` endpoint is deprecated on Jira Cloud;
target `/search/jql` and fall back only on a 404/410.

## 3. Confluence (wiki)

The source that makes documentation work visible at all — without it, a week
spent writing an RFC shows up as an empty Tuesday.

**Setup is nearly free when Jira is already configured**: same Atlassian site,
same email + API token, and the same `identity.jira_account_id` (an Atlassian
account id is shared across Jira and Confluence on one site). Only the space
keys and `enabled: true` are new.

**Base URL** defaults to `board.base_url`. Confluence Cloud lives under
`/wiki` on that host.

### Activity

The practical route is CQL search on the v1 API — the v2 API (`/wiki/api/v2/`)
has no good contributor filter:

```
GET /wiki/rest/api/content/search
  ?cql=contributor = "<accountId>" AND lastmodified >= "2026-09-01"
       AND lastmodified <= "2026-09-07" AND type = page
  &expand=version,space,history.lastUpdated
```

Add `AND space in (ENG, OPS)` when `wiki.spaces` is set. Then per page:

| Confluence object | Event type |
|---|---|
| page created in range (`history.createdDate`, `version.number == 1`) | `confluence_created` |
| page edited in range by this user | `confluence_updated` |
| comment authored in range | `confluence_comment` |

Version history for precise edit timestamps is
`GET /wiki/rest/api/content/{id}/version`; comments are
`GET /wiki/rest/api/content/{id}/child/comment`. Both cost an extra request
per page, so `wiki.fetch.comments = false` is the cheap default for large
spaces.

### Normalizing

Every Confluence event sets **`item_type: "confluence"`** — that is what puts
`Confluence` in the report's Type column and the page id in the Id column.

```json
{
  "date": "2026-09-22",
  "time": "13:20",
  "source": "confluence",
  "type": "confluence_updated",
  "item_type": "confluence",
  "ticket_type": "Page",
  "ticket_ids": ["393217"],
  "subject": "RFC: auth redesign",
  "url": "https://acme.atlassian.net/wiki/spaces/ENG/pages/393217"
}
```

Three things to get right:

1. **Use the numeric page id, not the title, as the id.** Titles get renamed;
   ids do not. A row whose id no longer resolves is worse than an ugly id.
2. **Always populate `url`.** `393217` on its own tells the reader nothing, and
   recall is the whole point of showing the id. The title carries the meaning
   and the URL carries the way back; the id is just the stable handle.
3. **Put the page title in `ticket_titles`**, keyed by the page id — the titles
   map is keyed by whatever appears in `ticket_ids`, regardless of item type.
   A Jira key and a numeric page id cannot collide.
4. **Set `ticket_type` to `"Page"`** — Confluence's own API and UI call them
   pages, so the word matches what the user sees on the other end of the URL.
   Use `"Blog post"` for the `blogpost` content type.

Confluence page ids never appear in commit messages, so Confluence rows come
only from this adapter — commit ticket-extraction is unaffected.

## 4. GitHub

**Preferred — `gh`** (no token handling at all):

```
gh api -X GET search/issues \
  -f q='is:pr author:<login> updated:2026-09-01..2026-09-07' --paginate
gh api -X GET search/issues \
  -f q='is:pr reviewed-by:<login> updated:2026-09-01..2026-09-07' --paginate
```

For review *timestamps* (search only gives you the PR), follow up per PR:
`gh api repos/{owner}/{repo}/pulls/{n}/reviews` and keep reviews whose
`user.login` matches and whose `submitted_at` is in range.

**Fallback — REST** at `https://api.github.com` (or `code_hosts[].base_url` +
`/api/v3` for Enterprise), `Authorization: Bearer $GITHUB_TOKEN`.

| GitHub object | Event type |
|---|---|
| PR created by user | `pr_opened` |
| PR merged by user | `pr_merged` |
| review submitted (`APPROVED`) | `pr_approved` |
| review submitted (other states) | `pr_review` |
| review comment | `pr_comment` |
| commit on a PR, if collected | `commit` — **must carry the SHA in `ref`** so it de-duplicates against the local clone (rule 4) |

Ticket ids come from the PR title, body and head branch name.

## 5. GitLab

**Preferred — `glab`:** `glab api "merge_requests?author_username=<user>&updated_after=...&scope=all" --paginate`

**Fallback — REST** at `<base_url>/api/v4`, header
`PRIVATE-TOKEN: $GITLAB_TOKEN`. Useful endpoints:

- `/merge_requests?author_username=&updated_after=&updated_before=&scope=all`
- `/merge_requests?reviewer_username=...` for reviews given
- `/events?target_type=MergeRequest&after=&before=` for a per-user activity
  feed, which is often the cheapest way to get timestamps

Map MR opened/merged to `pr_opened`/`pr_merged`, approvals to `pr_approved`,
MR notes to `pr_comment`. Self-managed GitLab is the same API behind a
different `base_url`.

## 6. Bitbucket Cloud

No first-party CLI; always REST at `https://api.bitbucket.org/2.0`, with an app
password or API token from `token_env` (Basic auth).

- `/repositories/{workspace}/{repo}/pullrequests?q=author.uuid="{uuid}" AND updated_on>=...`
- `/repositories/{workspace}/{repo}/pullrequests/{id}/activity` — the one
  endpoint that carries review/approval/comment timestamps per user

Bitbucket paginates with a `next` URL rather than page numbers; follow it until
absent. `identity.bitbucket_uuid` includes the braces.

## Resolving identity at setup

Do not ask the user to recall an account id or UUID — nobody knows these
without going to look. Resolve them, show the result, and let the user correct
it:

| Field | How |
|---|---|
| `git_authors` | `git config user.email`, plus distinct author emails found in the configured repos |
| `github_login` | `gh api user --jq .login` |
| `gitlab_username` | `glab api user` → `.username` |
| `jira_account_id` | `GET /rest/api/3/myself` → `accountId` |
| `bitbucket_uuid` | `GET /2.0/user` → `uuid` |

For `git_authors`, also scan the configured repos for other addresses attached
to the same name (`git log --format='%an <%ae>' | sort -u`) and offer them — a
work/personal address split is exactly the silent-drop case above.
