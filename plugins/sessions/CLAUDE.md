# Working on the sessions plugin

(Only read when working in this repo; no effect on the installed plugin.)

## Layout
- `skills/save/SKILL.md`, `skills/restore/SKILL.md` — interaction only (listing,
  asking, reporting).
- `scripts/sessions.ps1` — all discovery, snapshot I/O and terminal launching.
  Subcommands `list | save | snapshots | restore | config`; one JSON line on stdout.
- Exactly one snapshot is kept. `save` deletes all others after writing, but
  refuses (`unrestored-snapshot`) while the previous one has pending sessions
  (not in `settledSessionIds`) unless `-Force`. `restore` settles launched
  sessions and permanently skipped ones (everything except `no-shell`).
  Snapshots without `settledSessionIds` count as settled once `restoredAt` is set.
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
- `restore` runs inside a Claude session, whose tool shells carry session
  markers (`CLAUDE_CODE_CHILD_SESSION`, `CLAUDE_CODE_SESSION_ID`, messaging
  socket/token, `CLAUDECODE`, ...). `Clear-ClaudeSessionEnv` must drop them
  before any launch, or resumed sessions turn transcript saving off. The
  `-Launch` tests assert no marker reaches the launched process.
- A shell owning a visible window (`MainWindowHandle` ≠ 0) is in a standalone
  console window → host `console`, restored via `conhost.exe <shell>` so it stays
  a classic window even when Windows hands consoles to Windows Terminal.
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
