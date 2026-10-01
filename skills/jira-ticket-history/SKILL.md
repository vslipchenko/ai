---
name: jira-ticket-history
description: Render the complete history of one Jira ticket as a local HTML page styled like `git log` — every changelog entry, comment and worklog as a "commit" with author and time, click to expand what changed, description and text-field edits as line diffs with a full-text view, titles as word diffs, and filters by activity type (status, assignee, description, title, other fields, comments, issue links, web links, attachments, worklogs) plus a hide-automation switch. Pages through every endpoint so nothing is silently cut off, and works on any Jira Cloud or Data Center site via an Atlassian MCP or an API token. Use when the user asks for a ticket's history, changelog, audit trail or timeline, "what changed on ABC-123", "who changed the description", "show me the git log of this ticket", or pastes a Jira ticket URL wanting its history. Read-only; configured once, overridable per run.
---

# Jira Ticket History

Turn one Jira ticket's full history into a single self-contained HTML page that
reads like `git log`: one line per change, newest first, click a line to see
exactly what changed.

The history is spread across three Jira APIs that each know part of it — the
changelog (field edits), comments, and worklogs — and every one of them returns
a page at a time. This skill collects all of them to the end, normalises them
into "commits", and renders them through a fixed template, so the page looks the
same on every run and on every site.

`<SKILL_DIR>` below is this skill's own announced base directory (the path shown
when this skill loads, ending in `.../skills/jira-ticket-history`). Scripts are
at `<SKILL_DIR>/scripts/`, the page template at `<SKILL_DIR>/assets/`,
references at `<SKILL_DIR>/references/`.

**Config lives at `~/.jira-ticket-history/config.json`** — the user's home
directory, not this repo. It is written once and reused every run.

This skill is **read-only against Jira**. It only reads; it never edits a
field, transitions, comments, logs work or changes anything else on the ticket.
Never call a write operation, even if one is available and even if asked
mid-run to "just fix" something — say that this skill only reads.

## Prerequisites

**Hard requirements** — without these the skill cannot run at all:

- **Python 3 or Node ≥ 18** for the bundled scripts. Either is fine; they are
  twins. If neither exists, say so and stop — see Step 5 for the order.
- **Read access to the ticket** in Jira, through one of the paths below.
- **A browser** to view the page. It is a single local `.html` file; nothing
  needs to be installed or served.

**Jira access — one of:**

| Path | Needs | Works with |
|---|---|---|
| Atlassian MCP | an Atlassian/Jira MCP server connected in Claude Code (`/mcp` lists it) | Jira Cloud |
| REST, Cloud | `JIRA_EMAIL` + `JIRA_API_TOKEN` env vars (names configurable) | Jira Cloud |
| REST, Data Center | a personal access token in `JIRA_API_TOKEN` (name configurable) | Jira Server / Data Center 8.14+ |

**No MCP is required.** An MCP only saves creating and storing a token. Its
absence is normal, never a failure. **This skill cannot install an MCP
server**, and neither can you on the user's behalf — they configure it in
Claude Code. If one would help, mention it once during setup, then move on.

**What the user should know before relying on the page:**

- **It shows what Jira recorded, and nothing else.** Jira keeps no earlier
  versions of a comment, so an edited comment shows only its latest text and
  the time of the edit. Fields that never changed have no history entries.
- **It shows everything the fetching account can see**, including comments
  restricted to a group or role. The file is saved locally and nothing is
  published, but before sharing the file with anyone, remember it may hold
  content they are not allowed to see.
- **Images and attachments stay in Jira.** They need a Jira login, so the page
  shows `[image: name]` placeholders and attachment names, not the files.
- **The Development panel is counts only** (branches, commits, pull requests,
  builds, deployments), and only when the site has Jira's development
  integration.
- **Nothing leaves the machine** except requests to the user's own Jira site.
  The page loads two web fonts from Google Fonts. Without a network it falls
  back to system fonts and still works.

## Step 1 — Load config, or run first-time setup

Read `~/.jira-ticket-history/config.json`.

- **Found** → use it, and go to Step 2.
- **Not found** → run Step 7 (setup) first, then come back.
- **Found but `version` is higher than 1, or it does not parse** → say so
  plainly and offer to re-run setup. Never guess at a partial read.

