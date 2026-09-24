# dev-timesheet-report

*Reconstruct what you actually worked on, from the traces the work left behind.*

Builds a developer timesheet for any date range out of your real activity —
local git commits, your ticket board (Jira), your wiki (Confluence), and your
code hosts (GitHub, GitLab, Bitbucket Cloud) — and prints it in the terminal or
writes it to CSV. Each line is a date, what kind of item it was, its id, its
title, and an activity label.

Configured once, stored in your home directory, and reused every run. Any part
of it can be overridden for a single report without changing the saved defaults.

## Install

This is a **standalone skill**, not a plugin — there's no `claude plugin
install` for it. Put the folder where Claude Code looks for skills:

```bash
# personal (available in every project)
cp -r skills/dev-timesheet-report ~/.claude/skills/dev-timesheet-report

# or project-local (this project only)
cp -r skills/dev-timesheet-report /path/to/project/.claude/skills/dev-timesheet-report
```

(Symlink instead of `cp -r` if you want it to track updates from this repo.)
Restart Claude Code (or reload skills) afterwards.

## Example

```
> What did I work on last week?

Timesheet -- 2026-09-22 to 2026-09-26

2026-09-22 (Tue)
+------------+----------+-------------------------------------+---------------+
| System     | Id       | Title                               | Activity      |
+------------+----------+-------------------------------------+---------------+
| Jira       | ABC-1234 | Fix login redirect loop             | Coding        |
| Jira       | ABC-1240 | Add audit log to admin API, phase 2 | Code Review   |
| Confluence | 393217   | RFC: auth redesign                  | Documentation |
+------------+----------+-------------------------------------+---------------+

2026-09-23 (Wed)
+------------+----------+-------------------------------------+---------------+
| System     | Id       | Title                               | Activity      |
+------------+----------+-------------------------------------+---------------+
| Jira       | ABC-1234 | Fix login redirect loop             | Investigation |
| Jira       | ABC-1299 | Logout crashes on expired session   | Coding        |
+------------+----------+-------------------------------------+---------------+

Summary
  Coding               2 entries
  Code Review          1 entry
  Documentation        1 entry
  Investigation        1 entry
  total lines          5

Range: 2026-09-22 to 2026-09-26 (your week starts Monday)
Sources: local git 31 commits - Jira 12 events - Confluence 4 events - GitHub 5 events
```

Three columns answer adjacent questions, so they're named for what they answer.
Only **System** is on by default:

| Header | Answers | Example |
|---|---|---|
| **System** | which system the id lives in | `Jira`, `Confluence` |
| **Type** | what kind of item it is | `Bug`, `Task`, `Story`, `Page` |
| **Source** | what evidence produced the row | `local-git, github` |

A commit on `ABC-1234` is System `Jira`, Type `Bug`, Source `local-git`. Switch
the other two on with `columns` when you want them:

```
+--------+------+----------+-------------------------+----------+-----------------+
| System | Type | Id       | Title                   | Activity | Source          |
+--------+------+----------+-------------------------+----------+-----------------+
| Jira   | Bug  | ABC-1299 | Logout crashes on expiry| Coding   | local-git, jira |
| Jira   | Task | ABC-1240 | Add audit log           | Coding   | github          |
+--------+------+----------+-------------------------+----------+-----------------+
```

Only Jira and Confluence know an item's Type, so a day that merges commits with
a Jira transition takes the type from the transition — commits never split a
ticket-day just because they don't carry one.

Ask for times and each event stays on its own line:

```
> same thing, with hours

2026-09-22 (Tue)
+-------+--------+----------+-------------------------------------+-------------+
| Time  | System | Id       | Title                               | Activity    |
+-------+--------+----------+-------------------------------------+-------------+
| 09:14 | Jira   | ABC-1234 | Fix login redirect loop             | Coding      |
| 11:05 | Jira   | ABC-1240 | Add audit log to admin API, phase 2 | Code Review |
| 16:40 | Jira   | ABC-1234 | Fix login redirect loop             | Coding      |
+-------+--------+----------+-------------------------------------+-------------+
```

Prefer something lighter? `table_style: "plain"` drops the borders for indented
columns with a single header at the top — narrower, and easier to pipe
elsewhere:

```
  System  Id        Title                                Activity
  ------  --------  -----------------------------------  -----------

