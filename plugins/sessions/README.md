# sessions

*Reboot without losing your place: save open Claude Code sessions, then reopen them all in one go.*

Before a restart, ask Claude to **save your sessions**: it lists the Claude Code
sessions running on the machine and lets you pick which to keep. After the
restart, start Claude Code anywhere and ask it to **restore your sessions**:
each one reopens resumed in its original folder, in the same kind of terminal
it ran in — Git Bash, PowerShell or cmd.

No more writing session ids down.

## Install

```bash
claude plugin marketplace add vslipchenko/ai
claude plugin install sessions@vslipchenko
```

Then restart Claude Code.

**Requirements:** Windows 10/11 with Windows PowerShell 5.1 (built in).
Git Bash and Windows Terminal are used when installed, never required.

## Skills

| Invoke | What it does |
|---|---|
| `save` | List live Claude Code sessions, let you pick, and store a snapshot. |
| `restore` | Reopen every session from the latest snapshot (or one you name), each with `claude --resume <id>` in its folder and original terminal. |

Both respond to natural language, e.g. *"save my sessions, I'm rebooting"*,
*"restore my sessions"*, *"restore yesterday's sessions"*, *"restore just the
API one"*, *"restore them in cmd this time"*, *"always restore in Git Bash"*.

## Where sessions reopen

`save` records the shell each session was started from, and — when Windows can
tell — the window it was in:

| Saved from | Reopens in |
|---|---|
| Git Bash (its own window) | a Git Bash window |
| Git Bash inside Windows Terminal | a Windows Terminal tab running Git Bash |
| PowerShell 7 / Windows PowerShell / cmd | a Windows Terminal tab (all in one window), or its own console window without Windows Terminal |
| VS Code / JetBrains terminal | a Windows Terminal tab with the same shell (editor terminals can't be opened from outside) |
| unknown (e.g. older snapshots) | Windows PowerShell |

**Fallbacks.** If the saved shell isn't there any more (say Git Bash was
uninstalled), the session still opens, in PowerShell 7, else Windows
PowerShell, else cmd, and you're told which session fell back and why. A
missing Windows Terminal or Git Bash window (mintty) likewise falls back to
the other.

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
- **Storage.** Snapshots are JSON files in the plugin's own data folder
  (`~/.claude/plugins/data/sessions-vslipchenko/snapshots/`), which survives
  reboots and plugin updates. The newest 20 are kept. Uninstalling the plugin
  deletes this folder unless you pass `--keep-data`.
- **Restoring.** Sessions that are already open are skipped, as are sessions
  whose folder or conversation no longer exists, and you're told which and why.

## Limits

- Only conversations come back. Dev servers, watchers and other processes
  started inside a session are not restarted.
- A reply that is still being generated when the machine goes down is lost;
  let busy sessions finish before rebooting.
- Claude Code deletes old conversations after its retention period
  (`cleanupPeriodDays`, default 30 days); those can't be resumed.
- Windows only for now; other AI CLIs are not supported yet.

## Without Claude

The script can also be run directly, e.g. to restore without first opening a
Claude session:

```powershell
$p = Get-ChildItem "$env:USERPROFILE\.claude\plugins\cache\vslipchenko\sessions" -Directory | Sort-Object Name | Select-Object -Last 1
powershell -NoProfile -ExecutionPolicy Bypass -File "$($p.FullName)\scripts\sessions.ps1" restore
```

Commands: `list`, `save -Ids <id,...>`, `snapshots`,
`restore [-Snapshot <file>] [-Ids <id,...>] [-UseShell gitbash|pwsh|powershell|cmd] [-Terminal wt|window] [-DryRun]`,
`config [-UseShell ...] [-Terminal ...] [-Reset]`.

## License

MIT
