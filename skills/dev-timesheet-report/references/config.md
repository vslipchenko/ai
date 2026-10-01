# Config, event and rule schemas

The stored config lives at `~/.dev-timesheet-report/config.json`. A fresh copy
of the defaults is in `references/default-config.json`. Every field can be
overridden for a single run without touching the file (see "Overrides" below).

## Top-level fields

| Field | Purpose |
|---|---|
| `version` | Schema version; currently `1`. Refuse to guess at a higher number. |
| `identity` | Who "the developer" is, per system. See below. |
| `board` | The ticket board (Jira in v1). Supplies ticket titles and non-code activity. |
| `wiki` | The wiki (Confluence in v1). Off by default; makes documentation work visible. |
| `local_repos` | Local clones scanned with `collect_git`. |
| `code_hosts` | Remote hosts scanned for PRs/MRs and reviews. |
| `default_activity` | Label for events no rule matched. Default `"Other"`. |
| `activity_labels` | The allowed label vocabulary, for prompting and validation. |
| `activity_rules` | Ordered evidence → label rules. **First match wins.** |
| `range` | Default reporting window and week start. |
| `output` | Format, columns, time granularity, CSV destination. |
| `instructions` | Optional free-text guidance applied on every run. Default `null`. See below. |

## `identity`

```json
{
  "git_authors": ["Dev Name", "dev@work.example", "dev@personal.example"],
  "jira_account_id": "5f8a...",
  "github_login": "devname",
  "gitlab_username": "devname",
  "bitbucket_uuid": "{0d2b...}"
}
```

`git_authors` entries are passed to `git log --author=`, which treats each as a
regex over `Name <email>` and ORs them together. **A missing second email is
the silent-drop failure mode of this whole skill** — work committed under a
personal address just never appears, and a short timesheet looks like a light
week rather than a broken query. Resolve these at setup rather than asking the
user to recall them (see `sources.md`), and offer any additional author
addresses found in the configured repos.

## `board`

```json
{
  "type": "jira",
  "enabled": true,
  "access": "auto",
  "base_url": "https://acme.atlassian.net",
  "email_env": "JIRA_EMAIL",
  "token_env": "JIRA_API_TOKEN",
  "projects": ["ABC", "OPS"],
  "fetch": { "transitions": true, "comments": true }
}
```

- `access`: `auto` (MCP if a Jira MCP tool is available, else REST), `mcp`, or
  `rest`. `auto` is the default because MCP availability varies per session and
  no MCP is ever required — see the Prerequisites section of `SKILL.md`.
  Setting `mcp` explicitly makes a missing MCP an error rather than a fallback,
  so only use it when the user has one and wants to be told if it breaks.
- `projects` doubles as the ticket-key whitelist for commit/branch parsing.
  Leaving it empty falls back to a generic `ABC-123` pattern that will also
  match `UTF-8` and `SHA-256` — see `output.untracked` and the footer warning.
- `*_env` fields name **environment variables**, never the secrets themselves.
  Nothing in this skill writes a token to disk.
- `type` other than `"jira"` is not supported in v1; say so rather than
  improvising an adapter.

## `wiki`

```json
{
  "type": "confluence",
  "enabled": false,
  "access": "auto",
  "base_url": null,
  "email_env": "JIRA_EMAIL",
  "token_env": "JIRA_API_TOKEN",
  "spaces": ["ENG"],
  "fetch": { "pages": true, "comments": true }
}
```

Off by default — not every team uses a wiki, and an empty enabled source costs
a round trip per run. When Jira is already configured this needs almost nothing
new: same site, same credentials, same `identity.jira_account_id` (one
Atlassian account id serves both). `base_url` defaults to `board.base_url`.

`spaces` empty means all spaces the user can see. `type` other than
`"confluence"` is not supported in v1.

## `local_repos`

```json
[
  { "path": "C:/work/web-app", "name": "web-app" },
  { "path": "~/work/api" },
  { "path": "C:/work/legacy", "enabled": false }
]
```

`name` is optional and defaults to the directory name. It is what appears in
the `repo` column and in `repo` rule conditions. A leading `~` is expanded.

`enabled` is optional and defaults to `true`. Set it to `false` to park a repo
without deleting its entry — deleting is the thing people regret, because the
path and name have to be retyped to bring it back.

