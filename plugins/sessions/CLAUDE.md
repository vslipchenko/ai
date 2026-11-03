# Working on the sessions plugin

(Only read when working in this repo; no effect on the installed plugin.)

## Layout
- `skills/save/SKILL.md`, `skills/restore/SKILL.md` — interaction only (listing,
  asking, reporting).
- `scripts/sessions.ps1` — all discovery, snapshot I/O and terminal launching.
  Subcommands `list | save | snapshots | restore`; one JSON line on stdout.
- `scripts/tests/sessions.tests.ps1` — self-contained tests (no Pester).

## Rules
- Windows-only, so PowerShell only (no Python/Node pair). Must run on Windows
  PowerShell 5.1: no `?:`, `??`, `?.`, `&&`/`||`. StrictMode 2 is on — read JSON
  properties via `Get-Prop`, and wrap function results in `@()` before `.Count`.
- Variable names are case-insensitive: don't reuse `$e` next to `$E`, etc.
- Session ids are validated as GUIDs before they reach any command line; the
  resume command is passed via `-EncodedCommand`, so paths and titles need no
  shell or `wt` quoting beyond the tab title sanitizer.
- Inputs rely on undocumented Claude Code files: `~/.claude/sessions/<pid>.json`
  (`pid`, `sessionId`, `cwd`, `procStart` = FILETIME, `kind`, `name`) and
  transcript records (`custom-title`, `ai-title`, `last-prompt`, `cwd`). Keep the
  transcript fallback working when either changes.
- Skills use `${CLAUDE_PLUGIN_ROOT}`, `${CLAUDE_PLUGIN_DATA}` and
  `${CLAUDE_SESSION_ID}` (substituted into skill text, not set in the shell).
  The script's data-dir fallback must stay equal to Claude Code's folder for
  `sessions@vslipchenko`.

## Tests
```
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\tests\sessions.tests.ps1          # fast
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\tests\sessions.tests.ps1 -Launch  # + real wt/window launch
```
Run `claude plugin validate .` before considering a change done.
