---
name: edit
description: Edit fields of existing estimator history records, or delete records, selected by Jira key. Use when the user wants to change / fix / update a stored record's fields or remove records (e.g. "edit ABC-7777", "fix the story points on ABC-1", "delete ABC-2, ABC-3 from history"). Does NOT add new records.
---

# Estimator — Edit / Delete History Records

Edit field(s) of existing records, or delete records, in `history.csv` by Jira
key. Inserting new records is NOT supported (use `/add` or `/sync` to add records).

## Data location

Resolve `<DATA_DIR>` as the other skills do — the per-user data dir `~/.estimator`:
- Bash: `DATA_DIR="$HOME/.estimator"`
- PowerShell: `$DATA_DIR = Join-Path $env:USERPROFILE '.estimator'`

## Step 1 — Preflight

Resolve `<DATA_DIR>`. If `<DATA_DIR>/history.csv` does not exist, tell the user
to run `/sync` first to build the dataset, and stop.

## Step 2 — Resolve the key(s)

Take one or more keys from the user's message/argument (space- or
comma-separated) and uppercase them. Expand bare numbers via `config.json`
`project_keys`: one cached key → prefix (`7777` → `ABC-7777`); several → ask
which project; none cached → ask for the project key. If no key can be
determined, prompt the user.

## Step 3 — Determine the operation

Infer **edit** vs **delete** from the user's wording ("delete/remove …" →
delete; "edit/change/fix/update …" → edit). If unclear, ask which.

## Step 4 — Load current records, report missing

Look up the keys with the find script to fetch current values:
`python3 "<PLUGIN_ROOT>/skills/find/scripts/find_records.py" "<DATA_DIR>/history.csv" KEY [KEY ...]`
(or `python …`, or `py -3 …`, or `node "<PLUGIN_ROOT>/skills/find/scripts/find_records.mjs" …` — same ladder).
Report any keys in the result's `missing` list and proceed with the found ones.
If none were found, stop.

## Step 5a — Edit path

Show the 12 editable columns (everything EXCEPT Key) with their canonical field
keys:
Parent (`parent_key`), Issue Type (`issue_type`), Title (`summary`),
Description (`description`), Components (`components`), Labels (`labels`),
Story Points (`story_points`), Time Spent [s] (`time_spent_seconds`),
Resolution Date (`resolution_date`), Comments (`comments`),
Design Link (`design_link`), Estimate Basis (`estimate_basis`).
Ask which to edit. **Ask whether to apply the same value to all selected records
or set values per-record**, then collect the new value(s). Notes:
- Multi-value columns (Components, Labels, Comments) are set as the **raw cell
  text** — the user types the full value including any separators.
- If a new Estimate Basis value is not `actual`/`final`/`suggested`, **warn** but
  allow it.
Build an `edits` list: `[{"key": "KEY", "fields": {"<canonical_field>": "value", ...}}, ...]`
(uniform → same `fields` for each found key; per-record → that key's own `fields`).

## Step 5b — Delete path

Confirm the exact records to remove; build a `deletes` list of keys.

## Step 6 — Preview & confirm

Show old → new for each edited field, or the records to be deleted. Require
explicit confirmation. If the user declines, stop and change nothing. For a large
or risky change, suggest backing up the dataset first with the `export` skill —
the write replaces `history.csv` in place.

## Step 7 — Apply

Write the instructions to `<DATA_DIR>/_edit.tmp.json`:
`{"edits": [...], "deletes": [...]}`. Run with the first available runtime:

1. `python3 "<PLUGIN_ROOT>/skills/edit/scripts/edit_records.py" "<DATA_DIR>/history.csv" "<DATA_DIR>/_edit.tmp.json"`
2. else `python "<PLUGIN_ROOT>/skills/edit/scripts/edit_records.py" "<DATA_DIR>/history.csv" "<DATA_DIR>/_edit.tmp.json"`
3. else `py -3 "<PLUGIN_ROOT>/skills/edit/scripts/edit_records.py" "<DATA_DIR>/history.csv" "<DATA_DIR>/_edit.tmp.json"`
4. else `node "<PLUGIN_ROOT>/skills/edit/scripts/edit_records.mjs" "<DATA_DIR>/history.csv" "<DATA_DIR>/_edit.tmp.json"`
5. else **fallback**: edit `<DATA_DIR>/history.csv` yourself with the Write tool,
   applying the build_csv rules (13 columns; `;` delimiter; `, ` for multi-value;
   `\n\n` for comments; RFC 4180 quoting). Update the matched rows' cells, remove
   deleted rows, pad any legacy 12-column rows to 13, and NEVER change the `key`
   column.

The script prints `{"updated":[...],"deleted":[...],"missing":[...],"row_count":N}`
(and exits non-zero without writing if an instruction is invalid, e.g. editing
`key`, an unknown field, or a key listed in both edits and deletes). Delete
`_edit.tmp.json`. Update `config.json` `row_count` to the reported value. Report
updated / deleted / missing to the user.

**Resolving `<PLUGIN_ROOT>`:** `$CLAUDE_PLUGIN_ROOT` is usually empty inside a
skill's shell, so don't rely on it. `<PLUGIN_ROOT>` is the directory **two levels
above this skill's announced base directory** (the base dir shown when this skill
loaded is `…/skills/<name>`, so its parent's parent is the plugin root).
Substitute that absolute path for `<PLUGIN_ROOT>` in the commands above.

## Error handling

- No `history.csv` → guide to `/sync`; do not create one.
- No / unparseable keys → prompt.
- All provided keys missing → report, change nothing.
- The script rejects editing `key`, an unknown field, or a key in both edits and
  deletes (reported); never offer `Key` as editable.
- Write failure → report; never claim success when the write failed.
- Nothing is written without explicit confirmation.
