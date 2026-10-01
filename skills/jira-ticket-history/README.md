# jira-ticket-history

*The complete history of a Jira ticket, as a `git log` you can click through.*

Collects everything Jira recorded about one ticket — every field change,
comment and worklog — and renders it as a single local HTML page: one line per
change, newest first, with who and when. Click a line to see what changed:
line diffs for description edits (or the full text after the edit, with the
changes marked), word diffs for title changes, and old → new for everything
else.

Works on any Jira Cloud or Data Center site, through an Atlassian MCP if you
have one connected or an API token if you don't. Configured once and stored in
your home directory, overridable for any single run.

## Install

This is a **standalone skill**, not a plugin — there's no `claude plugin
install` for it. Put the folder where Claude Code looks for skills:

```bash
# personal (available in every project)
cp -r skills/jira-ticket-history ~/.claude/skills/jira-ticket-history

# or project-local (this project only)
cp -r skills/jira-ticket-history /path/to/project/.claude/skills/jira-ticket-history
```

(Symlink instead of `cp -r` if you want it to track updates from this repo.)
Restart Claude Code (or reload skills) afterwards.

## Example

```
> show me the history of ABC-123

Wrote ~/jira-history/ABC-123-history.html and opened it.
  84 entries — changelog 70/70 (2 pages), comments 13/13, worklogs 0/0
```

The page:

```
$ jira-ticket-history ABC-123
Retry failed webhook deliveries with backoff
Story · To Review · Major

[x] All 84 | [x] Status 7  [x] Assignee 7  [x] Description 8  [x] Title 3  [x] Other fields 19
             [x] Comments 14  [x] Issue links 13  [x] Web links 16  [ ] Attachments 0  [ ] Worklogs 0
[ ] Hide automation   Newest first   Expand all

▶ 9475268  Sep 29 19:25  Dana Reyes      Assign to Sam Okafor                              Assignee
▼ 9475114  Sep 29 18:59  Dana Reyes      Edit description (+1 −0)                          Description
    ┌ description (+1 −0) ─────────────────────────────────────── [Diff] [Full text] ┐
    │   *AC 6 — MedianCPM threaded into deal create/save*                            │
    │ + *Known limitation found during implementation:* AC 6 above is fully met …    │
    │   h2. Todo                                                                     │
    └────────────────────────────────────────────────────────────────────────────────┘
