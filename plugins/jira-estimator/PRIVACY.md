# Privacy Policy

The Jira Estimator plugin does not collect, transmit, or share any data with the plugin author or any third party.

## Data storage

All data the plugin creates is stored locally on your machine in `~/.jira-estimator/`:

- `history.csv` — your team's ticket dataset
- `config.json` — run metadata and preferences

This directory is never read or accessed by anyone other than you.

## External connections

The plugin reads Jira ticket data through **Atlassian's remote MCP server** (`https://mcp.atlassian.com/v2/mcp`), which the plugin declares and you sign in to yourself under your own Atlassian credentials. Requests go only to Atlassian. The plugin author has no access to your Jira instance or the data retrieved from it.

No analytics, telemetry, or usage data is sent anywhere.

## Uninstalling

To remove all stored data, run `/jira-estimator:reset` or delete `~/.jira-estimator` manually.
