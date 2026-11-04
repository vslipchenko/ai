---
name: manage
description: Session manager — keep the saved list of Claude Code sessions up to date automatically instead of saving by hand: once turned on, every new or resumed session is added (with its folder, shell and terminal) and sessions exited on purpose are dropped, so a sudden close, crash or reboot never loses track of them; reopen them later with the `restore` skill. Also turns this off again and reports its status. Use when the user says "manage sessions", "session manager", "start the session manager", "track my sessions automatically", "auto-save my sessions", "stop managing sessions", "turn off the session manager", "are my sessions being managed?". Windows and Linux.
---

# Sessions — Manage

Automatic alternative to `save`. While managing is on, the plugin's hooks run in
every Claude Code session on this machine (in this Claude Code install):

- a session that **starts or is resumed** is added to the saved list (or
  updated, if it's already there);
- a session the user **exits on purpose** (`/exit`, Ctrl+D, `/logout`) is
  dropped; `/clear` and `/resume` swap it for the new session;
- a session that is **cut off** — window closed, process killed, crash, power
  loss, reboot — stays on the list.

The list is the same snapshot `restore` reopens. Managing stays on until
turned off, across reboots.

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
carries `error` and `message` — report the message and stop.

## What did the user ask for?

- **Turn on** ("manage sessions", "session manager", "auto-save my
  sessions") → [Turn on](#turn-on).
- **Turn off** ("stop managing", "turn off the session manager") →
  [Turn off](#turn-off).
- **Status** ("are my sessions being managed?") →
  `... manage -DataDir "${CLAUDE_PLUGIN_DATA}"` and report `managing`, `since`
  and the sessions on the list (`snapshot.sessions[]`: title — folder).

## Turn on

### Step 1 — Look at what's open and what's saved

```
... list -DataDir "${CLAUDE_PLUGIN_DATA}" -CurrentSessionId "${CLAUDE_SESSION_ID}"
```

Result: `sessions[]` (the open interactive sessions: `sessionId`, `title`,
`cwd`, `shell`, `host`, `lastPrompt`, `isCurrent`), `managing`, and
`pendingSnapshot`.

- `managing` is already true → say managing is already on, show the sessions
  on the list (run the status command), and ask whether to start over with a
  fresh list. Only continue to Step 2 if they want that.
- `pendingSnapshot` set (a saved list with sessions never restored) → ask one
  single-select question (header `Replace?`): "Your saved sessions from
  <createdAt in local time> haven't all been restored yet (<pending titles>).
  Turning on the session manager replaces that list." Options:
  `Replace them` / `Cancel`. On Cancel, change nothing, suggest restoring them
  first (the `restore` skill), and stop. On Replace, add `-Force` in Step 3.

### Step 2 — Which open sessions to start with

The hooks only see sessions that start or resume from now on, so ask which of
the sessions open right now should be on the list from the start. Build the
options exactly as the `save` skill does (label = title, with ` (this
session)` for `isCurrent`; description = folder · shell[ in terminal] · last
prompt), split across `multiSelect` questions of up to 4 options, header
`Start with`, e.g. "Which of your open sessions should the session manager
start with?". For more than 16, use a numbered list. Free-text answers like
"all" or "none" are fine. If no sessions are open (`sessions[]` empty), skip
the question and start with an empty list.

### Step 3 — Turn it on

```
... manage -DataDir "${CLAUDE_PLUGIN_DATA}" -Enable [-Ids <id1>,<id2>,...] [-Force]
```

Leave out `-Ids` when they picked none. Result: `managing: true`, `saved[]`,
`missing[]`, `replaced`.

Report in plain text, briefly:
- that the session manager is on, and which sessions it starts with
  (`title — folder`), or that it starts empty;
- that from now on new and resumed sessions are added automatically, sessions
  closed with `/exit` are dropped, and anything cut off by a crash, a closed
  window or a reboot stays on the list — to get them back, ask to **restore my
  sessions**;
- that sessions which were already open before the plugin was installed or
  updated only pick this up after `/reload-plugins` or a restart (their end
  isn't seen until then);
- how to stop: "stop managing sessions".

## Turn off

```
... manage -DataDir "${CLAUDE_PLUGIN_DATA}" -Disable
```

Result: `managing: false`, `wasManaging`, `snapshot` (the list as it stands).
Report that the session manager is off (or was already off), and that the
current list (`snapshot.count` sessions) is kept: it can still be restored
with **restore my sessions** or deleted with **clear my sessions**.

## Notes

- While managing is on, a manual `save` is refused (`error: managing`); the
  `save` skill offers to turn managing off first.
- `clear` empties the list but managing keeps running.
- Headless runs (`claude -p`, scripts using the SDK) are never added.
- On Windows the hooks run through Git Bash, which Claude Code uses on Windows.
