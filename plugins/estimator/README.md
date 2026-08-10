# estimator

*Grounded, explainable Jira story-point estimates — learned from your team's own resolved tickets.*

Estimate Jira tickets from your team's actual history. The plugin pulls resolved
tickets via the Atlassian MCP to build a baseline dataset, then uses it to
suggest effort / story-point estimates for new work by comparing it to similar
past tickets.

## Install

```bash
# register the marketplace, then install the plugin
claude plugin marketplace add vslipchenko/estimator
claude plugin install estimator@vslipchenko
```

Then restart Claude Code. The plugin needs the **Atlassian (Jira) MCP** connected
(run `/mcp` to check). Repository: <https://github.com/vslipchenko/estimator>.

## Skills & commands at a glance

| Invoke | What it does |
|---|---|
| `sync` | Build / refresh the history dataset from resolved, estimated Jira tickets. |
| `estimate` | Suggest story points for a ticket from similar past work, then record the outcome. |
| `add` | Add specific tickets by key (one or many) to the history. |
| `find` | Look up stored records by key. |
| `edit` | Correct fields of, or delete, stored records. |
| `export` / `import` | Back up the dataset / load an existing one (merge or replace). |
| `/estimator:prune` | Scan for and delete broken records (after confirmation). |
| `/estimator:reset` | Delete the stored dataset. |

Skills (`sync`, `estimate`, `add`, `find`, `edit`, `export`, `import`) respond to
natural language; `prune` and `reset` are slash commands.

## Getting started

Run the `sync` skill to build your estimation baseline — and re-run it any time
to top up new or missing tickets:

- Verifies the Atlassian MCP is connected.
- Asks for the project key(s) and how to scope the fetch — a **time window**
  and/or the **latest N** tickets — and, on the first run, a **minimum
  story-points** filter, then builds and confirms a JQL query for resolved,
  estimated tickets.
- Detects your site's "Story Points" custom field.
- Fetches the matching tickets (including parent, all comments, and a design
  link where available) and writes them to a CSV dataset.

Re-running `sync` lets you **refresh** (overwrite) or **append** (fetch only
tickets updated since the last run, merged in).

## Estimate a ticket

Once you have a baseline, ask Claude to estimate a ticket — e.g. *"estimate
ABC-7777"*, *"how many points is this ticket?"* with a Jira link, or just
*"estimate 7777"* (the project key is taken from your `sync` config). The
`estimate` skill:

- Fetches the ticket via the Atlassian MCP.
- Compares it to your history — narrowing by issue type / components / labels,
  then ranking by similarity — and suggests story points in your team's scale,
  with a rationale and the most comparable past tickets.
- Prompts for the value **your team settles on**. If you give one it's recorded
  as `final`; if you skip, the suggestion is recorded as `suggested`.
- Adds the ticket to `history.csv` (prompting before overwriting an existing
  row), so the dataset grows as you estimate.

On the **first** estimate run, the skill asks (once) for your preferred point
**scale** (Fibonacci, linear, powers of two, or a custom scale) and optional
**min/max** limits, caching them in `config.json`. Later runs reuse them to keep
suggestions on your scale and within range; the value your team actually settles
on is always recorded as-is. To change them, edit `config.json`.

### Estimate provenance

Each row records *where its estimate came from* in the `estimate_basis` column:
`actual` (resolved ticket from `sync`), `final` (your team's agreed value), or
`suggested` (the skill's own suggestion). Estimation trusts `actual` over
`final` over `suggested`, so the tool never treats its own guesses as ground
truth. When an estimated ticket is later resolved, re-running `sync` replaces its
row with the real outcome.

## Add specific tickets

Already ran `/sync` but missing a few tickets? Ask Claude to *"add ABC-7777 to
history"* (or several keys / bare numbers). The `add` skill fetches each ticket
from Jira and appends it as a new record — capturing real `story_points`,
`time_spent`, and resolution (so resolved tickets are recorded as `actual`,
open-but-estimated ones as `final`). It only adds tickets that have a key,
summary, and story points, prompts before overriding an existing record, and
reports anything skipped. Field-level edits are handled by the edit skill.

## Find a stored record

Ask Claude to look up records by key — e.g. *"find ABC-7777 in history"*, *"show
the record for 7777"* (bare numbers expand via your `sync` project key), or
*"look up ABC-1, ABC-2"*. The `find` skill prints each matched record's fields
and its **row number** in `history.csv` (for manual reference), and lists any
keys it couldn't find.

## Edit or delete records

Need to correct or remove a stored record? Ask Claude to *"fix the story points
on ABC-7777"*, *"edit ABC-1"*, or *"delete ABC-2, ABC-3 from history"* (bare
numbers expand via your `sync` project key). The `edit` skill:

- Looks up the requested keys and reports any it can't find.
- For an **edit**, changes only the fields you name (validating the new values
  first) and never alters the record's `key`.
- For a **delete**, removes the matched records after you confirm.
- Does **not** insert new records — use `estimate` (or `add`) for that.

## Prune broken records

Run `/estimator:prune` to tidy the dataset. It takes no arguments and scans all
of `history.csv`:

- **Deletes** genuinely broken rows — a missing key, summary, or story points —
  but only after listing them and asking you to confirm.
- **Flags** fixable issues (e.g. a blank/invalid `estimate_basis` or missing
  issue type) so you can repair them with the `edit` skill; flagged rows are
  never deleted.

## Load existing history (import)

Already have a history CSV — from `/estimator:export`, another machine, or a
teammate? Ask Claude to *"import my history from `<path>`"*. The `import` skill
reads the file and either **merges** it into your dataset (dedup by key, imported
wins) or **replaces** it (with explicit confirmation). It maps columns by their
header tokens — tolerant of reordered columns and legacy 12-column files — derives
your `project_keys`, and reports what changed. It's the counterpart to `export`,
and lets you start from an existing dataset without running `/sync`.

## Where data is stored

The dataset lives in a per-user folder in your home directory:

```
~/.estimator/               (a normal home dotfolder, like ~/.aws)
├── history.csv              the ticket dataset (13 columns; ";"-delimited)
└── config.json              run metadata (JQL, field ids, updated watermark,
                             min_fetch_story_points, last_exported,
                             estimation_prefs: scale + min/max limits, …)
```

This is a single global directory per user — built once and reused from any
project.

## Cleanup / uninstall

- **Data lives in `~/.estimator`** (a normal folder in your home). Uninstalling
  the plugin does **not** remove it.
- **Remove it deliberately:** run `/estimator:reset` — it lists the stored files
  (`history.csv`, `config.json`, and any leftover temp file), deletes them after
  you confirm, and removes the `~/.estimator` folder if it ends up empty. Or just
  `rm -rf ~/.estimator`.
- **Back up / migrate:** the `export` skill copies the dataset to a path you
  choose — a folder (`history.csv`, and `config.json` too if you opt in) or a
  `*.csv` file (history only). Restore later with the `import` skill.

## Requirements

- The Atlassian (Jira) MCP connected in Claude Code.
- For CSV assembly the plugin uses, in order of preference, Python 3, then
  Node.js; if neither is available it falls back to building the CSV directly.
  No third-party packages are required.

## License

MIT — see [LICENSE](LICENSE).
