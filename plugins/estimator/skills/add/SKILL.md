---
name: add
description: Add tickets to the estimator history by Jira key — fetched live from Jira and written as new records — without re-running `sync`. Use when the user wants to add / record specific tickets into the history (e.g. "add ABC-7777 to history", "add these tickets to the estimator history", "add missing tickets 7777, 7780"). Adds whole records (overrides an existing one only after confirmation); field-level editing is the edit skill.
---

# Estimator — Add Tickets to History

Record specific tickets in `history.csv` by Jira key, fetched live from Jira,
without re-running `/sync`. For filling in a few missing/new records. Adds whole
records — field-level editing is `/edit`; an existing record is **overridden**
(replaced with fresh Jira data) only after explicit confirmation.

## Read-only Jira access

This skill treats Jira purely as a **data source**. Use only read operations —
`atlassianUserInfo`, `getAccessibleAtlassianResources`, project/field metadata,
`searchJiraIssuesUsingJql`, `getJiraIssue`, `getJiraIssueRemoteIssueLinks`. You
MUST NOT call any operation that creates, edits, transitions, comments on,
links, assigns, deletes, or logs work against Jira issues (or writes to
Confluence). If a step seems to require a write, stop and tell the user instead
of proceeding.

## Data location

Resolve `<DATA_DIR>` as the other skills do — the per-user data dir `~/.estimator`:
- Bash: `DATA_DIR="$HOME/.estimator"`
- PowerShell: `$DATA_DIR = Join-Path $env:USERPROFILE '.estimator'`

## Step 1 — Preflight
Resolve `<DATA_DIR>`. If `<DATA_DIR>/history.csv` does not exist, tell the user
to run `/sync` first (or use the `import` skill) and stop. Verify the Atlassian
MCP is connected (`atlassianUserInfo`); if not, tell the user to connect it
(`/mcp`) and stop. Read `config.json` for `story_point_field_id` and
`project_keys`.

## Step 2 — Resolve the key(s)
Take one or more keys from the user's message/argument (space- or
comma-separated) and uppercase them. Expand bare numbers via `config.json`
`project_keys`: one cached key → prefix (`7777` → `ABC-7777`); several → ask
which project; none cached → ask for the project key. If no key can be
determined, prompt the user.

## Step 3 — Fetch each ticket
For each key, use `getJiraIssue` requesting the same fields `sync` captures:
`summary, issuetype, description, components, labels, parent, timespent,
<story_point_field_id>, comment, resolutiondate`; also fetch remote/web links
(`getJiraIssueRemoteIssueLinks`) for the design link. Render description and
comments to plain text. Collect the full field set: `key, parent_key,
issue_type, summary, description, components` (array), `labels` (array),
`story_points, time_spent_seconds, resolution_date, comments` (array),
`design_link`. A key that cannot be fetched (not found / no access) → record it
as "not found" and skip it.

## Step 4 — Validate addability
A ticket is **addable** only if it has a non-empty `key`, `summary`, AND
`story_points`. Skip any that fail and report the reason (missing story points /
missing summary).

## Step 5 — Derive `estimate_basis`
Per addable ticket: if it has a resolution date (resolved) → `estimate_basis` =
`actual`; otherwise → `final`.

## Step 6 — Override check
Look up the addable keys in `history.csv` with the find script, using the first
available runtime:
1. `python3 "<PLUGIN_ROOT>/skills/find/scripts/find_records.py" "<DATA_DIR>/history.csv" KEY [KEY ...]`
2. else `python "<PLUGIN_ROOT>/skills/find/scripts/find_records.py" "<DATA_DIR>/history.csv" KEY [KEY ...]`
3. else `py -3 "<PLUGIN_ROOT>/skills/find/scripts/find_records.py" "<DATA_DIR>/history.csv" KEY [KEY ...]`
4. else `node "<PLUGIN_ROOT>/skills/find/scripts/find_records.mjs" "<DATA_DIR>/history.csv" KEY [KEY ...]`
5. else **fallback**: read `<DATA_DIR>/history.csv` yourself (`;`-delimited, RFC 4180) and scan for the keys.

For any key already present (in the script's `found` list, or your fallback scan), show its stored
`story_points`/`estimate_basis` and ask the user to confirm **overriding** it.
Declined keys are skipped and reported as "kept existing".

## Step 7 — Append
Write the records JSON (full 13 fields: `key, parent_key, issue_type, summary,
description, components` [array], `labels` [array], `story_points,
time_spent_seconds, resolution_date, comments` [array], `design_link,
estimate_basis`) for the new + confirmed-override set to `<DATA_DIR>/_add.tmp.json`.
Append with the first available runtime:
1. `python3 "<PLUGIN_ROOT>/scripts/build_csv.py" "<DATA_DIR>/_add.tmp.json" "<DATA_DIR>/history.csv" append`
2. else `python "<PLUGIN_ROOT>/scripts/build_csv.py" "<DATA_DIR>/_add.tmp.json" "<DATA_DIR>/history.csv" append`
3. else `py -3 "<PLUGIN_ROOT>/scripts/build_csv.py" "<DATA_DIR>/_add.tmp.json" "<DATA_DIR>/history.csv" append`
4. else `node "<PLUGIN_ROOT>/scripts/build_csv.mjs" "<DATA_DIR>/_add.tmp.json" "<DATA_DIR>/history.csv" append`
5. else **fallback**: append the rows yourself with the Write tool, applying the
   build_csv rules (13 columns; `;` delimiter; `, ` for multi-value; `\n\n` for
   comments; RFC 4180 quoting), dedup by key (new wins), padding any legacy
   12-column rows to 13.
Append mode dedups by key (new wins), so a confirmed override replaces the old
row. Delete `_add.tmp.json`. Update `config.json` `row_count` to the value
`build_csv` prints as `{"row_count":N}`, preserving every other key.

## Step 8 — Report
Report: added (new keys), overridden, skipped-invalid (with the reason),
not-found-in-Jira, and kept-existing (override declined).

**Resolving `<PLUGIN_ROOT>`:** `$CLAUDE_PLUGIN_ROOT` is usually empty inside a
skill's shell, so don't rely on it. `<PLUGIN_ROOT>` is the directory **two levels
above this skill's announced base directory** (the base dir shown when this skill
loaded is `…/skills/<name>`, so its parent's parent is the plugin root).
Substitute that absolute path for `<PLUGIN_ROOT>` in the commands above (it
applies to the sibling `find` script too).

## Error handling
- No `history.csv` → guide to `/sync` (or the `import` skill); do not create one.
- Atlassian MCP not connected → guide to connect; stop.
- No / unparseable keys → prompt.
- Ticket not found in Jira → report and skip (don't fail the whole batch).
- Addability failure (no key/summary/story_points) → skip and report.
- Write failure → report; never claim success when the write failed.
- Never override an existing record without explicit confirmation.
