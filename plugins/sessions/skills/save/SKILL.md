---
name: save
description: Save the currently open Claude Code terminal sessions (session id + folder + shell) so they can be reopened after a reboot with the `restore` skill. Lists the live sessions and lets the user pick which to keep; replaces the previously saved set (asking first if it was never restored). Use when the user wants to save / snapshot / remember / bookmark their open Claude sessions or terminals, e.g. "save my sessions", "I need to reboot, save my claude sessions", "snapshot my open terminals before restart". Windows only.
---

# Sessions — Save

Snapshot the live Claude Code sessions the user picks, so `restore` can reopen
each one in its folder (`claude --resume <id>`) after a reboot. Windows only.

## Script

All discovery and file work is done by one script. Run it with the PowerShell
tool (or Bash — the command is the same):

```
powershell -NoProfile -ExecutionPolicy Bypass -File "${CLAUDE_PLUGIN_ROOT}/scripts/sessions.ps1" <command> [options]
```

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
`isCurrent`, `shell` (`gitbash` / `pwsh` / `powershell` / `cmd` / null) and
`host` (`wt` / `console` / `mintty` / `vscode` / `jetbrains` / null), plus `source`,
`hiddenNonInteractive` and `pendingSnapshot`. `shell` and `host` are stored
with the snapshot so `restore` reopens each session in the same kind of
terminal.

Only one snapshot is kept: saving replaces the previous one. When the previous
one still has sessions that were never restored, `pendingSnapshot` describes it
(`createdAt`, `count`, `pending[]` with `title` and `cwd`); otherwise it is null.

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
  (Git Bash, PowerShell 7, Windows PowerShell, cmd), then
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

Report in plain text:
- how many sessions were saved, listed as `title — folder (shell)`;
- any `missing` ids (the session ended and its transcript is gone);
- that after the reboot they can start Claude Code anywhere and ask to
  **restore their sessions**.

Add two short caveats: a reply that is still being generated when the machine
goes down is lost (let busy sessions finish first), and only the conversations
come back — dev servers, watchers and other background processes do not.
