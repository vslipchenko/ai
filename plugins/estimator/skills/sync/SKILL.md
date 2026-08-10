---
name: sync
description: Build or update the estimator's history dataset by fetching Jira tickets via the Atlassian MCP — both the initial setup and periodic top-ups (new or missing resolved tickets). Use when the user wants to set up the estimator, or (re)build / refresh / sync the estimation history from Jira.
---

# Estimator — Sync History from Jira

This skill builds and updates `<DATA_DIR>/history.csv`: the estimation baseline of
resolved Jira tickets. Run it for the initial setup, and re-run it periodically
to top up new or missing tickets — **refresh** (full re-fetch) or **append**
(only tickets resolved since the last run). You (the model) do the interactive +
Jira work; a bundled script does the CSV assembly.

## Read-only Jira access

This skill treats Jira purely as a **data source**. Use only read operations —
`atlassianUserInfo`, `getAccessibleAtlassianResources`, project/field metadata,
`searchJiraIssuesUsingJql`, `getJiraIssue`, `getJiraIssueRemoteIssueLinks`. You
MUST NOT call any operation that creates, edits, transitions, comments on,
links, assigns, deletes, or logs work against Jira issues (or writes to
Confluence). If a step seems to require a write, stop and tell the user instead
of proceeding.

## Data location

Resolve `<DATA_DIR>` once and reuse it everywhere below — the per-user data dir
`~/.estimator` (a normal home dotfolder, like `~/.aws`; uninstalling the plugin
does NOT remove it — use `/estimator:reset` to clear it):

- Bash: `DATA_DIR="$HOME/.estimator"`
- PowerShell: `$DATA_DIR = Join-Path $env:USERPROFILE '.estimator'`

This is a single global directory per plugin (not per project), so the dataset
is fetched once and reused from any working directory.

Files in `<DATA_DIR>`:
- `history.csv` — the ticket dataset (13 columns; see the build script)
- `config.json` — run metadata: `jql`, `project_keys`, `cloud_id`,
  `story_point_field_id`, `min_fetch_story_points`, `updated_watermark`,
  `schema_version`, `row_count` (plus `estimation_prefs`, written by `estimate`)

Create the directory if it does not exist (`mkdir -p "<DATA_DIR>"`).

## Step 1 — Preflight: verify Atlassian MCP

Call `atlassianUserInfo` (or `getAccessibleAtlassianResources`). If it fails or
no resources are returned, STOP and tell the user to connect the Atlassian MCP
(`/mcp`), then re-run. Capture the `cloud_id` for `config.json`.

## Step 2 — Existing-CSV check

If `history.csv` already exists, read `config.json` and ask the user to choose:
- **refresh** — overwrite the full dataset from a fresh fetch (`mode=overwrite`)
- **append** — fetch only tickets updated after `updated_watermark` and merge
  them (`mode=append`)
- **cancel** — stop, change nothing

If it does not exist, proceed with `mode=overwrite`.

## Step 3 — Interactive scoping (build the JQL)

Ask the user (one at a time):
1. Project key(s) — e.g. `PROJ` or `PROJ, CORE`
2. How to scope the fetch. Every fetch covers only **completed tickets that have
   story points** (`statusCategory = Done` + the estimate filter — see below);
   the scope just bounds *which* of those are pulled, by a **time window** and/or
   a **maximum count (latest N)**. **At least one is required** (never fetch
   unbounded history):
   - Time window — e.g. updated in the last 6 months, or since a specific date.
   - Max count — the latest N estimated tickets (most-recently-updated first).

Once you have the project key(s), **resolve the Story Points field id** (Step 4)
and settle the **minimum story points** to include (Step 4's first-run
preference) — the query needs both. Then build JQL for **estimated, completed
tickets**, ordered **most-recently-updated first** (`ORDER BY updated DESC` —
`updated` always exists and only moves forward, unlike `resolutiondate`, which is
null for many Done-category tickets, so it is the reliable basis for ordering,
the time window, and the append watermark). JQL refers to a custom field by its
numeric id as `cf[<n>]` (so `customfield_10016` → `cf[10016]`); for example:
`project in (PROJ) AND statusCategory = Done AND cf[10016] is not EMPTY
AND updated >= -26w ORDER BY updated DESC`
- **Story-points filter** → always include the estimate filter, using the field
  id from Step 4 and the minimum from Step 4: minimum `0` → `cf[<id>] is not
  EMPTY`; minimum `N > 0` → `cf[<id>] >= N` (both refresh and append). If Step 4
  could not resolve a populated field, there are no estimated tickets to learn
  from — warn the user and stop (don't import blank rows or overwrite existing
  history).
