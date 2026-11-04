# sessions

*Close your sessions without losing your place: save open Claude Code sessions, then reopen them all in one go.*

Before closing them (a reboot, a terminal update, or just stopping for the
day), ask Claude to **save your sessions**: it lists the Claude Code sessions
running on the machine and lets you pick which to keep. Later, start Claude
Code anywhere and ask it to **restore your sessions**:
each one reopens resumed in its original folder, in the same kind of terminal
it ran in — Git Bash, PowerShell or cmd on Windows; bash, zsh or fish in your
terminal or tmux on Linux.

No more writing session ids down.

## Install

```bash
claude plugin marketplace add vslipchenko/ai
claude plugin install sessions@vslipchenko
```

Then restart Claude Code.

**Requirements:**
- **Windows** 10/11 with Windows PowerShell 5.1 (built in). Git Bash and Windows
  Terminal are used when installed, never required.
- **Linux** with Python 3 (preinstalled on almost every desktop distro). Works
  under WSL too. macOS is not supported yet.

## Skills

| Invoke | What it does |
|---|---|
| `save` | List live Claude Code sessions, let you pick, and store them, replacing the previously saved set. |
| `restore` | Reopen every saved session, each with `claude --resume <id>` in its folder and original terminal. |
| `clear` (also `/sessions:remove`) | Delete the saved set without restoring it (only the list; the conversations stay). Asks first if some were never restored. |

Both respond to natural language, e.g. *"save my sessions, I'm rebooting"*,
*"restore my sessions"*, *"restore just the
API one"*, *"restore them in cmd this time"*, *"restore them in tmux"*,
*"always restore in Git Bash"*, *"clear sessions"* or *"remove sessions"*.

## Where sessions reopen

`save` records the shell each session was started from, and — when it can be
told — the window or terminal it was in.

### Windows

| Saved from | Reopens in |
|---|---|
| Git Bash (its own window) | a Git Bash window |
| Git Bash inside Windows Terminal | a Windows Terminal tab running Git Bash |
| PowerShell 7 / Windows PowerShell / cmd in a standalone console window | a standalone console window with the same shell |
| PowerShell 7 / Windows PowerShell / cmd in Windows Terminal | a Windows Terminal tab (all in one window), or a console window without Windows Terminal |
| VS Code / JetBrains terminal | a Windows Terminal tab with the same shell (editor terminals can't be opened from outside) |
| unknown (e.g. sessions saved by version 1.0.0) | Windows PowerShell |

**Fallbacks.** If the saved shell isn't there any more (say Git Bash was
uninstalled), the session still opens, in PowerShell 7, else Windows
PowerShell, else cmd, and you're told which session fell back and why. A
missing Windows Terminal or Git Bash window (mintty) likewise falls back to
the other.

### Linux

| Saved from | Reopens in |
|---|---|
| bash / zsh / fish / sh in GNOME Terminal, Ptyxis, Console, Konsole, xfce4-terminal, Tilix, Terminator, kitty, WezTerm, Alacritty, foot or xterm | the same shell in the same terminal |
| tmux | a new window in the same tmux session (recreated detached if tmux was restarted; `tmux attach -t <name>`) |
| WSL inside Windows Terminal | a Windows Terminal tab running WSL |
| VS Code terminal, SSH, unknown | the system default / first installed terminal |

**Fallbacks.** On Linux a missing shell falls back to bash, then sh; a missing
terminal to Windows Terminal (under WSL), the system default terminal, any
installed one, and finally a detached tmux session when there is no desktop at
all. Either way the session still opens and you're told which one fell back
and why.

**Overrides.** Ask for a different shell for one restore, or set a default
("always restore in Git Bash"); the default is kept in the plugin's data folder
and can be cleared any time.

## How it works

- **Finding live sessions.** Claude Code keeps a small file per running session
  in `~/.claude/sessions/`. The plugin reads it and checks each entry against
  the actual process (PID and start time), so leftovers from crashed sessions
  and reused PIDs are ignored. Background/SDK sessions are hidden unless you
  ask for them. If that folder is ever missing or its format changes, it falls
  back to transcripts written in the last 12 hours.
- **Labels.** Each session is shown by its title (your `/rename` title, else
  Claude's generated one), folder, and last prompt.
- **Storage.** The saved set is a single small JSON file in the plugin's own
  data folder (`~/.claude/plugins/data/sessions-vslipchenko/snapshots/`), which
  survives reboots and plugin updates. Nothing piles up: each save replaces the
  previous file. If the previous set still has sessions that were never
  restored, `save` asks before replacing it, so a mistaken save later on
  can't wipe what you meant to restore. A default shell, if you set one, is kept
  next to it in `config.json`. Uninstalling the plugin deletes the folder unless
  you pass `--keep-data`.
- **Clean start.** Restored sessions are fully independent: the markers Claude
  Code gives to processes started from inside a session (child-session flag,
  session id, messaging socket) are removed before launching, so each resumed
  session keeps saving its own transcript.
- **Restoring.** Sessions that are already open are skipped, as are sessions
  whose folder or conversation no longer exists, and you're told which and why.

## Limits

- Only conversations come back. Dev servers, watchers and other processes
  started inside a session are not restarted.
- A reply that is still being generated when a session is closed is lost;
  let busy sessions finish first.
- Claude Code deletes old conversations after its retention period
  (`cleanupPeriodDays`, default 30 days); those can't be resumed.
- Windows and Linux only for now (no macOS yet); other AI CLIs are not
  supported yet.

## Without Claude

The script can also be run directly, e.g. to restore without first opening a
Claude session:

On Windows:

```powershell
$p = Get-ChildItem "$env:USERPROFILE\.claude\plugins\cache\vslipchenko\sessions" -Directory | Sort-Object Name | Select-Object -Last 1
powershell -NoProfile -ExecutionPolicy Bypass -File "$($p.FullName)\scripts\sessions.ps1" restore
```

On Linux:

```bash
p=$(ls -d ~/.claude/plugins/cache/vslipchenko/sessions/*/ | sort -V | tail -1)
python3 "$p/scripts/sessions.py" restore
```

Commands: `list`, `save -Ids <id,...> [-Force]`, `snapshots`,
`restore [-Ids <id,...>] [-UseShell <shell>] [-Terminal <terminal>] [-DryRun]`,
`config [-UseShell ...] [-Terminal ...] [-Reset]`, `clear [-Force] [-IncludeConfig]`.

## License

MIT