## `code_hosts`

```json
[
  { "type": "github", "access": "auto", "base_url": null, "repos": ["acme/web-app"], "orgs": ["acme"] },
  { "type": "gitlab", "access": "auto", "base_url": "https://gitlab.acme.io", "token_env": "GITLAB_TOKEN", "groups": ["acme/backend"] },
  { "type": "bitbucket", "access": "rest", "workspace": "acme", "token_env": "BITBUCKET_TOKEN" }
]
```

- `github` covers GitHub Enterprise through `base_url`; `gitlab` covers
  self-managed the same way. Bitbucket **Cloud** only in v1 — Bitbucket Data
  Center has a different API shape (`/rest/api/1.0`), so reject it with a clear
  message instead of firing Cloud routes at it.
- `access`: `auto` prefers the host's CLI (`gh`, `glab`) when it is installed
  *and authenticated*, else REST with the token env var. Bitbucket has no
  first-party CLI, so it is always REST.
- `enabled` is optional and defaults to `true`, same as `local_repos` — park a
  host without losing its configuration.

## Enabling and disabling sources

Every source can be switched off, and the idiom is the same everywhere:

| Source | Off when |
|---|---|
| Board (Jira) | `board.enabled: false` |
| Wiki (Confluence) | `wiki.enabled: false` |
| A local repo | its entry has `"enabled": false`, or the list is empty |
| A code host | its entry has `"enabled": false`, or the list is empty |

**The shipped defaults are not "everything on".** `default-config.json` has the
board enabled but with no projects, the wiki off, and both lists empty — it is
inert until setup fills it in. That is deliberate: a source that is enabled but
unconfigured costs a failed request and a confusing status line every run.

### Using one source only

Perfectly supported, in both directions:

- **Permanently** — disable the rest in the config. A GitLab-only setup is
  `board.enabled: false`, `wiki.enabled: false`, `local_repos: []`, and a single
  `code_hosts` entry.
