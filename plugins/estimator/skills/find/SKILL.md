---
name: find
description: Look up one or more records in the estimator history by Jira key. Use when the user wants to find / show / inspect a stored ticket record (e.g. "find ABC-7777 in history", "show the record for 7777", "look up ABC-1, ABC-2").
---

# Estimator — Find History Records

Look up records in `history.csv` by Jira key and show their full stored fields.

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
`project_keys`: exactly one cached key → prefix it (`7777` → `ABC-7777`);
several → ask which project; none cached → ask for the project key. If no key
can be determined, prompt the user for the ticket key(s).

## Step 3 — Query the history

Run the lookup with the first available runtime:

1. `python3 "<PLUGIN_ROOT>/skills/find/scripts/find_records.py" "<DATA_DIR>/history.csv" KEY [KEY ...]`
2. else `python "<PLUGIN_ROOT>/skills/find/scripts/find_records.py" "<DATA_DIR>/history.csv" KEY [KEY ...]`
3. else `py -3 "<PLUGIN_ROOT>/skills/find/scripts/find_records.py" "<DATA_DIR>/history.csv" KEY [KEY ...]`
4. else `node "<PLUGIN_ROOT>/skills/find/scripts/find_records.mjs" "<DATA_DIR>/history.csv" KEY [KEY ...]`
5. else **fallback**: read `<DATA_DIR>/history.csv` yourself (treat it as
   `;`-delimited with RFC 4180 quoting — a record may span multiple physical
   lines inside a quoted cell) and select records whose first column equals a
   requested key, tracking each match's 1-based data-row position (header
   excluded).

The script prints JSON:
`{"found": [{"row": N, ...all fields}], "missing": [...]}`.

**Resolving `<PLUGIN_ROOT>`:** `$CLAUDE_PLUGIN_ROOT` is usually empty inside a
skill's shell, so don't rely on it. `<PLUGIN_ROOT>` is the directory **two levels
above this skill's announced base directory** (the base dir shown when this skill
loaded is `…/skills/<name>`, so its parent's parent is the plugin root).
Substitute that absolute path for `<PLUGIN_ROOT>` in the commands above.

## Step 4 — Present

For each found record show its **row number** and **all fields** as
`Label: value`, using the human-readable column names (Key, Parent, Issue Type,
Title, Description, Components, Labels, Story Points, Time Spent [s], Resolution
Date, Comments, Design Link, Estimate Basis). Then list any **missing** keys
plainly. If nothing was found, say so.

## Error handling

- No `history.csv` → guide the user to run `/sync`; do not fabricate data.
- No / unparseable keys → prompt.
- Script runtime unavailable → use the Step-3 fallback.
