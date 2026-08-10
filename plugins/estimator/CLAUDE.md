# Working on the estimator plugin

Operational rules for editing this repo. For *why* the plugin is built this way
see `DESIGN.md`; for *what it does* see `README.md`. (This file is only read when
working **in** this repo — it has no effect on the installed plugin.)

## Layout
- `skills/<name>/SKILL.md` — skill instructions (prose the model follows): `sync`,
  `estimate`, `add`, `find`, `edit`, `export`, `import`.
- `commands/<name>.md` — slash commands: `prune`, `reset`.
- `scripts/` — shared deterministic core: `build_csv.{py,mjs}` (CSV assembly),
  `dump_records.{py,mjs}` (history → JSON). Per-skill scripts under
  `skills/*/scripts/` and `commands/scripts/`. Tests live in `*/tests/`.
- The model does interactive + Jira work; **scripts own all CSV logic**.

## Hard rules
- **Python and Node implementations must stay byte-identical.** Every script has a
  `.py` and `.mjs`; change both together. Output convention: Python
  `json.dumps(obj, ensure_ascii=False, separators=(",", ":"))` to
  `sys.stdout.buffer` + bare `\n` (never `print()`); Node
  `console.log(JSON.stringify(obj))`.
- **After any script change, run BOTH test suites for that pair and keep all green.**
  Add/extend tests with the change (TDD). Don't ship a red suite.
- **Reuse `build_csv` — never reinvent CSV parsing/quoting/dedup.** `FIELD_KEYS` is
  single-sourced from `build_csv`; import it, don't re-derive.
- **Path resolution:** `$CLAUDE_PLUGIN_ROOT`/`$CLAUDE_PLUGIN_DATA` are **empty in a
  skill's shell**. Skills resolve `<PLUGIN_ROOT>` as two levels above the skill's
  announced base dir; data dir is the plain `~/.estimator`. Commands *may* use
  `$CLAUDE_PLUGIN_ROOT` (it's substituted for command bodies).
- **Runtime ladder** for invoking scripts: `python3 → python → py -3 → node →
  Read/Write tool fallback`. Keep this order and full set in every script-invoking
  step.
- **`config.json` writers must preserve keys they don't own** (e.g. `estimation_prefs`,
  `last_exported`). Read-modify-write, never clobber.
- **Read-only Jira:** Jira-touching skills (`sync`, `estimate`, `add`) use only read
  operations — never create/edit/transition/comment/delete. Keep the enumerated
  read-only block.
- **Destructive actions require explicit user confirmation** (reset, prune-delete,
  export/import overwrite/replace, overwriting an existing row).
- **Skill output is plain text** (renders in a terminal — no HTML entities/markup).

## Running tests & validation (Windows)
- Bare `python`/`python3` are often Microsoft Store **stubs** (exit 49) — use `py -3`
  (or your real interpreter) to run the Python suites.
- `node --test <dir>` is unreliable — always pass an explicit test **file**, e.g.
  `node --test scripts/tests/build_csv.test.mjs`.
- Verify cross-runtime parity by running both CLIs on a shared fixture and diffing
  stdout when you touch a script.
- Run `claude plugin validate .` before considering a change done.

## Conventions
- Don't commit `__pycache__/`, `*.pyc`, `node_modules/`, `.idea/`, `.estimator/`,
  or `docs/` — all gitignored. Clean stray `__pycache__` after test runs.
- No usernames, machine paths, or internal project/company identifiers in committed
  files (skills/scripts/README/DESIGN). Examples use generic placeholders
  (`PROJ`, `ABC-123`, `customfield_10016`).
- Features go design-first (brainstorm → spec → plan → implement); specs/plans are
  kept in `docs/` (local, gitignored).
