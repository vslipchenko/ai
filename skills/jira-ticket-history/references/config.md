# Config

Stored at `~/.jira-ticket-history/config.json` — the user's home directory, not
a repo — and written once during setup. `default-config.json` next to this file
is the starting shape. Every value can be overridden for a single run without
touching the file (SKILL.md Step 2).

**No secret is ever stored here.** `auth` names environment variables; the
token itself is read from the environment at call time.

## Schema (version 1)

```json
{
  "version": 1,
  "site": "https://acme.atlassian.net",
  "deployment": "auto",
  "access": "auto",
  "auth": { "email_env": "JIRA_EMAIL", "token_env": "JIRA_API_TOKEN" },
  "history": {
    "types": ["status", "assignee", "description", "title", "fields",
              "comments", "links", "weblinks", "attachments", "worklogs"],
    "exclude_fields": ["customfield_10019"]
  },
  "automation_accounts": ["557058:f58131cb-0000-0000-0000-000000000000"],
  "output": { "dir": "~/jira-history", "open": true, "order": "desc",
              "hide_automation": false, "timezone": "local" }
}
```

| Key | Meaning |
|---|---|
| `version` | Always `1`. A higher number or an unparsable file means stop and offer setup — never guess at a partial read. |
| `site` | Jira base URL, no trailing path. Used when the user gives a bare key (`ABC-123`); a full ticket URL carries its own site and wins. |
| `deployment` | `cloud`, `datacenter`, or `auto` (detect with `GET /rest/api/2/serverInfo`). Decides the auth scheme. |
| `access` | `auto` (use an Atlassian MCP if the session has one, else REST), `mcp`, or `rest`. |
| `auth.email_env` | Env var holding the account email. Cloud only (Basic auth is `email:token`). |
| `auth.token_env` | Env var holding the API token (Cloud) or personal access token (Data Center, sent as Bearer). |
| `history.types` | Activity types **checked by default** on the page. Unchecked types are still collected and one click away — this is a default view, not a filter on what is fetched. |
| `history.exclude_fields` | Fields **never collected**. Matched case-insensitively against a changelog item's `fieldId` or `field` name (`customfield_10019`, `Rank`, `labels`). Two pseudo-fields switch off whole sources: `comment` and `worklog`. The page lists what was excluded so a missing field never reads as "never changed". |
| `automation_accounts` | Account ids (Cloud `accountId`, Data Center `key` or `name`) to treat as automation, in addition to accounts Jira itself marks `accountType: "app"`. Never matched by display name. |
| `output.dir` | Folder for `<KEY>-history.html`. `~` is expanded. |
| `output.open` | Open the page in the default browser after writing it. |
| `output.order` | `desc` (newest first) or `asc`. |
| `output.hide_automation` | Start with automation entries hidden. |
| `output.timezone` | `local` (the machine's zone) or `utc`. Every timestamp on the page uses this one zone. |

## The activity types

The ten values of `history.types`, and exactly what puts an entry in each. Every
rule reads Jira's own field identity — `fieldId`, or `field` for the built-in
items that have no id — or the API the record came from. Nothing is inferred
from titles, names or wording.

| Type | Page label | Comes from |
|---|---|---|
| `status` | Status | changelog `status` |
| `assignee` | Assignee | changelog `assignee` |
| `description` | Description | changelog `description` |
| `title` | Title | changelog `summary` |
| `fields` | Other fields | every other changelog field, system or custom |
| `comments` | Comments | the comments API, plus changelog `Comment` items (deletions) |
| `links` | Issue links | changelog `Link`, `IssueParentAssociation`, `parent`, `Epic Link` |
| `weblinks` | Web links | changelog `RemoteWorkItemLink` / `RemoteIssueLink` |
| `attachments` | Attachments | changelog `Attachment` |
| `worklogs` | Worklogs | the worklog API, plus changelog `WorklogId`, `timespent`, `timeestimate`, `timeoriginalestimate` |

An entry with several changes carries several types and shows up under any of
them.

## Partial changes

Handle these without re-running setup, writing the single change back
immediately: change the site, switch access path, add or remove an excluded
field, add or remove an automation account, change the default types, order,
time zone or output folder.
