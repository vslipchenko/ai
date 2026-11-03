---
name: restore
description: Reopen Claude Code sessions saved earlier with the `save` skill — each resumed in its original folder (`claude --resume <id>`) and in the same kind of terminal it ran in (Windows — Git Bash, PowerShell, cmd, Windows Terminal; Linux — bash/zsh/fish in GNOME Terminal, Konsole, kitty, tmux, WSL in Windows Terminal, ...), falling back to another shell or terminal if that one is gone. Use when the user wants to restore / reopen / bring back / resume their saved Claude sessions or terminals, e.g. "restore my sessions", "reopen the sessions I saved before the reboot", "bring back yesterday's sessions", "restore them all in Git Bash", "restore them in tmux", or to set how sessions are restored ("always restore in Git Bash"). Windows and Linux.
---

# Sessions — Restore

Reopen the sessions from a snapshot made by `save`, each running
`claude --resume <id>` in its folder and in the shell and terminal it was saved
from.

**Windows:**
- **Git Bash** → a Git Bash (mintty) window, or a Windows Terminal tab if it
  ran inside Windows Terminal;
- **PowerShell 7 / Windows PowerShell / cmd** → a standalone console window if
  it ran in one; otherwise a Windows Terminal tab (one window for all of them),
  or a console window without Windows Terminal;
- **unknown** (older snapshots) → Windows PowerShell.
- Missing shell → PowerShell 7, else Windows PowerShell, else cmd.

**Linux:**
- the same shell (bash, zsh, fish, sh) in the same terminal (GNOME Terminal,
  Ptyxis, Console, Konsole, xfce4-terminal, Tilix, Terminator, kitty, WezTerm,
  Alacritty, foot, xterm);
- **tmux** → a new window in the same tmux session (the session is recreated,
  detached, if tmux was restarted);
- **WSL inside Windows Terminal** → a Windows Terminal tab running WSL;
- missing shell → bash, else sh; missing terminal → Windows Terminal (in WSL),
  the system default terminal, any installed terminal, and finally a detached
  tmux session (e.g. with no desktop, over SSH);
- VS Code / editor terminals can't be opened from outside → another terminal.

Whatever falls back, the session still opens and the result says why.

## Script

Pick the command for the OS you're running on (the environment tells you the
platform); the options and JSON output are identical.

- **Windows** — run with the PowerShell tool (or Bash):
  ```
  powershell -NoProfile -ExecutionPolicy Bypass -File "${CLAUDE_PLUGIN_ROOT}/scripts/sessions.ps1" <command> [options]
  ```
- **Linux** — run with Bash:
  ```
  python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sessions.py" <command> [options]
  ```
  If `python3` is not installed, tell the user the plugin needs Python 3 on
  Linux (e.g. `sudo apt install python3`) and stop.
- **macOS** — not supported yet: say so and stop.

If `${CLAUDE_PLUGIN_ROOT}` above was not replaced with a real path, use the
folder two levels above this skill's base directory instead. Pass
`-DataDir "${CLAUDE_PLUGIN_DATA}"` exactly as written; the script handles an
empty or unreplaced value. Every command prints one JSON line; `"ok": false`
carries `error` and `message` — report the message and stop (`no-snapshots`:
tell the user to run the `save` skill first).

## Choosing the terminal

Precedence: per-run options → saved default → what each session ran in.

- **This run only** ("restore them in Git Bash", "use tmux this time"): add
  `-UseShell <shell>` and/or `-Terminal <terminal>` to `restore`:
  - Windows — shells `gitbash|pwsh|powershell|cmd`; terminals `wt|window`
    (`window` = Git Bash's own window, or a plain console window);
  - Linux — shells `bash|zsh|fish|sh`; terminals `gnome-terminal|ptyxis|kgx|
    konsole|xfce4-terminal|tilix|terminator|kitty|wezterm|alacritty|foot|xterm|
    x-terminal-emulator|tmux|wt` (`kgx` = GNOME Console, `wt` = Windows Terminal
    from WSL).
- **From now on** ("always restore in Git Bash"): save it as the default:
  ```
  ... config -DataDir "${CLAUDE_PLUGIN_DATA}" [-UseShell <shell>] [-Terminal <terminal>]
  ```
  `-UseShell auto` / `-Terminal auto` clear one setting; `-Reset` clears both;
  `config` alone shows the current defaults. Confirm the new default in one
  line. If the user only asked to change the default, stop there.

## Step 1 — Pick sessions (only if asked)

Only one snapshot is kept (each `save` replaces the previous one), so there is
nothing to choose between: restore it. Restore every session in it unless the
user asked to choose. If they did, read the snapshot first:

```
... snapshots -DataDir "${CLAUDE_PLUGIN_DATA}"
```

Result: `snapshots[]` (normally one) with `createdAt`, `restoredAt`, `count`,
`pending`, `sessions[]` (`sessionId`, `title`, `cwd`, `lastPrompt`). Ask with
`multiSelect` options (label = title, description = folder), split across
questions of up to 4 options as in the `save` skill, and pass the chosen ids
with `-Ids`.

If the user asks for an older set of sessions, explain that only the most
recent save is kept.

## Step 2 — Restore

```
... restore -DataDir "${CLAUDE_PLUGIN_DATA}" [-Ids <id1>,<id2>,...] [-UseShell <shell>] [-Terminal <terminal>]
```

Result: `launched[]` and `skipped[]` (each with `sessionId`, `title`, `cwd`).
Launched rows also carry `shell`, `terminal`, `savedShell` and `fallback` (null,
or why a different shell or terminal was used), and on Linux `tmuxSession` for
tmux; skipped rows carry `reason`. Sessions that are already open are skipped,
so restoring twice never opens duplicates. The snapshot records which sessions
were dealt with; once all are, the next `save` replaces it without asking.

`terminal` values: `wt` = Windows Terminal tab, `window` = own window
(Windows), `tmux`, or the Linux terminal's name.

Report in plain text:
- what was opened, as `title — folder — shell, terminal`;
- each fallback, e.g. "opened in Windows PowerShell because Git Bash was not
  found", "opened in xterm because Konsole is not installed";
- for tmux: the session name, and that it can be reached with
  `tmux attach -t <tmuxSession>` if it isn't already on screen;
- each skipped session with its reason in plain words:
  - `already-running` — that session is already open;
  - `folder-missing` — the folder was moved or deleted;
  - `transcript-missing` — Claude Code no longer has that conversation
    (deleted or cleaned up after the retention period), so it can't be resumed;
  - `no-shell` (Windows) / `no-terminal` (Linux) — no usable shell or terminal
    was found at all;
  - `bad-id` — the snapshot entry is damaged.

If nothing was launched, say so plainly.
