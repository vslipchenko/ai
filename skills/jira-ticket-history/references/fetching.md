# Fetching a ticket's history

How the raw history is collected, by either access path, into one **bundle**
that `build_history` turns into the page. Everything here is **read-only**:
only GET requests, never a write, transition, comment or worklog.

## Four rules

These are the ones that, broken, produce a page that looks right and is wrong.

### 1. Page every endpoint to the end

Jira truncates every list it returns. A first page arrives looking complete.

| Endpoint | Page with | Done when |
|---|---|---|
| `GET /rest/api/2/issue/{key}/changelog` | `startAt`, `maxResults` (≤ 100) | `isLast: true` |
| `GET /rest/api/2/issue/{key}/comment` | `startAt`, `maxResults` | `startAt + page ≥ total` |
| `GET /rest/api/2/issue/{key}/worklog` | `startAt`, `maxResults` | fetched `≥ total` (Data Center ignores paging and returns all) |

A page that comes back **empty before the end** means stop and mark the source
incomplete — never loop on it and never call it done.

### 2. Never use `expand=changelog` on Jira Cloud

On Cloud it returns **only the newest ~100 entries**, and says nothing about
the rest. Use the paged `/changelog` endpoint. `expand=changelog` is only the
fallback for Data Center versions where `/changelog` returns 404 — and even
then, compare `histories.length` against `total` and mark it incomplete if
short. The same trap exists in MCP tools: an "issue" call with a changelog
expand is not a substitute for the paged changelog operation.

### 3. Record how far each source got

Every bundle carries, per source:

```json
"completeness": {
  "changelog": { "got": 70, "total": 70, "pages": 2, "complete": true },
  "comments":  { "got": 13, "total": 13, "pages": 1, "complete": true },
  "worklogs":  { "got": 0,  "total": 0,  "pages": 1, "complete": true }
}
```

A source missing from `completeness`, or with `got < total`, is shown on the
page as incomplete and reported in the status block. A source that failed
outright goes in `errors` as `{ "source", "message" }` and the rest still runs.

### 4. Never print or store a token

Read it from the env var named in the config at call time. If it is unset,
that is "not configured" — not a reason to ask for a secret in chat.

## Path 1: an Atlassian MCP

Use it only if one is actually connected in this session — check the tools
you have; never assume. Match operations by **what they do**, not by name,
because names differ between MCP servers:

| Need | Look for an operation that… |
|---|---|
| issue | gets one issue by key with all fields, field names and field schema |
| changelog | lists an issue's changelog **with paging** (`startAt` / `maxResults`) |
| comments | lists an issue's comments with paging, ideally with rendered HTML bodies |
| worklogs | lists an issue's worklogs with paging |

If the MCP has no paged changelog operation, use the REST path for the
changelog instead of accepting a truncated one. Page each list exactly as in
rule 1, then **write the bundle yourself** in the shape below and save it to a
file. Keep items exactly as returned; do not summarise, reorder or drop any.

- Put comment bodies in `body`. If the MCP returned HTML, set
  `"body_format": "html"` on each comment (or put the HTML in `renderedBody`).
  If it returned ADF, leave `body` as the ADF object.
- If the issue's `description` came back as HTML rather than wiki markup, set
  `"description_format": "html"` on `issue`.
- Request the issue with its field **schema** too: the Development summary is
  found by schema type, never by the field's display name.
- Some MCPs nest custom fields, e.g. `fields.customFields["Sprint"] = { "id":
  "customfield_10020", "value": … }`. Flatten those into `fields[id] = value`
  so `issue.fields` looks the way REST returns it.
- Pages can overlap (e.g. `startAt` 0 and 20 because a response was too big to
  read in one go). Merge changelog entries **by `id`**. The history can also
  grow while you page, so take `total` and `isLast` from the **last** page, and
  keep paging until `isLast` is true.

