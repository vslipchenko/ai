# sessions

*Close your sessions without losing your place: save open Claude Code sessions, then reopen them all in one go.*

Before closing them (a reboot, a terminal update, or just stopping for the
day), ask Claude to **save your sessions**: it lists the Claude Code sessions
running on the machine and lets you pick which to keep. Later, start Claude
Code anywhere and ask it to **restore your sessions**:
each one reopens resumed in its original folder, in the same kind of terminal
it ran in — Git Bash, PowerShell or cmd on Windows; bash, zsh or fish in your
terminal or tmux on Linux; zsh or bash in Terminal, iTerm2, Ghostty and others
on macOS.

No more writing session ids down. Or let the **session manager** do it: say
*"manage sessions"* once, and every session you start or resume is added to the
list automatically, so even a crash or a sudden reboot loses nothing.

## Install

Pick one of the options below, then restart Claude Code.

### Safe install (recommended)

With the [`safe-install`](../../skills/safe-install) skill installed, run:

```text
/safe-install sessions --marketplace vslipchenko/ai
```

(or `/safe-install sessions@vslipchenko` if you've already added the marketplace).
It scans the plugin (fixed rules, Claude Code's manifest validator and an
isolated AI review) before installing it, and blocks the install on any
critical issue.

### Manual install

```bash
# register the marketplace, then install the plugin
claude plugin marketplace add vslipchenko/ai
claude plugin install sessions@vslipchenko
```

### Quick install via your AI agent (unchecked)

Paste this into Claude Code:

```text
Install this plugin https://github.com/vslipchenko/ai/tree/main/plugins/sessions
```

> [!WARNING]
> Nothing is checked. The agent reads the plugin's files in a session that has
> your permissions, so a tampered file could give it instructions while it
> installs. Use [safe install](#safe-install-recommended) if you want a check.

### Requirements

- **Claude Code in a terminal** (the `claude` CLI). It saves and reopens
  terminal sessions only: sessions in Claude Desktop, the IDE extensions,
  claude.ai chat or Cowork are never listed, and the plugin can't do anything
  when installed there.
- **Windows** 10/11 with Windows PowerShell 5.1 (built in). Git Bash and Windows
  Terminal are used when installed, never required.
- **Linux** with Python 3 (preinstalled on almost every desktop distro). Works
  under WSL too.
- **macOS** with Python 3 from Apple's Command Line Tools (`/usr/bin/python3`;
  installed with `xcode-select --install`, and already there if you use `git`).
  macOS support is tested on GitHub's macOS runners but **not yet on a real
  Mac** — see [Limits](#limits).

## Skills

| Invoke | What it does |
|---|---|
| `save` | List live Claude Code sessions, let you pick, and store them, replacing the previously saved set. |
| `restore` | Reopen every saved session, each with `claude --resume <id>` in its folder and original terminal. |
| `clear` (also `/sessions:remove`) | Delete the saved set without restoring it (only the list; the conversations stay). Asks first if some were never restored. |
| `manage` | Session manager: keep the saved set up to date automatically (see below). Also turns it off and shows its status. |

They respond to natural language, e.g. *"save my sessions, I'm rebooting"*,
*"restore my sessions"*, *"restore just the
API one"*, *"restore them in cmd this time"*, *"restore them in tmux"*,
*"always restore in Git Bash"*, *"clear sessions"* or *"remove sessions"*,
*"manage sessions"*, *"stop managing sessions"*.

## Session manager

Instead of saving by hand, say *"manage sessions"* (or *"session manager"*). It
asks what to start with — **all open sessions**, **some you pick**, or **none**
for a fresh start where only sessions started or resumed from then on are
added — then keeps the list current on its own:

| What happens to a session | On the list? |
|---|---|
| started or resumed (in any folder, any terminal) | added, with its folder, shell and terminal |
| closed with `/exit`, Ctrl+D or `/logout` | dropped — you closed it on purpose |
| `/clear` or `/resume` to another session | swapped for the new one |
| window closed, process killed, crash, power loss, reboot | kept |

Restore them any time with *"restore my sessions"*. Managing stays on across
reboots until you say *"stop managing sessions"*; the list is kept when you
stop. While it's on, a manual `save` asks to turn it off first, and `clear`
empties the list without stopping it.

It works through two plugin hooks (`SessionStart`, `SessionEnd`) that run in the
background and exit at once while managing is off. Headless runs (`claude -p`,
the SDK) are never added. Each Claude Code install (e.g. Windows and WSL) has its
own list. Sessions that were already open when the plugin was installed or
updated pick the hooks up after `/reload-plugins` or a restart.

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

### macOS

| Saved from | Reopens in |
|---|---|
| zsh / bash / fish / sh in Terminal or iTerm2 | a new window of the same app with the same shell (via AppleScript) |
| Ghostty, kitty, WezTerm or Alacritty | a new window of the same terminal |
| tmux | a new window in the same tmux session (recreated detached if tmux was restarted) |
| Warp, VS Code / editor terminal, unknown | Terminal (they can't be opened with a command) |

**Fallbacks.** A missing shell falls back to zsh, then bash, then sh; a missing
terminal to Terminal (it ships with every Mac), then any other installed one,
then a detached tmux session.

**Permission.** The first restore into Terminal or iTerm2 makes macOS ask
whether the app running Claude may control it. If that's refused, the session
is reported as skipped (`automation-denied`) rather than lost — also when the
prompt is left unanswered for 45 seconds: allow it in System Settings › Privacy
& Security › Automation and restore again.

**Overrides.** Ask for a different shell for one restore, or set a default
("always restore in Git Bash"); the default is kept in the plugin's data folder
and can be cleared any time.

## How it works

- **Finding live sessions.** Claude Code keeps a small file per running session
  in `~/.claude/sessions/`. The plugin reads it and checks each entry against
  the actual process (PID and start time), so leftovers from crashed sessions
  and reused PIDs are ignored. Only terminal sessions are offered: sessions of
  Claude Desktop (and Cowork), the VS Code extension panel, headless runs
  (`claude -p`, the SDK) and other apps belong to those apps and are left out
  (Claude Code running in a VS Code terminal is a terminal session and is kept). If that folder is ever missing or its format changes, it falls
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
  session keeps saving its own transcript. So are the "no colour" switch Claude
  sets for its tool commands and the description of the terminal `restore` ran
  in, so each session comes back in full colour and sees its own terminal.
- **Restoring.** Sessions reopen in the order you originally opened them
  (Windows Terminal tabs left to right, windows one after another). Sessions
  that are already open are skipped, as are sessions whose folder or
  conversation no longer exists, and you're told which and why.

## Limits

- Only conversations come back. Dev servers, watchers and other processes
  started inside a session are not restarted.
- A reply that is still being generated when a session is closed is lost;
  let busy sessions finish first.
- Claude Code deletes old conversations after its retention period
  (`cleanupPeriodDays`, default 30 days); those can't be resumed.
- **macOS is not yet tested on a real Mac.** Everything that can run on GitHub's
  macOS runners is tested there (session discovery from `ps`, shell and
  terminal detection, every restore plan, the session manager). Still unchecked:
  windows actually opening in Terminal, iTerm2, Ghostty, kitty, WezTerm and
  Alacritty, the Automation permission prompt, and the exact `procStart` format
  in Claude Code's session files on macOS (any format falls back to a safe
  process-name check). Reports from Mac users are welcome.
- Other AI CLIs are not supported yet.

## Without Claude

The script can also be run directly, e.g. to restore without first opening a
Claude session:

On Windows:

```powershell
$p = Get-ChildItem "$env:USERPROFILE\.claude\plugins\cache\vslipchenko\sessions" -Directory | Sort-Object Name | Select-Object -Last 1
powershell -NoProfile -ExecutionPolicy Bypass -File "$($p.FullName)\scripts\sessions.ps1" restore
```

On Linux and macOS:

```bash
p=$(ls -d ~/.claude/plugins/cache/vslipchenko/sessions/*/ | sort -V | tail -1)
python3 "$p/scripts/sessions.py" restore
```

Commands: `list`, `save -Ids <id,...> [-Force]`, `snapshots`,
`restore [-Ids <id,...>] [-UseShell <shell>] [-Terminal <terminal>] [-DryRun]`,
`config [-UseShell ...] [-Terminal ...] [-Reset]`, `clear [-Force] [-IncludeConfig]`,
`manage [-Enable [-Ids <id,...>] [-Force] | -Disable]`.

## License

MIT
