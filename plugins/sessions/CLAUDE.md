# Working on the sessions plugin

(Only read when working in this repo; no effect on the installed plugin.)

## Layout
- `skills/save/SKILL.md`, `skills/restore/SKILL.md`, `skills/clear/SKILL.md`, `skills/manage/SKILL.md` (+ `skills/remove/SKILL.md`, a slash-only alias that defers to `clear`; skills have no alias field) — interaction only (listing,
  asking, reporting); they pick the script by OS.
- `scripts/sessions.ps1` (Windows) and `scripts/sessions.py` (Linux) — all
  discovery, snapshot I/O and terminal launching. Same subcommands
  `list | save | snapshots | restore | config | clear | manage | track`, same `-Flag` names, same JSON
  (one line on stdout) and the same snapshot/config files. **Keep them in step:**
  a behaviour change in one needs the same change (and test) in the other.
- Exactly one snapshot is kept. `save` deletes all others after writing, but
  refuses (`unrestored-snapshot`) while the previous one has pending sessions
  (not in `settledSessionIds`) unless `-Force`. `restore` settles launched
  sessions and permanently skipped ones (everything except `no-shell` /
  `no-terminal`). Snapshots without `settledSessionIds` count as settled once
  `restoredAt` is set.
- Order: sessions are kept in the order they were opened (`startedAt`, oldest
  first) — `list` shows them that way (the current session is not pinned), `save`
  stores them that way whatever order they were picked in, and `restore` reopens
  them that way (wt tabs left to right; separate windows one by one with a short
  pause). Snapshots without `startedAt` keep their stored order.
- Session manager (`manage` skill): `manage -Enable` writes a fresh snapshot
  (`"managed": true`) and the flag file `<data>/tracking`; `hooks/hooks.json`
  runs `track` on `SessionStart` (async) and `SessionEnd`. The hook command
  checks the flag file in bash first (cheap no-op when off), picks the script
  with `uname` (hooks run in Git Bash on Windows), and discards output — a
  `SessionStart` hook's stdout would otherwise be added to the session's context.
  `track` reads the hook JSON on stdin and uses `$CLAUDE_PID` to find the
  session's registry file (shell/terminal, start time, `entrypoint`). Rules:
  start/resume/clear/compact → upsert (keep the original `startedAt`, un-settle
  it); end with `prompt_input_exit` / `logout` / `clear` / `resume` → remove;
  `other` (window closed, killed, reboot) → keep. Headless sessions report
  `kind: interactive` but `entrypoint: sdk-*` — never listed or tracked.
  `save` is refused while managing (`error: managing`).
