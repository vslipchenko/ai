---
name: export
description: Export / back up the estimator's stored dataset (history.csv, and optionally config.json) to a file path the user chooses. Use when the user wants to back up, export, snapshot, or copy out their estimation history (e.g. "export my history to ~/backups", "back up the estimator data", "save a copy of the history before resetting"). Counterpart to the import skill.
---

# Estimator — Export Data

Copy the stored dataset to a location the user chooses, for **backup** or
**migration** (e.g. before a `/estimator:reset` or uninstall, or to move the
dataset to another machine). Counterpart to the `import` skill.

## Data location

Resolve `<DATA_DIR>` as the other skills do — the per-user data dir `~/.estimator`:
- Bash: `DATA_DIR="$HOME/.estimator"`
- PowerShell: `$DATA_DIR = Join-Path $env:USERPROFILE '.estimator'`

Source files: `<DATA_DIR>/history.csv` and `<DATA_DIR>/config.json`.

## Step 1 — Preflight
Resolve `<DATA_DIR>`. If `<DATA_DIR>/history.csv` does not exist, tell the user
there is nothing to export (suggest `/sync` to build a dataset, or the `import`
skill to load one) and stop.

## Step 2 — Determine the destination
Use the destination path from the user's message if one was given; otherwise ask
the user where to export to. Expand `~` and environment variables in the path.

## Step 3 — Pick the mode (from the path form)
- Destination **ends in `.csv`** → **single-file mode**: copy *only*
  `history.csv` to that exact path (a named data backup, e.g.
  `~/backups/estimator-2026-06.csv`).
- **Otherwise** → **directory mode**: treat the path as a directory and copy
  `history.csv` into it, keeping its name (any path without a `.csv` suffix is
  treated as a directory). **Ask the user whether to also include `config.json`**
  (the sync metadata — JQL, story-point field id, project keys); copy it only if
  they say yes. Create the directory (including parents) if it does not exist.

## Step 4 — Overwrite guard
Resolve the absolute target path(s). If any target file already exists, show
which one(s) and ask the user to confirm overwrite before proceeding. If the
user declines, stop and copy nothing.

## Step 5 — Record the export, copy & report
First, **record the export time** in the source config so backups carry it: get
the current UTC time from the shell (`date -u +%Y-%m-%dT%H:%M:%SZ`, or PowerShell
`([datetime]::UtcNow).ToString('yyyy-MM-ddTHH:mm:ssZ')` — same format, don't
fabricate it), then update
`<DATA_DIR>/config.json` to set `last_exported` to that timestamp, **preserving
every other key** (create `config.json` with just `last_exported` if it doesn't
exist). Doing this before the copy means a directory-mode backup that includes
`config.json` carries the export time.

Then copy the file(s). In directory mode, if the user chose to include
`config.json` but it is missing, warn and still copy `history.csv`. Finally,
report exactly which file(s) were copied, the absolute destination path(s), and
the recorded `last_exported` time.

## Error handling
- No `history.csv` → guide to `/sync` or the `import` skill; nothing to export.
- Destination unwritable / invalid path / copy failure → report the error
  clearly; do not claim success.
- Existing target file → require explicit confirmation (never silent overwrite).
