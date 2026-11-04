---
name: clear
description: Delete the saved set of Claude Code sessions (the snapshot made by the `save` skill) without restoring it — only the saved list, never the conversations themselves. Asks first if some saved sessions were never restored. Use when the user wants to remove / delete / clear / discard / forget their saved sessions or snapshot, e.g. "clear sessions", "remove sessions", "clear my saved sessions", "remove my saved sessions", "delete the sessions snapshot", "forget the sessions I saved", "start fresh before a demo", optionally also resetting the restore defaults ("and reset my restore settings"). Windows and Linux.
---

# Sessions — Clear

Delete the snapshot made by `save`, so there is nothing to restore. This removes
only the saved list of sessions: the conversations stay in Claude Code and can
still be resumed one by one (`claude --resume`). The restore defaults set with
`config` (e.g. "always restore in Git Bash") are kept unless the user asks to
reset them too.

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
carries `error` and `message`.

## Step 1 — See what is saved

```
... snapshots -DataDir "${CLAUDE_PLUGIN_DATA}"
```

Result: `snapshots[]` (normally one) with `createdAt`, `restoredAt`, `count`,
`pending` (sessions never restored) and `sessions[]` (`title`, `cwd`).

- No snapshots → say there are no saved sessions. If the user also asked to
  reset the restore defaults, go to Step 2 anyway (the script removes just
  those); otherwise stop.
- `pending` > 0 → ask one single-select question (header `Delete?`): "Your
  saved sessions from <createdAt in local time> include <pending> that were
  never restored (<titles>). Delete the saved list anyway? The conversations
  themselves are kept." Options: `Delete them` / `Keep them`. On Keep, delete
  nothing and stop.
- Everything already restored → no question; the user asked to clear.

## Step 2 — Clear

```
... clear -DataDir "${CLAUDE_PLUGIN_DATA}" [-Force] [-IncludeConfig]
```

- `-Force` — only after the user chose `Delete them` in Step 1. Without it the
  script refuses (`error: unrestored-snapshot`, plus `pendingSnapshot`) while
  there are unrestored sessions: if that happens, ask the Step 1 question.
- `-IncludeConfig` — only if the user asked to reset the restore defaults too.

Result: `removed[]` (snapshot files), `removedSessions` (how many sessions were
in them), `configRemoved`, `configKept` (defaults exist and were left alone).

Report in plain text, briefly:
- what was deleted, e.g. "Deleted the saved list of 5 sessions from 11:05.";
- that the conversations are still there and can be resumed individually;
- if `configKept`: that the restore defaults were kept (and that they can ask
  to reset them); if `configRemoved`: that they were reset;
- if nothing was saved: say so.