- All snapshot read-modify-writes (track, save, clear, manage, restore's marking)
  go through the snapshot lock (`snapshot.lock`; O_EXCL file on Windows with a
  30 s stale timeout, `flock` on Linux); restore re-reads the file under the lock
  before marking it, because hooks of the sessions it just opened may have
  changed it.
- PowerShell: `Sort-ByOpened` returns its array with `return ,`; assign it
  directly — wrapping the call in `@()` nests the array (`"sessions": [[…]]`).
- Tests: `scripts/tests/sessions.tests.ps1` (Windows, no Pester) and
  `scripts/tests/test_sessions.py` (Linux, stdlib unittest).

## Shared rules
- SKILL.md frontmatter must be strict YAML: an unquoted `description:` may not
  contain `: ` (colon + space) — Claude Code accepts it, strict parsers (and
  WebStorm) don't. Use a dash, or quote the whole value.
- Session ids are validated as GUIDs before they reach any command line.
- `restore` runs inside a Claude session, whose tool shells carry session
  markers (`CLAUDE_CODE_CHILD_SESSION`, `CLAUDE_CODE_SESSION_ID`, messaging
  socket/token, `CLAUDECODE`, ...). Both scripts must drop them before any
  launch, or resumed sessions turn transcript saving off. The launch tests
  assert no marker reaches the launched process.
- Restore must always fall back (another shell / terminal) rather than skip a
  session; only "nothing usable at all" skips (`no-shell` / `no-terminal`).
- Inputs rely on undocumented Claude Code files: `~/.claude/sessions/<pid>.json`
  (`pid`, `sessionId`, `cwd`, `procStart`, `kind`, `name`) and transcript records
  (`custom-title`, `ai-title`, `last-prompt`, `cwd`). Keep the transcript
  fallback working when either changes.
- Skills use `${CLAUDE_PLUGIN_ROOT}`, `${CLAUDE_PLUGIN_DATA}` and
  `${CLAUDE_SESSION_ID}` (substituted into skill text, not set in the shell).
  The scripts' data-dir fallback must stay equal to Claude Code's folder for
  `sessions@vslipchenko`.

## Windows (`sessions.ps1`)
- Must run on Windows PowerShell 5.1: no `?:`, `??`, `?.`, `&&`/`||`.
  StrictMode 2 is on — read JSON properties via `Get-Prop`, and wrap function
  results in `@()` before `.Count`.
- Variable names are case-insensitive: don't reuse `$e` next to `$E`, etc.
- `procStart` = process start as FILETIME.
- Per-shell launch quoting (all covered by `-Launch` tests — rerun them after
  touching `New-LaunchSpec`):
  - PowerShell: command via `-EncodedCommand`, no quoting needed.
  - Git Bash: POSIX paths in single-quoted bash literals, no `;` in the command;
    mintty is launched like `git-bash.exe` does (`MSYSTEM=MINGW64`), wt uses
    `Git\bin\bash.exe`. `;` is escaped as `\;` for `wt`.
  - cmd: `/k <exe> --resume <id>` with at most one pair of quotes (prefer the
    8.3 short path); `wt` re-tokenizes, so nested `""…""` quoting breaks there.
- A shell owning a visible window (`MainWindowHandle` ≠ 0) is in a standalone
  console window → host `console`, restored via `conhost.exe <shell>` so it stays
  a classic window even when Windows hands consoles to Windows Terminal.
  Non-elevated consoles are usually handed to Windows Terminal ("Let Windows
  decide"): parent `explorer.exe`, no window handle → host null → wt. Elevated
  consoles never are — test from an elevated shell only covers the conhost case.
- Git Bash's chain usually ends before mintty (msys re-launches bash), so
  `host = null` + `gitbash` restores to mintty. Fallback order:
  wanted → pwsh → powershell → cmd.

## Linux (`sessions.py`)
- Python 3.8+, standard library only; never a traceback (errors are JSON).
- Processes come from `/proc`: `stat` (comm, ppid, starttime), `exe`, `environ`.
  `procStart` may be `/proc` start ticks or epoch s/ms — all accepted; an unknown
  format falls back to "process is named claude".
- Detection: nearest shell above `claude`, then the first terminal / tmux /
  editor / sshd further up (`HOST_NAMES`), then environment hints (`TMUX`,
  `TERM_PROGRAM`, `KITTY_WINDOW_ID`, `WT_SESSION`, ...). WSL started from Windows
  (Windows Terminal, Start menu) shows up as a chain ending in WSL's
  `Relay(<pid>)` / `SessionLeader` → host `wt`; `WT_SESSION` is usually *not*
  passed into WSL (`WSLENV` empty), so don't rely on it.
- `procStart` on Linux = `/proc/<pid>/stat` field 22 (start ticks), confirmed
  with Claude Code 2.1.317 in WSL.
- wt.exe runs the tab command on the Windows side: pass `wsl.exe` by its Windows
  name, never its `/mnt/c/...` path.
- Commands use single-quote POSIX quoting without `"` and without `;` (fish
  needs `;`, escaped as `\;` for wt), so they survive wt.exe → wsl.exe.
- Launch: `start_new_session=True`, stdio to /dev/null, env with markers removed.
  tmux: new window in the saved session if it exists, else a detached new
  session. Fallback order: saved terminal → wt (WSL) → x-terminal-emulator →
  `GUI_TERMINALS` → tmux; shells: wanted → bash → sh.
- Hidden test overrides `-Terminals` / `-Shells` pretend exactly those are
  installed, so planning tests don't depend on the machine.

## macOS (`sessions.py`, `IS_MAC`)
- Same script as Linux. Processes come from one `ps -axww -o pid=,ppid=,lstart=,comm=`
  table per run (`LC_ALL=C`; start = epoch seconds from `lstart`); `comm` is a
  path, and login shells show as `-zsh` — strip both. Environment hints come
  from `ps -E` (only the keys in `MAC_ENV_KEYS`).
- `procStart` format in Claude Code's macOS session files is **unverified**;
  liveness accepts epoch s/ms within 2 s, else falls back to the process name.
- Terminal and iTerm2 open via `osascript`, with the command and title passed
  as `argv` to `on run argv` — never interpolated into AppleScript text. The run
  is waited for: error -1743 / "not authorized" → skip reason
  `automation-denied`, other errors → `launch-failed` (neither is settled, so a
  later restore retries). Ghostty: `open -na <app> --args …`; kitty, WezTerm,
  Alacritty: the binary inside the app bundle (or on PATH) with the Linux args.
- Fallbacks: shells zsh → bash → sh; terminals saved → `MAC_TERMINALS`
  (Terminal first) → tmux. Warp / editors can't be launched → Terminal.
- `-Platform mac|linux` (hidden) forces either behaviour, so macOS planning tests
  run in WSL too. `launch` in restore rows shows exactly how a window opens.
- Not yet verified on a real Mac: windows really opening, the Automation prompt,
  `procStart`. The CI macOS job runs everything else (Apple's `/usr/bin/python3`).

## CI
`.github/workflows/sessions-plugin.yml` runs the suites on macOS, Linux and
Windows runners for changes under `plugins/sessions/`. Results are also emitted
as annotations (error / notice), readable without auth:
`https://api.github.com/repos/vslipchenko/ai/actions/runs` → the run's
`check_suite` → check-runs → `/annotations`.

## Tests
```
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\tests\sessions.tests.ps1          # Windows, fast
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\tests\sessions.tests.ps1 -Launch  # + real launches
python3 -I scripts/tests/test_sessions.py                                                      # Linux / WSL, fast
SESSIONS_LAUNCH=1 python3 -I scripts/tests/test_sessions.py                                    # + real launches
```
From Windows, run the Linux suite in WSL:
`wsl -d Ubuntu -e bash -lc 'cd /mnt/c/.../plugins/sessions && python3 -I scripts/tests/test_sessions.py'`.
Ubuntu 26.04's coreutils is a multi-call binary: fake executables must be
scripts, not renamed copies of `sleep`. Run `claude plugin validate .` before
considering a change done.