The user can force setup again at any time ("reconfigure", "redo my Jira
history setup"). Never re-run setup just because the skill was invoked again.

Load `references/config.md` before reading or writing the config file — the
schema is there, not in memory.

## Step 2 — Resolve the ticket and any per-run overrides

**Ticket.** Accept a key (`ABC-123`) or any Jira issue URL — a `/browse/`
link, or a board link with `selectedIssue=`. A URL carries its own site and
wins over `config.site`. A bare key with no configured site: ask for the site
once, and offer to save it.

One ticket per run. If the user names several, do them one after another as
separate pages, and say so.

**Overrides.** Anything in the config can be overridden for this run: which
types start checked ("only comments", "just status and assignee"), order
("oldest first"), "hide automation", time zone, output folder, excluded fields.
Apply them to an in-memory copy.

**Only write to the config file when the user says so** — "save that", "make
that my default", "always hide automation". Otherwise an override is for this
run and the stored config is untouched. If it is unclear which they mean, ask.

## Step 3 — Pick the access path

Load `references/fetching.md` now. Its four rules — page to the end, never use
`expand=changelog` on Cloud, record completeness, never print a token — are
the ones that produce a page that looks right and is wrong.

With `access: "auto"`: use an Atlassian MCP **if one is actually connected in
this session** (check your tools; do not assume), otherwise REST with the
configured env vars. `mcp` or `rest` forces one.

If neither path works — no MCP, and the token env var is unset — say plainly
that Jira access is **not configured**, name the env var that is missing, and
offer setup. Never report "no history" for a ticket you could not read.

## Step 4 — Fetch the whole history into a bundle

Write the bundle to a temp or scratch folder, not into the user's project.

- **REST:** run `fetch_history` (runtime order in Step 5):

  ```
  python3 "<SKILL_DIR>/scripts/fetch_history.py" --key ABC-123 --out <scratch>/ABC-123-bundle.json
  ```

  Exit `0` means a bundle was written — still read its `errors` and
  `completeness`. `2` means not configured, and `3` means the ticket itself
  could not be read (not found, no permission, auth failed). Relay the message.

- **MCP:** page the changelog, comments and worklogs exactly as
  `references/fetching.md` describes, then write the bundle yourself in its
  schema, with `completeness` filled in from what you actually received. If the
  MCP has no paged changelog operation, use REST for the changelog rather than
  accept a truncated one.

**When a source fails, keep going and record it.** Missing worklog permission
must not cost the user the changelog. A partial page with a visible warning is
useful; a silently short one is the worst output this skill can produce.

## Step 5 — Build the page

Run `build_history` with the bundle. Try runtimes in order, first one that works —
the `.py` and `.mjs` twins take identical flags and write byte-identical pages:

1. `python3 "<SKILL_DIR>/scripts/build_history.py" [args]`
2. else `python "<SKILL_DIR>/scripts/build_history.py" [args]`
3. else `py -3 "<SKILL_DIR>/scripts/build_history.py" [args]`
4. else `node "<SKILL_DIR>/scripts/build_history.mjs" [args]`

On Windows, `python`/`python3` may be the Microsoft Store placeholder, which
exits with code 9009 and prints an install hint. Treat that as "not available"
and move on.

```
python3 "<SKILL_DIR>/scripts/build_history.py" \
  --bundle <scratch>/ABC-123-bundle.json \
  --out "<output.dir>/ABC-123-history.html"
```

Flags: `--bundle PATH|-`, `--out PATH`, `--config PATH`, `--template PATH`,
`--tz local|utc`, `--types status,comments,...`, `--order asc|desc`,
`--hide-automation` / `--show-automation`. Per-run overrides from Step 2 go in
as flags. Everything else comes from the config.

It prints one JSON line (`out`, `entries`, `fetch`, `warnings`) and repeats each
warning on stderr.

**Never write, patch or post-process the HTML yourself.** The script and the
fixed template are what keep the page identical between runs and sites. If
something on the page is wrong, fix the script or report it — don't hand-edit
the output.

## Step 6 — Deliver

Give the path to the page, and open it in the default browser when
`output.open` is true (`start ""` on Windows, `open` on macOS, `xdg-open` on
Linux). Alongside it, a short status block — not a narrative:

- **Entries**, and per source what was fetched: "changelog 70/70 (2 pages),
  comments 13/13, worklogs 0/0".
- **Every warning**, plainly — an incomplete source, a failed source, fields
  excluded by the config. A short history must never read as a quiet ticket.
- The **first time only**, one line saying the page reflects only what Jira
  records (no earlier comment versions, no images), and that it can include
  restricted comments, so check before sharing it.

**Publishing is only on request.** The page is a local file. If the user asks
for a link or wants to share it, publish it as a private Artifact then — and
mention that restricted comments, if the page has any, go with it.

Offer to save per-run overrides as defaults only when the user seems to be
repeating them. Do not ask after every run.

## Step 7 — First-time setup

Run once, in order, then save to `~/.jira-ticket-history/config.json` using
`references/default-config.json` as the starting shape.

**7a. Site.** Take it from a ticket URL if the user already gave one.
Otherwise ask for the base URL.

**7b. Access.** If an Atlassian MCP is connected, use it and say no token is
needed. Otherwise ask which env var names hold the credentials (defaults
`JIRA_EMAIL` and `JIRA_API_TOKEN`), and mention **once** that an Atlassian MCP
configured in Claude Code would remove the token step. Detect the deployment
with `GET /rest/api/2/serverInfo` (`deploymentType: "Cloud"` means Cloud) and
explain which auth that implies: Cloud uses email + API token, Data Center a
personal access token. Never ask for a token value in chat.

**7c. Sample ticket.** Ask for one ticket they know well, and fetch it (Steps
3–4). The next two choices are made from real data, not from guesses.

**7d. What to track.** Everything is tracked by default. Show the fields that
appear in the sample's history, grouped by activity type, and ask via
`AskUserQuestion` whether to:

- start with some types unchecked (`history.types`) — still collected, one
  click away on the page; and/or
- stop collecting some fields at all (`history.exclude_fields`, by field id).

Say that excluded fields are listed on the page as not tracked, so their
absence is never mistaken for "never changed".

**7e. Automation accounts.** List the sample's authors with their entry
counts. Accounts Jira marks `accountType: "app"` are automation already. Ask
which others are bots or integrations (CI users, service accounts, sync tools),
and store their **account ids**, never names.

**7f. Output.** Folder for the pages (default: the current directory), open
automatically or not, newest or oldest first, hide automation by default or
not, local time or UTC.

**7g. Confirm and save.** Show the assembled config in plain language — not
raw JSON — and let the user correct it. Mention that tokens stay in
environment variables and are never written to the file. Create
`~/.jira-ticket-history/` if it does not exist, then write. If the write fails,
say so and offer to run with the settings held for this session only.

Then build the page for the ticket they originally asked about.

### Partial reconfiguration

Handle these without redoing all of 7a–7g, writing the single change back
immediately: change the site or access path, add or remove an excluded field or
an automation account, change default types, order, time zone or output folder.

## Error handling

- **No config** → Step 7, never a guessed run.
- **No Python or Node** → say so and stop. There is no hand-rolled fallback for
  the diffing, ordering and escaping the scripts do.
- **Not configured** (no MCP, token env var unset) → say which variable is
  missing and offer setup. Never report an empty history.
- **401** → the email/token pair is wrong or the token expired. **403 / 404 on
  the issue** → the ticket does not exist or this account cannot see it. Jira
  answers 404 for both, so say both.
- **One source failed** (e.g. worklogs 403) → build anyway. The page's warning
  banner and the status block name it.
- **`got < total`, or the page cap was hit** → build anyway, and say plainly
  that the history is incomplete and by how much.
- **Rate limited** → the scripts retry with `Retry-After`. If retries run out,
  the source is reported as failed. Suggest trying again shortly.
- **A huge MCP response saved to a file** → read all of it before building. A
  bundle made from the first chunk is a truncated history.
- **An entry looks wrong** → load `references/rendering.md`. Most surprises are
  a markup-only edit, repaired broken characters, or a field the config
  excludes.
