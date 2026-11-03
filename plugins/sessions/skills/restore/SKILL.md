---
name: restore
description: Reopen Claude Code sessions saved earlier with the `save` skill — one terminal tab per session, each resumed in its original folder (`claude --resume <id>`). Use when the user wants to restore / reopen / bring back / resume their saved Claude sessions or terminals, e.g. "restore my sessions", "reopen the sessions I saved before the reboot", "restore yesterday's sessions". Windows only.
---

# Sessions — Restore

Reopen the sessions from a snapshot made by `save`: Windows Terminal gets one
new window with a tab per session (separate PowerShell windows if Windows
Terminal is missing), each running `claude --resume <id>` in the session's
folder. Windows only.

## Script

Run with the PowerShell tool (or Bash — the command is the same):

```
powershell -NoProfile -ExecutionPolicy Bypass -File "${CLAUDE_PLUGIN_ROOT}/scripts/sessions.ps1" <command> [options]
```

If `${CLAUDE_PLUGIN_ROOT}` above was not replaced with a real path, use the
folder two levels above this skill's base directory instead. Pass
`-DataDir "${CLAUDE_PLUGIN_DATA}"` exactly as written; the script handles an
empty or unreplaced value. Every command prints one JSON line; `"ok": false`
carries `error` and `message` — report the message and stop (`no-snapshots`:
tell the user to run the `save` skill first).

## Step 1 — Pick the snapshot

```
... snapshots -DataDir "${CLAUDE_PLUGIN_DATA}"
```

Result: `snapshots[]`, newest first, each with `file`, `createdAt`,
`restoredAt`, `count`, `sessions[]` (`sessionId`, `title`, `cwd`, `lastPrompt`).

- Default: the newest snapshot. Don't ask.
- If the user described another one ("yesterday's", "the one before"), match
  it by `createdAt` (shown in the user's local time); if that's ambiguous, ask
  with a single-select question listing the candidates.
- If the chosen snapshot already has `restoredAt`, mention when — but still go
  ahead; sessions that are already open are skipped automatically, so nothing
  is opened twice.

## Step 2 — Pick sessions (only if asked)

Restore every session in the snapshot unless the user asked to choose. If they
did, ask with `multiSelect` options (label = title, description = folder), split
across questions of up to 4 options as in the `save` skill, and pass the chosen
ids with `-Ids`.

## Step 3 — Restore

```
... restore -DataDir "${CLAUDE_PLUGIN_DATA}" [-Snapshot <file>] [-Ids <id1>,<id2>,...]
```

Result: `launched[]` and `skipped[]` (each with `sessionId`, `title`, `cwd`;
skipped ones also carry `reason`), plus `terminal` (`wt` or `window`). The
snapshot is marked as restored.

Report in plain text: what was opened (`title — folder`) and where (Windows
Terminal window vs separate windows), then each skipped session with its reason
in plain words:
- `already-running` — that session is already open;
- `folder-missing` — the folder was moved or deleted;
- `transcript-missing` — Claude Code no longer has that conversation (deleted
  or cleaned up after the retention period), so it can't be resumed;
- `bad-id` — the snapshot entry is damaged.

If nothing was launched, say so plainly.