- **Time window given** → include an `updated >= <window>` filter (activity-based;
  captures recent work without dropping Done tickets that lack a resolution date).
- **Max count N given** → fetch only the first **N** results (the latest N by
  `updated`); see Step 5.
- **Both given** → the window filters, then take the latest N within it.
- **Neither** → re-ask; at least one is required.
For **append**, add `AND updated >= "<updated_watermark>"` — use `>=` (not `>`)
so a ticket sharing the boundary timestamp is never skipped; the dedup-merge
absorbs the harmless re-fetch. The max-count cap does **not** apply to append
(Step 5).
Show the assembled JQL **and** the cap ("fetch up to N, newest first") and ask
the user to confirm before fetching.

## Step 4 — Resolve the Story Points field id

"Story Points" is a Jira **custom field**, not built-in — its id (e.g.
`customfield_10016`) is assigned per site and must be discovered. A site often
has **several** story-points-like fields (e.g. "Story Points", "Story point
estimate", "Original Story Points", "QA Story Points"); only one is actually used.

Run this **during Step 3**, right after the project key(s) are known — Step 3's
fetch query needs the resolved id for its `is not EMPTY` clause.

Resolve it once and cache it:
1. If `config.json` already has `story_point_field_id`, reuse it.
2. Otherwise list the **candidate fields whose name matches** story points —
   from a sample issue fetched with field `names` expanded (or the field
   listing). Collect every `customfield_…` whose name contains "story point"
   (case-insensitive).
3. **Pick by population:** fetch a sample of recent resolved issues (~25)
   requesting those candidate ids, and choose the candidate **populated in the
   most issues** (the field the team actually uses).
4. **Tiebreaker:** if two are similarly populated, prefer the one whose
   `schema.custom` is a greenhopper story-points type
   (`com.pyxis.greenhopper.jira:*story-points*`) **if the MCP exposes it**;
   otherwise ask the user which to use.
5. Store the chosen id in `config.json`. If no candidate is found or populated,
   there is no estimate signal to learn from — warn the user and stop without
   overwriting `history.csv` (Step 3's `is not EMPTY` filter has no field to
   apply).

**Inspecting the saved sample (steps 2–3).**
The candidate `names` map and the population count come from a saved MCP result. Read it and tally the populated
candidate with the first available runtime (don't hand-write a fragile inline
`python -c`/`node -e` one-liner over shell-quoted data):
1. `python3`
2. else `python`
3. else `py -3`
4. else `node` — run a small script that reads the saved result file
5. else **fallback**: read the saved result with the **Read tool** and count by hand.

### Minimum story points to include (first-sync preference)

Determine `min_fetch_story_points` — the lowest Story Points value a ticket must
have to be fetched:
1. If `config.json` already has `min_fetch_story_points`, reuse it (no prompt).
2. Otherwise (first sync), ask the user once: **"Minimum story points a ticket
   must have to be included? (0 = keep all estimated tickets, including 0-point;
   1 = drop 0-point tickets; higher allowed.)"** Default to `0` if they skip.
3. Cache the integer in `config.json` (preserved across later syncs; to change
   it, edit `config.json`).

It feeds Step 3's estimate filter: `0` → `cf[<id>] is not EMPTY`; `N > 0` →
`cf[<id>] >= N`.

## Step 5 — Fetch tickets

Fetch with a **single** `searchJiraIssuesUsingJql` using the confirmed JQL,
requesting these fields: `summary, issuetype, description, components, labels,
resolutiondate, updated, parent, timespent, <story_point_field_id>, comment`.
**Paginate that one search** until all matching results are retrieved, or until
the max count N is reached (initial build / refresh only — the cap never applies
to append). This one (paginated) search returns every matching issue with its
fields; **assemble the records from it** — do NOT loop `getJiraIssue` per ticket.

For each issue collect:
- `parent_key` — from the `parent` field (blank if none)
- `comments` — ALL comments, oldest→newest, as an array of plain-text strings
- `design_link` — the first Figma/Confluence URL found in the **description**
  (blank if none). Do **not** call `getJiraIssueRemoteIssueLinks` per ticket here
  (it would add one MCP call per issue); note in the summary that authoritative
  remote-link backfill is available on request.
- track the **maximum `updated`** timestamp across all fetched issues — it
  becomes `updated_watermark` (Step 7).

Render description and comments to plain text (strip ADF/markup; drop image-blob
embeds; keep the inner text/URLs/mentions of any `<custom>` tags).

**Reading the bulk result.** The harness may return the search inline (small) or
save it to a file (large). Either way it is the **source of record data** — if it
was saved, **read the saved result** (the Read tool, or a script that reads the
file) and assemble from it. Do NOT improvise a fragile inline `node -e`/`python
-c` parser of shell-quoted JSON, and do NOT re-fetch issues one-by-one. A
per-issue `getJiraIssue` is only a *fallback* for a specific field the search did
not return (e.g. comments missing for one issue). Use markdown rendering so
descriptions/comments come back as plain text.

If pagination or any API cap forces you to drop results, state exactly how many
were dropped — never silently truncate. If a max-count cap stopped the fetch
early (more tickets match than were fetched), say so (e.g. "fetched the latest
100; more match the query").

If **zero** tickets are returned: warn the user and do NOT overwrite an existing
`history.csv`. Stop. (If a high `min_fetch_story_points` is the likely cause, say
so.)

## Step 6 — Build the CSV

Write the collected records as a JSON array to
`<DATA_DIR>/_records.tmp.json`. Each record object uses these keys
(omit or null any that are absent): `key, parent_key, issue_type, summary,
description, components` (array), `labels` (array), `story_points,
time_spent_seconds, resolution_date, comments` (array), `design_link`,
`estimate_basis`. Because `sync` fetches **resolved** tickets with real
outcomes, set `estimate_basis` to `"actual"` on every record (this lets the
`estimate` skill trust these rows over its own suggestions).

Contract: every record MUST have a non-empty `key`. Scalar fields (`key`,
`parent_key`, `issue_type`, `summary`, `description`, `story_points`,
`time_spent_seconds`, `resolution_date`, `design_link`, `estimate_basis`) must
be strings or numbers — not objects or booleans. `components`, `labels`, and
`comments` must be arrays of strings.

Then assemble the CSV by detecting an available runtime, in this order:

1. `python3 "<PLUGIN_ROOT>/scripts/build_csv.py" "<DATA_DIR>/_records.tmp.json" "<DATA_DIR>/history.csv" <mode>`
2. else `python "<PLUGIN_ROOT>/scripts/build_csv.py" "<DATA_DIR>/_records.tmp.json" "<DATA_DIR>/history.csv" <mode>`
3. else `py -3 "<PLUGIN_ROOT>/scripts/build_csv.py" "<DATA_DIR>/_records.tmp.json" "<DATA_DIR>/history.csv" <mode>`
4. else `node "<PLUGIN_ROOT>/scripts/build_csv.mjs" "<DATA_DIR>/_records.tmp.json" "<DATA_DIR>/history.csv" <mode>`
5. else **fallback**: build the CSV yourself with the Write tool, applying the
   exact rules in `scripts/build_csv.py` — header row first, `;`
   delimiter, multi-value cells joined with `, `, comments joined with `\n\n`,
   and RFC 4180 quoting (wrap any cell containing `;`, `"`, a newline, or a
   carriage return in double quotes and double internal `"`). For append, read and merge the
   existing rows, dedup by key (new wins).

**Resolving `<PLUGIN_ROOT>`:** `$CLAUDE_PLUGIN_ROOT` is usually empty inside a
skill's shell, so don't rely on it. `<PLUGIN_ROOT>` is the directory **two levels
above this skill's announced base directory** (the base dir shown when this skill
loaded is `…/skills/<name>`, so its parent's parent is the plugin root).
Substitute that absolute path for `<PLUGIN_ROOT>` in the commands above.

Delete `_records.tmp.json` when done.

## Step 7 — Update config and report

Read the existing `config.json` (if any) and update **only** these keys,
preserving every other key already present (e.g. `estimation_prefs`):
`updated_watermark` (the newest issue `updated` timestamp fetched — the append
watermark), `jql`, `project_keys`, `cloud_id`, `story_point_field_id`,
`min_fetch_story_points`, `schema_version` = `1`, and `row_count` (the value
`build_csv` prints as `{"row_count":N}`). Then report to the user: number of rows
written, the absolute CSV path, and the column list.