▶ c849017  Sep 29 18:51  Dana Reyes      @Sam you were right, our fix didn't cover this…   Comments
▶ 9447534  Sep 25 16:24  Dana Reyes      (To Review) Move to To Review                     Status
▶ 9443512  Sep 25 11:17  Automation for Jira  This work item is tested by ABC-140   [automation]
```

The header also has an author shortlog (`git shortlog -sn`), a **Fetched**
panel showing how much of each source came back, and, when your site has the
development integration, counts of branches, pull requests and builds.

## What's on the page

- **Every changelog entry, comment and worklog**, plus a root **Create** entry
  with the values the ticket started with.
- **Filters** by activity type, with counts. Tick **All** to reset:

  | Type | What it covers |
  |---|---|
  | Status | status changes, labelled with the new status like a branch name |
  | Assignee | assignment and unassignment |
  | Description | description edits: Diff, or Full text after the edit |
  | Title | title changes, as a word diff |
  | Other fields | every other system or custom field |
  | Comments | comments (Jira's own formatting), replies, deleted comments |
  | Issue links | links to other tickets, parent changes |
  | Web links | remote links, e.g. pull requests someone linked |
  | Attachments | files added or removed |
  | Worklogs | logged time, and time-tracking field changes |

- **Hide automation**: entries by Jira apps, plus any accounts you mark as
  bots during setup.
- **Honest edge cases.** Edits that only changed markup or escape characters
  say so instead of showing a noisy diff. Text that Jira stored with broken
  characters (`â€”` for `—`) is shown repaired, with a note on the edit that
  introduced it and the one that fixed it.

## First run: setup

The first time, the skill configures itself instead of guessing:

1. **Site** — taken from a ticket URL if you paste one.
2. **Access** — an Atlassian MCP if one is connected, otherwise the names of
   the environment variables that hold your credentials. It detects Cloud vs
   Data Center for you.
3. **A sample ticket** — one you know, so the next two choices come from real
   data.
4. **What to track** — everything by default. You can start with some types
   unchecked, or stop collecting specific fields altogether. Excluded fields
   are listed on the page, so a missing one never looks like "never changed".
5. **Automation accounts** — Jira apps are recognised automatically. You pick
   any other bots or service accounts from the sample's authors.
6. **Output** — folder, open automatically, order, time zone.

Everything is shown back to you in plain language before it's saved to
`~/.jira-ticket-history/config.json`.

## Overriding for one run

> "only comments" · "just status and assignee" · "oldest first" · "hide the
> bots" · "in UTC" · "save it to ~/Desktop"

Your saved config is untouched unless you say "save that" or "make that my
default".

## Requirements

Genuinely required:

- **Python 3 or Node ≥ 18** for the bundled scripts (either works; they're
  twins with identical flags and byte-identical output). No third-party
  packages.
- **Read access to the ticket** in Jira, through one of:

  | Path | Needs | Works with |
  |---|---|---|
  | Atlassian MCP | an Atlassian/Jira MCP server connected in Claude Code | Jira Cloud |
  | REST, Cloud | `JIRA_EMAIL` + `JIRA_API_TOKEN` (an [API token](https://id.atlassian.com/manage-profile/security/api-tokens)) | Jira Cloud |
  | REST, Data Center | a personal access token in `JIRA_API_TOKEN` | Jira Server / Data Center 8.14+ |

  The variable names are configurable.
- **A browser** to open the page. It's one self-contained `.html` file.

### Do I need to install an MCP?

**No.** An MCP only saves you creating an API token. If one is connected, the
skill uses it; if not, it uses the REST API with your token and behaves the
same. A skill can't install an MCP — you configure those in Claude Code
(`/mcp` shows what's connected).

### What it can't show

- **Earlier versions of a comment.** Jira doesn't keep them. An edited comment
  shows its latest text and when it was edited.
- **Images and attachment contents.** They need a Jira login, so the page shows
  `[image: name]` and file names.
- **Individual pull requests** unless someone linked them to the ticket. The
  development panel only gives counts.
- **Anything Jira didn't record.** Fields that never changed have no entries.

### Privacy

The skill is **read-only** — it never edits, transitions, comments on or logs
work against a ticket. It talks only to your own Jira site. Tokens are read
from environment variables and never written to the config file or the page.

The page contains **everything the fetching account can see**, including
comments restricted to a group or role. It stays on your machine unless you
ask for it to be published, but check what's in it before sharing it. The page
loads two web fonts from Google Fonts. Offline, it falls back to system fonts.

## Bundled scripts

| Script | Job |
|---|---|
| `scripts/fetch_history.{py,mjs}` | REST path: fetch the issue, the full paged changelog, comments and worklogs into a bundle, with per-source completeness |
| `scripts/build_history.{py,mjs}` | Turn a bundle into the page: classify, order, diff, repair broken characters, flag automation, inject into `assets/template.html` |

Both exist because the parts that must be identical between two runs of the
same ticket — ordering, diffs, escaping, time zones — are exactly the parts a
model re-derives slightly differently each time.

Run the tests with:

```bash
node --test skills/jira-ticket-history/scripts/tests/build_history.test.mjs skills/jira-ticket-history/scripts/tests/fetch_history.test.mjs
python3 -m unittest discover -s skills/jira-ticket-history/scripts/tests
```

(`node --test <dir>` is unreliable — pass explicit files.) The fixture is a
synthetic ticket; no real Jira data is committed.

## License

MIT (repo default — see the root [README](../../README.md)).
