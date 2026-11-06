# Privacy Policy

The sessions plugin does not collect, transmit, or share any data with the plugin author or any third party. It makes no network connections.

## What it reads

To list the Claude Code sessions running on your machine, the plugin reads, locally:

- Claude Code's session files in `~/.claude/sessions/` (session id, folder, process id and start time)
- the running processes, to check that each session is still alive and to tell which shell and terminal it runs in
- the transcript of each session it lists, only for the session's title and last prompt; if the session files are missing, it finds sessions from the transcripts written in the last 12 hours instead

## Data storage

All data the plugin creates is stored locally on your machine in the plugin's data folder, `~/.claude/plugins/data/sessions-vslipchenko/`:

- `snapshots/` — the one saved set of sessions: for each session its id, folder, title, last prompt, shell, terminal, and start time
- `config.json` — your restore defaults, if you set any
- `tracking` — present only while the session manager is on

Each save replaces the previous set, so nothing piles up. The folder is never read or accessed by anyone other than you.

## External connections

None. Restoring opens terminal windows on your own machine; on macOS, opening Terminal or iTerm2 asks for macOS Automation permission the first time.

No analytics, telemetry, or usage data is sent anywhere.

## Uninstalling

To remove the saved set, say *"clear sessions"*. Uninstalling the plugin deletes the whole data folder, unless you pass `--keep-data`.
