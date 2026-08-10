# Privacy Policy

The estimator plugin does not collect, transmit, or share any data with the plugin author or any third party.

## Data storage

All data the plugin creates is stored locally on your machine in `~/.estimator/`:

- `history.csv` — your team's ticket dataset
- `config.json` — run metadata and preferences

This directory is never read or accessed by anyone other than you.

## External connections

The plugin reads Jira ticket data through the **Atlassian MCP** — a connection you configure yourself in Claude Code under your own credentials. The plugin author has no access to your Jira instance or the data retrieved from it.

No analytics, telemetry, or usage data is sent anywhere.

## Uninstalling

To remove all stored data, run `/estimator:reset` or delete `~/.estimator` manually.
