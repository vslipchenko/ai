---
name: save
description: Save the currently open Claude Code terminal sessions (session id + folder + shell) so they can be closed and reopened later (after a reboot, a terminal update, or the next day) with the `restore` skill. Lists the live sessions and lets the user pick which to keep; replaces the previously saved set (asking first if it was never restored). Use when the user wants to save / snapshot / remember / bookmark their open Claude sessions or terminals, e.g. "save my sessions", "I need to reboot, save my claude sessions", "save my sessions, I'm updating my terminal", "save these so I can continue tomorrow". Windows, Linux and macOS.
---

# Sessions — Save

Snapshot the live Claude Code sessions the user picks, so `restore` can reopen
each one in its folder (`claude --resume <id>`) whenever the user wants them
back. Windows, Linux and macOS.

## Script

All discovery and file work is done by one script per OS. Pick the command for
the OS you're running on (the environment tells you the platform); the options
and JSON output are identical.

- **Windows** — run with the PowerShell tool (or Bash):
  ```
  powershell -NoProfile -ExecutionPolicy Bypass -File "${CLAUDE_PLUGIN_ROOT}/scripts/sessions.ps1" <command> [options]
  ```
- **Linux and macOS** — run with Bash:
  ```
  python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sessions.py" <command> [options]
  ```
  If `python3` is not installed, tell the user the plugin needs Python 3 and
  stop: on Linux e.g. `sudo apt install python3`; on macOS `xcode-select --install`
  (Apple's Command Line Tools, which include `/usr/bin/python3`).

If `${CLAUDE_PLUGIN_ROOT}` above was not replaced with a real path, use the
folder two levels above this skill's base directory instead. Pass
`-DataDir "${CLAUDE_PLUGIN_DATA}"` exactly as written; the script handles an
empty or unreplaced value. Every command prints one JSON line; `"ok": false`
carries `error` and `message` — report the message and stop.

## Step 1 — List live sessions

```
... list -DataDir "${CLAUDE_PLUGIN_DATA}" -CurrentSessionId "${CLAUDE_SESSION_ID}"
```

Result: `sessions[]` with `sessionId`, `cwd`, `title`, `lastPrompt`,
`isCurrent`, `shell` and `host`, plus `source`,
`hiddenNonInteractive`, `pendingSnapshot` and `managing`. `shell` and `host` are stored
with the snapshot so `restore` reopens each session in the same kind of
terminal:
- Windows — `shell`: `gitbash` / `pwsh` / `powershell` / `cmd`; `host`: `wt` /
  `console` / `mintty` / `vscode` / `jetbrains`;
- Linux — `shell`: `bash` / `zsh` / `fish` / `sh` / others; `host`: the
  terminal (`gnome-terminal`, `konsole`, `kitty`, `xterm`, …), `tmux` (with
  `tmuxSession`), `wt` (WSL in Windows Terminal), `vscode`, `ssh`;
- macOS — `shell`: `zsh` / `bash` / `fish` / `sh`; `host`: `terminal`
  (Apple's Terminal), `iterm2`, `ghostty`, `kitty`, `wezterm`, `alacritty`,
  `warp`, `tmux`, `vscode`;
- either may be null when it couldn't be detected.

Only one snapshot is kept: saving replaces the previous one. When the previous
one still has sessions that were never restored, `pendingSnapshot` describes it
(`createdAt`, `count`, `pending[]` with `title` and `cwd`); otherwise it is null.

- `managing` true (the session manager — the `manage` skill — is keeping the
  list up to date automatically) → **before anything else**, ask one
  single-select question (header `Manager`): "The session manager is already
  saving your sessions automatically. Turn it off and save a list by hand
  instead?" Options: `Turn it off and save` / `Keep the manager`. On Keep, save
  nothing, say the list is already being kept up to date, and stop. On Turn it
  off: run `... manage -DataDir "${CLAUDE_PLUGIN_DATA}" -Disable`, skip the
  `pendingSnapshot` question below (they already chose to replace the managed
  list) and add `-Force` to the save in Step 3.
- `pendingSnapshot` set → **before anything else**, ask one single-select
  question (header `Replace?`): "Your saved sessions from <createdAt in local
  time> haven't all been restored yet (<pending titles>). Saving now replaces
  them." Options: `Replace them` / `Cancel`. On Cancel, save nothing and suggest
  restoring them first (the `restore` skill), then stop. On Replace, add
  `-Force` to the save in Step 3.
- No sessions → say so and stop.
- `source` is `transcripts` → the live-session list was unavailable; tell the
  user these are sessions **active in the last 12 hours**, some possibly closed.
- `hiddenNonInteractive` > 0 → mention that N background/SDK sessions were left
  out. Re-run with `-IncludeNonInteractive` only if the user asks for them.

## Step 2 — Let the user pick

Build one option per session:
- **label**: the `title` (append ` (this session)` when `isCurrent`). Labels
  must be unique — on a clash append the folder name, then the first 8 chars of
  the id.
- **description**: the `cwd`, then ` · <shell name>` when `shell` is set
  (Git Bash, PowerShell 7, Windows PowerShell, cmd, bash, zsh, fish, …) plus
  the terminal when `host` is set (e.g. `zsh in kitty`, `bash in tmux`), then
  ` · last: <lastPrompt>` when present.

Then, by count:
- **1 session** → don't ask; save it (the user asked to save) and say which.
- **2–4** → one `AskUserQuestion` question, `multiSelect: true`, header
  `Sessions`, e.g. "Which sessions should be saved for restoring later?".
- **5–16** → split across up to 4 `multiSelect` questions of 2–4 options each
  (balance them, e.g. 5 → 3+2), headers `Sessions 1/2`, `Sessions 2/2`, … The
  question tool has no pre-selection, so the current session is identified only
  by its label.
- **More than 16** → print a numbered list (title — folder) and ask the user to
  reply with numbers, ranges, or `all`.

Free-text answers ("all", "all except X") are fine — interpret them. If nothing
is selected, save nothing and say so.

## Step 3 — Save

```
... save -DataDir "${CLAUDE_PLUGIN_DATA}" -Ids <id1>,<id2>,... [-Force]
```

Result: `snapshot` (file path), `saved[]`, `missing[]`, `replaced` (number of
older snapshot files removed). Without `-Force` the script refuses to replace a
snapshot with unrestored sessions (`error: unrestored-snapshot`, plus
`pendingSnapshot`): if that happens, ask the Step 1 question and retry with
`-Force` only if the user chooses Replace.

Report in plain text. Don't assume why the user is saving (reboot, terminal
update, stopping for the day…): keep the wording about closing and coming back
later, not about a reboot. Shape:

```
Saved 3 sessions:

- <title> (this session): <folder> (<shell>[, <terminal>])
- ...

Whenever you want them back, start Claude Code in any folder and ask it to
restore your sessions. Each one reopens in its folder, in the same kind of
terminal it ran in.

- Let busy sessions finish before closing them: a reply still being written
  when a session is closed is lost.
- Only the conversations come back: dev servers, file watchers and other
  background processes won't restart.
```

Mention `missing` ids only when there are any (that session ended and its
conversation is gone, so it wasn't saved).
