---
description: Scan the estimator history for broken records, delete them (after confirmation), and report fixable quality issues. Takes no arguments.
---

# Estimator — Prune History

Scan `history.csv` for low-quality records, delete the genuinely broken ones
after confirmation, and report fixable issues. Takes no arguments — it scans the
whole dataset.

## Data location

Resolve `<DATA_DIR>` as the other components do — the per-user data dir `~/.estimator`:
- Bash: `DATA_DIR="$HOME/.estimator"`
- PowerShell: `$DATA_DIR = Join-Path $env:USERPROFILE '.estimator'`

## Step 1 — Preflight

Resolve `<DATA_DIR>`. If `<DATA_DIR>/history.csv` does not exist, tell the user
to run `/sync` first, and stop.

## Step 2 — Detect

Run with the first available runtime:
1. `python3 "$CLAUDE_PLUGIN_ROOT/commands/scripts/prune_records.py" detect "<DATA_DIR>/history.csv"`
2. else `python "$CLAUDE_PLUGIN_ROOT/commands/scripts/prune_records.py" detect "<DATA_DIR>/history.csv"`
3. else `py -3 "$CLAUDE_PLUGIN_ROOT/commands/scripts/prune_records.py" detect "<DATA_DIR>/history.csv"`
4. else `node "$CLAUDE_PLUGIN_ROOT/commands/scripts/prune_records.mjs" detect "<DATA_DIR>/history.csv"`
5. else **fallback**: read `<DATA_DIR>/history.csv` yourself (`;`-delimited, RFC
   4180 quoting, records may span lines) and classify each 1-based data row by
   the rules below.

Output JSON: `{"prune":[{"row":N,"key":"…","reasons":[…]}],"flag":[{"row":N,"key":"…","warnings":[…]}]}`.

**Rules** — *prune* if any of: `key` blank · `summary` blank · `story_points`
blank or non-numeric (a plain non-negative integer/decimal is valid; `0` is
valid). *flag* (only if not pruned) if any of: `estimate_basis` ∉ {actual,
final, suggested} · `issue_type` blank.

## Step 3 — Present

Show two sections:
- **Prune candidates**: for each, `row`, key (or `(no key)`), and reasons.
- **Flagged (fixable)**: for each, `row`, key, and warnings.
If both are empty, tell the user the dataset is clean and stop.

## Step 4 — Confirm & delete

Default selection = all prune candidates; let the user exclude specific rows by
number. Suggest backing up the dataset first with the `export` skill (it copies
`history.csv`/`config.json` to a path you choose) — the write replaces
`history.csv` in place. On explicit confirmation, write the chosen row numbers
to `<DATA_DIR>/_prune.tmp.json` as `{"rows":[…]}` and run:
1. `python3 "$CLAUDE_PLUGIN_ROOT/commands/scripts/prune_records.py" apply "<DATA_DIR>/history.csv" "<DATA_DIR>/_prune.tmp.json"`
2. else `python "$CLAUDE_PLUGIN_ROOT/commands/scripts/prune_records.py" apply "<DATA_DIR>/history.csv" "<DATA_DIR>/_prune.tmp.json"`
3. else `py -3 "$CLAUDE_PLUGIN_ROOT/commands/scripts/prune_records.py" apply "<DATA_DIR>/history.csv" "<DATA_DIR>/_prune.tmp.json"`
4. else `node "$CLAUDE_PLUGIN_ROOT/commands/scripts/prune_records.mjs" apply "<DATA_DIR>/history.csv" "<DATA_DIR>/_prune.tmp.json"`
5. else **fallback**: delete those data rows yourself with the Write tool,
   applying the build_csv rules (13 columns; `;` delimiter; `, ` for multi-value;
   `\n\n` for comments; RFC 4180 quoting).

The script prints `{"deleted_rows":[…],"deleted_keys":[…],"row_count":N}`. Delete
`_prune.tmp.json`. Update `config.json` `row_count` to the reported value. Report
what was deleted. If the user excludes everything / declines, change nothing.

## Step 5 — Report flagged

List the flagged records and how to fix them with `/edit` (e.g. backfill
`estimate_basis`, set `issue_type`). **Never delete flagged rows.**

(`$CLAUDE_PLUGIN_ROOT` is the plugin root provided to commands; if unset, resolve
the scripts relative to this command file's directory.)

## Error handling

- No `history.csv` → guide to `/sync`.
- Nothing broken or flagged → report clean, change nothing.
- Write failure → report; never claim success on failure.
- Nothing deleted without explicit confirmation; flagged rows are never deleted.
