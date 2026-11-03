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
- Session ids are validated as GUIDs before they reach any command line.
  Per-shell launch quoting (all covered by `-Launch` tests — rerun them after
  touching `New-LaunchSpec`):
  - PowerShell: command via `-EncodedCommand`, no quoting needed.
  - Git Bash: POSIX paths in single-quoted bash literals, no `;` in the command;
    mintty is launched like `git-bash.exe` does (`MSYSTEM=MINGW64`), wt uses
    `Git\bin\bash.exe`. `;` is escaped as `\;` for `wt`.
  - cmd: `/k <exe> --resume <id>` with at most one pair of quotes (prefer the
    8.3 short path); `wt` re-tokenizes, so nested `""…""` quoting breaks there.
- Shell detection walks parent processes (`Get-LaunchInfo`). Git Bash's chain
  usually ends before mintty (msys re-launches bash), so `host = null` +
  `gitbash` restores to mintty. Restore must always fall back
  (wanted → pwsh → powershell → cmd) rather than skip a session.
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
