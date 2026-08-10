---
description: Delete the estimator's stored history dataset (history.csv + config.json) on demand.
---

# Estimator — Reset Stored Data

Delete the estimator's stored dataset so the user can start over, or clear the
data left behind in `~/.estimator` after uninstalling the plugin.

This is a **destructive** action. Confirm with the user before deleting anything.

## Step 1 — Resolve the data directory

Use the same location the `sync` skill uses — the per-user data dir `~/.estimator`:

- Bash: `DATA_DIR="$HOME/.estimator"`
- PowerShell: `$DATA_DIR = Join-Path $env:USERPROFILE '.estimator'`

## Step 2 — Show what will be deleted

List the target files that actually exist in `<DATA_DIR>`: `history.csv`,
`config.json`, and any leftover `_*.tmp.json` scratch files (e.g.
`_records.tmp.json`, `_add.tmp.json`, `_prune.tmp.json`). Show the absolute
`<DATA_DIR>` path and the matched files.

If none of those exist, tell the user there is nothing to remove and stop — do
not create or delete anything.

## Step 3 — Confirm

Ask the user to confirm the deletion explicitly (e.g. "Delete these N files?").
Do not proceed without a clear yes. If the user declines, stop and change nothing.

## Step 4 — Delete and report

On confirmation, delete `history.csv`, `config.json`, and any `_*.tmp.json`
scratch files from `<DATA_DIR>`. Remove the directory itself only if it is now
empty. Then report exactly which files and directories were removed.

Note: this does not uninstall the plugin. Conversely, uninstalling the plugin
does **not** remove `~/.estimator` — it is a normal home dotfolder, so use this
command (or `rm -rf ~/.estimator`) to clear the data.