2026-09-22 (Tue)
  Jira    ABC-1234  Fix login redirect loop              Coding
  Jira    ABC-1240  Add audit log to admin API, phase 2  Code Review
```

The weekday in the heading and the column header can both be turned off too
(`show_weekday` / `show_header`, or "without the day names" for a single run).
In CSV, date and day are two separate columns — `Date` stays machine-parseable
and `Day` carries `Tue` — so a spreadsheet still reads the date as a date.

Ask for CSV and it goes to a file:

```
> export September to ~/september.csv
5 row(s) written to ~/september.csv
```

## First run: setup

The first time you ask for a report, the skill configures itself instead of
guessing:

1. **Identity** — it looks up your git author emails, GitHub/GitLab logins,
   Jira account id and Bitbucket UUID rather than asking you to recall them,
   then shows you the table to correct. It also offers any *other* author
   addresses it finds in your repos, since work committed under a personal
   email is the usual reason a timesheet comes back mysteriously short.
2. **Local repos** — which clones to scan.
3. **Board** — your Jira site, project keys, and which evidence to pull
   (transitions and comments).
4. **Wiki** — Confluence, off unless you turn it on. If Jira is already set up
   this needs nothing new but your space keys: same site, same token, same
   account. It's what makes a day spent writing an RFC show up at all instead
   of reading as an empty day.
5. **Code hosts** — GitHub, GitLab and/or Bitbucket Cloud, via their CLI
   (`gh`, `glab`) where you're already logged in, or an API token read from an
   environment variable.
6. **Activity labels** — rename, drop or add to the default vocabulary
   (Coding, Code Review, Investigation, Testing, Documentation). It reads your
   board's real workflow statuses so "which mean finished" matches your team
   rather than a guess, and asks whether you have dedicated QA — if you do,
   `Testing` is dropped, since moving a ticket to QA is a handoff rather than
   testing you performed.
7. **Output defaults** — terminal or CSV, which columns, times on or off,
   default range.

Everything is shown back to you in plain language before it's saved to
`~/.dev-timesheet-report/config.json`.

## Overriding for one run

The stored config is the default, not a cage. Say what you want and it applies
to that report only:

> "as a CSV to ~/ts.csv" · "with times" · "just the web-app repo" · "skip Jira
> this time" · "call reviews 'Peer Review'" · "for project ABC only" · "only
> GitLab"

Your saved config is untouched unless you say "save that" or "make that my
default".

## Using only some sources

Every source is independently switchable, and nothing forces you to use all of
them:

| Source | Turn off with |
|---|---|
| Jira | `board.enabled: false` |
| Confluence | `wiki.enabled: false` |
| A local repo | `"enabled": false` on its entry |
| A code host | `"enabled": false` on its entry |

So a GitLab-only setup, or a purely-local-git one, is a normal configuration
rather than a degraded mode. For a single report, just say "only Jira" or "just
GitLab this time" — that leaves your saved config alone.

The `enabled` flag exists so you can park a source without deleting its entry;
deleting means retyping the paths, tokens and keys to bring it back.

Two things worth knowing:

- **The defaults aren't "everything on".** A fresh config has the board
  enabled but with no projects, Confluence off, and no repos or hosts — it's
  inert until setup fills it in. An enabled-but-unconfigured source would just
  produce a failed request every run.
- **Disabled sources are named in the status block**, so a report that's short
  because you switched something off never reads as a quiet week.

## How activity labels are decided

Each piece of evidence is matched against an ordered rule list — first match
wins — so a review on GitHub becomes `Code Review`, a Confluence page becomes
`Documentation`, a Jira comment becomes `Investigation`, and commits become
`Coding`.

**The vocabulary is deliberately small, and that's the point.** Every row means
"a person spent time on this". Finer labels sound appealing until you see the
cost: an earlier version split a ticket by commit prefix, so one day's work on
one bug came out as two rows — `Coding` and `Bug Fixing` — for what was one
continuous sitting. A coarse label that's right beats a precise one that's
usually wrong.

**Bookkeeping is dropped, not labelled.** Assigning yourself a ticket, logging
dragging a card to Done — these are records *about* work, not work,
and they get no row at all rather than a row reading "Other".

If you *do* want a finer split — defect work broken out for CapEx/OpEx
accounting, say, or conventional-commit categories — the cookbook in
[`references/activity-labels.md`](references/activity-labels.md) has the rules,
including why defect work should key on the ticket's type rather than the
commit message. You can also pin a label by hand when the inference is wrong.

## What it can't see

Meetings, pairing, mentoring, whiteboard design, reading and support chat leave
**no trace** in git, Jira, Confluence or a code host. A generated report is a
floor on your week, not a full account of it.

There's deliberately **no `Meeting` label and no calendar source**. A calendar
would fit the report structurally, but it records what was *scheduled*, not
what happened — every other source here exists because someone did something,
while an invite only proves intent. Accepted-but-skipped meetings, recurring
events nobody cancels and meetings that end early would all inflate the week,
and a personal calendar carries appointments that don't belong in a work
timesheet. A row you can't trust devalues the rows you can.

If you want those hours in, add them after export, or pin an explicit activity
on an event — the label list is advisory, not enforced.

## Requirements

Two things are genuinely required:

- **Python 3 or Node ≥ 18** for the two bundled scripts (either works; they're
  twins with identical flags and identical output).
- **git** on `PATH` for local repo scanning.

Everything else is per-source, and each source needs **one** of:

| Source | Needs one of | |
|---|---|---|
| Local git repos | nothing beyond `git` | works offline, no credentials |
| Jira | an Atlassian/Jira MCP server, **or** `JIRA_EMAIL` + `JIRA_API_TOKEN` | |
| Confluence | the same Atlassian credentials | one token covers both |
| GitHub | `gh` (logged in), **or** `GITHUB_TOKEN` | GitHub Enterprise via `base_url` |
| GitLab | `glab` (logged in), **or** `GITLAB_TOKEN` | self-managed via `base_url` |
| Bitbucket Cloud | app password / API token | no CLI or MCP path exists |

### Do I need to install an MCP?

**No.** Every source has a credentials-based path, and an MCP is a convenience
— it saves you creating and storing an Atlassian API token — not a dependency.
If you already have an Atlassian MCP configured in Claude Code, the skill will
use it; if you don't, it uses the REST API with your token and behaves
identically.

Worth knowing: MCP availability varies per session, and a skill can't install
one — that's configured in Claude Code by you (`/mcp` shows what's connected).
That's exactly why nothing here depends on one.

### What you get with less

The skill degrades per source rather than failing:

- **git only** — commits, with ticket ids parsed from commit messages and
  branch names. No ticket titles (you'll see `(title unavailable)`), no review
  activity, no Confluence.
- **git + Jira** — the above plus real titles, ticket comments and status
  transitions. This is the useful minimum for most people.
- **everything** — adds reviews you gave, PRs you opened, and documentation
  days.

A source that can't authenticate is reported as "not configured" next to the
numbers. It is never silently skipped, because a report that's short because of
a missing token looks exactly like a quiet week.

Tokens are always read from environment variables you name in the config. **No
secret is ever written to the config file**, and nothing is sent anywhere
except the APIs you configured.

The skill is **read-only against every source** — it never writes a worklog,
comment or any other record back.

## Bundled scripts

| Script | Job |
|---|---|
| `scripts/collect_git.{py,mjs}` | Scan local repos for your commits in a range, extract ticket ids from subject/body/branch, emit normalized events |
| `scripts/build_report.{py,mjs}` | Apply activity rules, collapse to rows, render the terminal table or RFC 4180 CSV |

Both exist because the parts that must be identical between two runs of the
same week — grouping, sorting, CSV quoting, timezone rendering — are exactly
the parts a model re-derives slightly differently each time.

Run the tests with:

```bash
node --test skills/dev-timesheet-report/scripts/tests/collect_git.test.mjs
node --test skills/dev-timesheet-report/scripts/tests/build_report.test.mjs
python3 -m unittest discover -s skills/dev-timesheet-report/scripts/tests
```

(`node --test <dir>` is unreliable — pass explicit files.)

## License

MIT (repo default — see the root [README](../../README.md)).