Large MCP responses may be saved to a file by the harness. Read that file
completely — every character range — before building from it. Parse it with a
script rather than by eye, and cross-check the item count against `total`.

## Path 2: REST with a token (`fetch_history`)

```
python3 "<SKILL_DIR>/scripts/fetch_history.py" --key ABC-123 --out /tmp/ABC-123-bundle.json
```

Runtime order: `python3`, `python`, `py -3`, then
`node "<SKILL_DIR>/scripts/fetch_history.mjs"` — identical flags and bundle.

| Flag | Meaning |
|---|---|
| `--key` | Issue key or any Jira issue URL (a URL also supplies the site). Required. |
| `--site` | Base URL when `--key` is a bare key and the config has no `site`. |
| `--deployment` | `auto` (default), `cloud`, `datacenter`. |
| `--email-env`, `--token-env` | Env var names; default to the config, then `JIRA_EMAIL` / `JIRA_API_TOKEN`. |
| `--config` | Config path; default `~/.jira-ticket-history/config.json`. |
| `--page-size` | Items per request (default 100). |
| `--max-pages` | Safety cap per source (default 500). Hitting it is reported, never silent. |
| `--out` | Bundle path; default `<KEY>-bundle.json` in the working directory. Prefer a temp/scratch folder. |

Exit codes: `0` bundle written (read its `errors` and `completeness`),
`1` bad arguments, `2` not configured (token/email env var missing),
`3` the issue itself could not be read (not found, no permission, auth failed).
A summary JSON line goes to stdout; each source error also goes to stderr.

It uses **API v2 on both Cloud and Data Center**, because v2 returns the same
wiki markup the changelog stores, so descriptions diff and render through one
path. Comments are requested with `expand=renderedBody` for Jira's own HTML.

**Auth:** Cloud — Basic `email:token`. Data Center — `Authorization: Bearer
<personal access token>`. `auto` asks `/rest/api/2/serverInfo` and falls back to
Cloud when an email is configured.

**Rate limits:** HTTP 429 and 503 are retried up to 4 times, honouring
`Retry-After` (capped at 60 s) and otherwise backing off 1, 2, 4, 8 s. If
retries run out, the source is recorded in `errors` — reported, not skipped.

## Bundle schema (version 1)

The contract between fetching and building. Both paths must produce it.

```json
{
  "bundle_version": 1,
  "site": "https://acme.atlassian.net",
  "key": "ABC-123",
  "deployment": "cloud",
  "fetched_at": "2026-09-30T09:12:00.000Z",
  "issue": {
    "id": "10042", "key": "ABC-123",
    "fields": { "summary": "…", "description": "…", "status": {}, "issuetype": {}, "priority": {},
                "assignee": {}, "reporter": {}, "creator": {}, "parent": {}, "created": "…", "updated": "…" },
    "names": { "customfield_10020": "Sprint" },
    "schema": { "customfield_10500": { "custom": "…:devsummarycf" } },
    "description_format": "wiki"
  },
  "changelog": [ { "id": "1", "created": "…", "author": { "accountId": "…", "displayName": "…", "accountType": "atlassian" },
                   "items": [ { "field": "status", "fieldId": "status", "fromString": "To Do", "toString": "In Progress" } ] } ],
  "comments":  [ { "id": "2", "created": "…", "updated": "…", "author": {}, "body": "…", "renderedBody": "<p>…</p>",
                   "parentId": null, "visibility": null } ],
  "worklogs":  [ { "id": "3", "created": "…", "started": "…", "updated": "…", "author": {}, "timeSpent": "1h", "comment": "…" } ],
  "completeness": { "changelog": {}, "comments": {}, "worklogs": {} },
  "errors": [ { "source": "worklogs", "message": "no permission" } ]
}
```

Timestamps are Jira's own (`2026-09-04T16:21:05.966+0200`); `build_history`
normalises them. Data Center users have `key`/`name` instead of `accountId` and
no `accountType` — both are handled.