- **For one run** — say so ("only Jira", "just GitLab this time", "skip the
  local repos"). Treat it as disabling every other source for that run only,
  and leave the stored config untouched.

A single-source report is a legitimate thing to want, not a degraded one — but
say in the status block which sources were off, so a short week is never
mistaken for a quiet one.

## `range`

```json
{ "default": "last-7-days", "week_starts_on": "monday" }
```

`default` accepts `today`, `yesterday`, `this-week`, `last-week`,
`last-N-days`, `this-month`, `last-month`.

**There is no timezone setting.** Every source renders in the machine's local
timezone — one fixed convention, so a commit and a code review from the same
evening always land on the same day. Making it configurable only created ways
for sources to disagree with each other. See rule 1 in `sources.md`;
`collect_git --tz commit` remains available for the rare case where a user
wants commits rendered in the offset they were made in.

## `output`

| Field | Default | Notes |
|---|---|---|
| `format` | `"terminal"` | or `"csv"` |
| `table_style` | `"grid"` | terminal-only: `grid` draws a boxed table per day; `plain` uses indented columns with one header at the top |
| `include_time` | `false` | `true` adds `HH:MM` **and** stops collapsing a day's events into one line |
| `columns` | `["date","day","item_type","id","title","activity"]` | from `date`, `day`, `time`, `item_type`, `ticket_type`, `id`, `title`, `activity`, `source`, `repo`, `url`, `evidence` |
| `csv_path` | `null` | default destination when `--format csv` is used with no `--out` |
| `title_width` | `60` | terminal-only truncation, ASCII `...` |
| `show_summary` | `true` | per-activity tally under the terminal table |
| `show_weekday` | `true` | terminal-only: append the day name to each date heading, `2026-09-22 (Tue)` |
| `show_header` | `true` | terminal-only: column-name row (inside each box in `grid`, once at the top in `plain`) |
| `untracked` | `"include"` | `include` / `omit` / `group` — what to do with activity carrying no ticket id |
| `untracked_placeholder` | `"(no ticket)"` | |
| `missing_title_placeholder` | `"(title unavailable)"` | when the board could not be reached or the ticket is gone |

`evidence` is the count of underlying events behind a collapsed line ("7
commits"), which is what makes a collapsed day defensible when someone
questions it.

### The three "what is this" columns

They are easy to confuse, so they are named for what they answer:

| Column | Header | Answers | Example |
|---|---|---|---|
| `item_type` | **System** | which system the id lives in | `Jira`, `Confluence` |
| `ticket_type` | **Type** | what kind of item it is | `Bug`, `Task`, `Story`, `Page` |
| `source` | **Source** | what evidence produced the row | `local-git, github` |

A git commit on `ABC-1234` is System `Jira` (its id is a Jira key), Type `Bug`
(the ticket's issue type), Source `local-git` (the proof was a commit).

`item_type` is set by the adapter and defaults to `jira`. A row with no item
behind it (untracked work) has an empty System.

`ticket_type` is **opt-in** — not in the default columns. Only board and wiki
events know it, so when a ticket's day merges a commit with a Jira transition,
the row takes the type from whichever event carried one. It is deliberately
**not** part of the grouping key: making it one would split a ticket-day in two
whenever some of its events were typed and some were not.

Issue types are per-project custom fields in Jira, so `Bug`/`Task`/`Story` are
conventional but not guaranteed — a team with `Tech Debt` gets that string
verbatim. Any rule keyed on `ticket_type` needs the team's real type names,
the same lesson as the workflow statuses.

`id` (header **Id**) is the Jira key for Jira rows and the numeric page id for
Confluence rows. Page ids are opaque on purpose: they are *stable* where titles
are not. The `title` column and the `url` column are what make a Confluence row
recognizable again — the id is only the handle for finding it.

Rows sort Jira before Confluence within a day. Without that, numeric page ids
would interleave among `ABC-123` keys purely because digits sort before letters.

In `columns`, `ticket_id` and `ticket` are accepted as spellings of `id`,
`type` and `issue_type` as spellings of `ticket_type`, and `system` as a
spelling of `item_type`.

Note that in **rule conditions** `type` means the evidence kind (`commit`,
`pr_review`, `confluence_updated`) — a different field again from either
column. Rule conditions use the raw event field names: `type`, `ticket_type`,
`status_to`, `source`, `repo`, `branch`, `ticket_ids`.

`day` is the short weekday name (`Tue`), derived from `date` — a fixed ASCII
table, never `strftime("%a")`/`toLocaleDateString`, both of which are
locale-dependent and would break parity between the two script twins. In
**terminal** output `date` and `day` are printed as the group heading rather
than as columns, so listing them in `columns` never duplicates them into every
line. In **CSV** they are two separate columns on purpose: folding `(Tue)` into
the `date` cell would stop Excel and Sheets recognizing it as a date.

## `instructions`

```json
{
  "instructions": "Treat OPS-* tickets as Investigation, never Coding. Skip the sandbox repo on Fridays. Always end with a 3-bullet summary of the week for my standup."
}
```

Free text, or `null` (the default — absent is the same as `null`). It is the
escape hatch for preferences the structured fields cannot express, and it is
read **every run, after the config loads and before Step 2**, as standing
guidance from the user.

How to apply it:

- **Translate it into overrides wherever one exists.** "OPS tickets are
  Investigation" becomes an in-memory rule placed ahead of the catch-all;
  "always CSV" becomes `output.format`; "never the sandbox repo" disables that
  `local_repos` entry. `build_report` still does the labelling, grouping and
  formatting — an instruction never means hand-editing its table, or two runs
  over the same week stop agreeing.
- **What has no override shapes the agent's own work**: how ambiguous ranges
  are read, extra notes or a summary after the report, which follow-ups to
  offer, tone of the status block.
- **Explicit requests in the current conversation win** over the stored
  instructions, the same way they win over every other config field.
- **It cannot switch off the safety rules.** The skill stays read-only against
  every source, failed and disabled sources are still reported in the status
  block, and the resolved range is still stated. An instruction that asks for
  any of those to go away is followed as far as it can be and the conflict is
  said once, plainly — a timesheet that hides a failed source is the one
  output this skill must never produce.
- **If an instruction is ambiguous or contradicts the structured config** (it
  names a repo that is not configured, a label not in `activity_labels`), say
  so in the status block rather than guessing silently.

Mention in the status block that stored instructions were applied — one short
line, not the text itself — so a report shaped by them is never mistaken for
the plain defaults.

Overriding it follows the same rules as everything else: "ignore my
instructions this time" runs with `null`; "this time also …" appends for one
run; "instead, …" replaces for one run. Only "save that" / "add that to my
instructions" / "clear my instructions" writes back. When saving an addition,
show the resulting full text before writing, since appended instructions can
quietly contradict earlier ones.

## Event schema

Every source normalizes to this shape before it reaches `build_report`:

```json
{
  "timestamp": "2026-09-22T09:14:03+03:00",
  "date": "2026-09-22",
  "time": "09:14",
  "source": "local-git",
  "type": "commit",
  "repo": "web-app",
  "ref": "9f3c1ab",
  "branch": "feature/ABC-1234-login",
  "ticket_ids": ["ABC-1234"],
  "subject": "ABC-1234 fix login redirect loop",
  "author": "Dev Name <dev@work.example>",
  "url": null,
  "item_type": "jira",
  "ticket_type": null,
  "status_to": null,
  "activity": null
}
```

`item_type` defaults to `"jira"` when absent, so git/GitHub/GitLab/Bitbucket
adapters need not set it. Confluence events set `"confluence"`.

`ticket_type` is the issue type (`Bug`, `Task`) on Jira events and `"Page"` on
Confluence events. Commit and PR events leave it empty — they have no way to
know it — and the row picks it up from whichever of its events did.

`date`/`time` are pre-rendered by the collector, so the renderer never does
timezone math. `activity` is normally `null`; setting it pins the label and
skips rule evaluation entirely.

### `type` vocabulary

| Source | Types |
|---|---|
| local git | `commit` |
| code hosts | `commit`, `branch_created`, `pr_opened`, `pr_updated`, `pr_merged`, `pr_review`, `pr_approved`, `pr_comment` |
| board | `jira_created`, `jira_transition`, `jira_comment`, `jira_assigned` |
| wiki | `confluence_created`, `confluence_updated`, `confluence_comment` |

Introducing a new type means adding a rule for it; otherwise it falls to
`default_activity`, which is visible in the report rather than silent.

## Rule schema

```json
{ "label": "Code Review", "when": { "type": ["pr_review", "pr_approved"] } }
{ "drop": true,           "when": { "type": "jira_transition", "status_to": "Done" } }
```

A rule carries either a `label` or `"drop": true`. A **drop rule suppresses the
event entirely** — no row is produced. That is how bookkeeping (assigning a
ticket, dragging a card to Done) stays off a timesheet
instead of piling up as `Other` rows. A rule with neither warns and falls back
to `default_activity`.

An explicit `activity` on an event beats every rule, drop rules included —
pinning a label is always deliberate.

Conditions inside one `when` **AND** together; a list of values inside one
condition **ORs**. Recognized condition fields: `type`, `source`, `repo`,
`branch`, `subject_matches`, `status_to`, `ticket_type`, `ticket_ids`. All are
case-insensitive; `subject_matches` is a case-insensitive regex against
`subject`. An unrecognized field warns and never matches — it is not silently
ignored, because a typo'd condition that matched everything would mislabel the
whole report.

**Order matters and is the most common mistake.** A specific rule placed after
a general one is unreachable:

```json
[
  { "label": "Coding",     "when": { "type": "commit" } },
  { "label": "Bug Fixing", "when": { "type": "commit", "subject_matches": "^fix" } }
]
```

Here nothing is ever labelled Bug Fixing. Put the narrow rule first.

## Overrides

Any config value can be overridden for one run without writing to disk. Only an
explicit "save this" / "make this my default" writes back. Common shapes:

| The user says | Override |
|---|---|
| "as a CSV to ~/ts.csv" | `output.format`, `--out` |
| "with times" | `output.include_time` |
| "just the web-app repo" | restrict `local_repos` |
| "call reviews 'Peer Review'" | relabel in `activity_rules` |
| "skip Jira this time" | `board.enabled = false` |
| "only GitLab" / "just my local repos" | disable every source but that one, this run only |
| "for ABC only" | restrict `board.projects` |
| "ignore my instructions this time" | `instructions = null` |
| "this time also mark OPS tickets as Investigation" | append to `instructions`, this run only |
| "add that to my instructions" / "clear my instructions" | write `instructions` back |
