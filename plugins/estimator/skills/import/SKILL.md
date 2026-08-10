---
name: import
description: Import an existing history CSV into the estimator from a file path, instead of building it with `sync`. Use when the user wants to load / import an existing estimation history (e.g. "import my history from ./history.csv", "load this dataset", "import estimator history"). Supports merging into or replacing the current history.
---

# Estimator — Import History

Load an external history CSV into the plugin so a user who already has a dataset
can skip `/sync`. Supports **merge** (into an existing history) and **replace**.

## Data location

Resolve `<DATA_DIR>` as the other skills do — the per-user data dir `~/.estimator`:
- Bash: `DATA_DIR="$HOME/.estimator"`
- PowerShell: `$DATA_DIR = Join-Path $env:USERPROFILE '.estimator'`

## Step 1 — Resolve the source path

Take the source path from the user's message/argument; if none, prompt for it.
Expand `~` and environment variables. Verify the file exists and is readable.
Canonicalize both paths before comparing — expand `~`/env vars, resolve
symlinks, and normalize case on Windows — and if the source resolves to the live
`<DATA_DIR>/history.csv`, refuse (you cannot import a file onto itself).

## Step 2 — Determine mode

If `<DATA_DIR>/history.csv` exists, ask the user: **merge** the imported records
into it (dedup by key, imported wins) or **replace** it entirely. Replace
requires explicit confirmation. If it does not exist, proceed as a straight
import (mode = `replace` into an empty target) — no confirmation needed.

## Step 3 — Import

Run with the first available runtime:
1. `python3 "<PLUGIN_ROOT>/skills/import/scripts/import_records.py" "<source>" "<DATA_DIR>/history.csv" <merge|replace>`
2. else `python "<PLUGIN_ROOT>/skills/import/scripts/import_records.py" "<source>" "<DATA_DIR>/history.csv" <merge|replace>`
3. else `py -3 "<PLUGIN_ROOT>/skills/import/scripts/import_records.py" "<source>" "<DATA_DIR>/history.csv" <merge|replace>`
4. else `node "<PLUGIN_ROOT>/skills/import/scripts/import_records.mjs" "<source>" "<DATA_DIR>/history.csv" <merge|replace>`
5. else **fallback**: read the source yourself; map its columns to the canonical
   fields by the token in each header's trailing parentheses (e.g.
   `Title (summary)` → `summary`); require a `key` column (else reject); merge or
   replace into `<DATA_DIR>/history.csv` applying the build_csv rules (13 columns;
   `;`; `, ` for multi-value; `\n\n` for comments; RFC 4180 quoting); dedup by key
   (imported wins on merge).

The script prints `{"mode":...,"imported":N,"row_count":M,"project_keys":[...]}`,
or exits non-zero with an error (e.g. unrecognized headers / no `key` column).

## Step 4 — Update config

Read `<DATA_DIR>/config.json` if present (else start from `{}`). Set `row_count`
to the reported value and `project_keys` to the reported list; **preserve** any
other existing fields (`story_point_field_id`, `cloud_id`, `jql`,
`updated_watermark`, `min_fetch_story_points`, `estimation_prefs`,
`schema_version`). Write `config.json`.

## Step 5 — Report

Report the mode, imported count, total rows, derived `project_keys`, and the
absolute history path. Suggest `/estimator:prune` to clean any broken rows. Note
that fetching/estimating *new* tickets still needs `story_point_field_id` — run
`/sync` to resolve and cache it.

**Resolving `<PLUGIN_ROOT>`:** `$CLAUDE_PLUGIN_ROOT` is usually empty inside a
skill's shell, so don't rely on it. `<PLUGIN_ROOT>` is the directory **two levels
above this skill's announced base directory** (the base dir shown when this skill
loaded is `…/skills/<name>`, so its parent's parent is the plugin root).
Substitute that absolute path for `<PLUGIN_ROOT>` in the commands above.

## Error handling

- Source missing / unreadable → report and stop.
- Source path is the live `history.csv` → refuse (no self-import).
- Unrecognized headers / no `key` column → reject with guidance (expects
  estimator history columns, e.g. a file produced by the `export` skill or a
  copied `history.csv`).
- Replace → require explicit confirmation before overwriting.
- Write failure → report; never claim success on failure.
