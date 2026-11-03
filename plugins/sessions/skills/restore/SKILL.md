---
name: restore
description: Reopen Claude Code sessions saved earlier with the `save` skill — each resumed in its original folder (`claude --resume <id>`) and in the same kind of terminal it ran in (Git Bash, PowerShell, cmd), falling back to PowerShell or cmd if that terminal is gone. Use when the user wants to restore / reopen / bring back / resume their saved Claude sessions or terminals, e.g. "restore my sessions", "reopen the sessions I saved before the reboot", "restore them all in Git Bash", or to set how sessions are restored ("always restore in Git Bash"). Windows only.
---

# Sessions — Restore

Reopen the sessions from a snapshot made by `save`, each running
`claude --resume <id>` in its folder and in the shell it was saved from:

- **Git Bash** → a Git Bash (mintty) window, or a Windows Terminal tab if it
  ran inside Windows Terminal;
- **PowerShell 7 / Windows PowerShell / cmd** → a standalone console window if
  it ran in one; otherwise a Windows Terminal tab (one window for all of them),
  or a console window without Windows Terminal;
- **unknown** (older snapshots) → Windows PowerShell.

If the saved shell is no longer installed, the session still opens — in
PowerShell 7, else Windows PowerShell, else cmd — and the result says why.
Windows only.

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

## Choosing the terminal

Precedence: per-run options → saved default → what each session ran in.

- **This run only** ("restore them in Git Bash", "use cmd this time"): add
  `-UseShell gitbash|pwsh|powershell|cmd` and/or `-Terminal wt|window`
  (`window` = Git Bash's own window, or a plain console window) to `restore`.
- **From now on** ("always restore in Git Bash"): save it as the default:
  ```
  ... config -DataDir "${CLAUDE_PLUGIN_DATA}" [-UseShell <shell>] [-Terminal <wt|window>]
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
... restore -DataDir "${CLAUDE_PLUGIN_DATA}" [-Ids <id1>,<id2>,...] [-UseShell <shell>] [-Terminal <wt|window>]
```

Result: `launched[]` and `skipped[]` (each with `sessionId`, `title`, `cwd`).
Launched rows also carry `shell`, `terminal` (`wt` = Windows Terminal tab,
`window` = own window), `savedShell` and `fallback` (null, or why a different
shell or terminal was used); skipped rows carry `reason`. Sessions that are
already open are skipped, so restoring twice never opens duplicates. The
snapshot records which sessions were dealt with; once all are, the next `save`
replaces it without asking.

Report in plain text:
- what was opened, as `title — folder — shell, Windows Terminal tab / window`;
- each fallback, e.g. "opened in Windows PowerShell because Git Bash was not
  found";
- each skipped session with its reason in plain words:
  - `already-running` — that session is already open;
  - `folder-missing` — the folder was moved or deleted;
  - `transcript-missing` — Claude Code no longer has that conversation
    (deleted or cleaned up after the retention period), so it can't be resumed;
  - `no-shell` — no usable shell was found at all (not even cmd);
  - `bad-id` — the snapshot entry is damaged.

If nothing was launched, say so plainly.
