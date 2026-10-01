---
name: dev-timesheet-report
description: Build a developer timesheet for a date range from real activity — local git repos, a ticket board (Jira), a wiki (Confluence), and code hosts (GitHub, GitLab, Bitbucket) — rendered in the terminal or as CSV, with each line showing the date, item type, id, title and an activity label (Coding, Code Review, Investigation, Testing, Documentation). Use when the user asks what they worked on, for a timesheet/activity/work report, to fill in timesheets or a standup/weekly summary, or to export their activity for a period. Configured once and stored, overridable per run.
---

# Dev Timesheet Report

Reconstruct what a developer actually worked on over a date range from the
traces the work left behind, and render it as a timesheet.

The evidence is scattered across systems that each know only part of the story:
local commits know *what changed* but not *why*, the board knows the ticket and
its title but not the hours at the keyboard, the code host knows about review
work that produces no commit at all, and the wiki holds the days that produced
a document instead of a diff. This skill gathers all of them, matches them to
ids, labels each piece of activity, and collapses it into one line per day per
item per activity.

`<SKILL_DIR>` below is this skill's own announced base directory (the path shown
when this skill loads, ending in `.../skills/dev-timesheet-report`). Scripts are
at `<SKILL_DIR>/scripts/`, references at `<SKILL_DIR>/references/`.

**Config lives at `~/.dev-timesheet-report/config.json`** — the user's home
directory, not this repo, matching how `estimator` and `naturalize` store
personal setup. It is written once and reused every run.

This skill is **read-only against every source**. It never writes a worklog,
comment or any other record back to Jira or a code host.

## Prerequisites

**Hard requirements** — without these the skill cannot run at all:

- **Python 3 or Node ≥ 18** for the bundled scripts. Either is fine; they are
  twins. If neither exists, say so and stop (Step 5).
- **`git` on `PATH`**, for local repository scanning.

**Per-source access.** Each source needs one of the following. Nothing here is
required — a source without access is skipped and reported, and the rest of the
report still runs:

| Source | Needs one of |
|---|---|
| Local git repos | nothing beyond `git` — works offline, no credentials |
| Jira | an Atlassian/Jira **MCP server**, or `JIRA_EMAIL` + `JIRA_API_TOKEN` |
| Confluence | the same Atlassian credentials as Jira |
| GitHub | `gh`, authenticated, or `GITHUB_TOKEN` |
| GitLab | `glab`, authenticated, or `GITLAB_TOKEN` |
| Bitbucket Cloud | an app password / API token in the configured env var — no CLI or MCP path exists |

**No MCP is required.** Every source has a credentials-based path, and
`board.access: "auto"` prefers an MCP only when one happens to be present. An
MCP is a convenience — it removes token handling for Atlassian — not a
dependency. Treat its absence as normal, never as a failure.

**This skill cannot install an MCP server**, and neither can you on the user's
behalf. MCP servers are configured in Claude Code by the user (`/mcp` lists
what the session has). If an Atlassian MCP would genuinely help, mention it once
during setup as an alternative to an API token, then move on — do not block on
it and do not re-raise it each run.

**Never treat missing access as "no activity".** A source with no credentials
must report "not configured" and be listed in the Step 7 status block. A
timesheet that is short because a token is missing looks exactly like a quiet
week, and that is the most damaging output this skill can produce.

**Degraded mode is useful.** With nothing but `git`, the report still shows
commits with ticket ids parsed from messages and branch names — it just carries
`missing_title_placeholder` in the Title column and has no review, board or
wiki rows. Say what is missing rather than implying the week was thin.

## Step 1 — Load config, or run first-time setup

Read `~/.dev-timesheet-report/config.json`.

- **Found** → use it, and go to Step 2.
- **Not found** → run Step 6 (setup) first, then come back.
- **Found but `version` is higher than 1, or it does not parse** → say so
  plainly and offer to re-run setup. Do not guess at a partial read; a
  half-understood config produces a plausible-looking wrong timesheet.

The user can force setup again at any time ("reconfigure", "redo my timesheet
setup"). Never re-run setup just because the skill was invoked again.

Load `references/config.md` before reading or writing the config file — the
schema is there, not in memory.

**Then read `config.instructions`.** When it is a non-empty string, it is the
user's standing guidance for every run — treat it as if they had typed it at
the start of this request, and let it shape Steps 2-7. Apply it the way
`references/config.md` ("`instructions`") describes: turn it into per-run
overrides wherever one exists, use it to steer judgment where none does, let
anything said in the current conversation win over it, and never let it
switch off the read-only rule or the Step 7 source reporting.

## Step 2 — Resolve the range and any per-run overrides

**Range.** Explicit wins ("last week", "September 1-7", "yesterday", "this
month"). With nothing given, use `range.default`. Resolve relative phrases
against today's date and `range.week_starts_on`, then **state the resolved
absolute range** in the output header — "last week" is ambiguous enough that a
silent interpretation produces the wrong invoice.

**Overrides.** Anything in the config can be overridden for this run: format,
columns, time granularity, which repos or projects to include, label names, a
source to skip, and the stored `instructions` themselves ("ignore my
instructions this time", "this time also …"). Apply them to an in-memory copy,
on top of whatever the stored instructions already turned into overrides.

**"Only X" means disable everything else** — "only Jira", "just GitLab this
time", "skip the local repos". A single-source report is a legitimate request,
not a degraded one; run it without argument, and name the disabled sources in
the Step 7 status block so a short report is never read as a quiet week.

**Only write to the config file when the user says to** — "save that", "make
that my default", "always do it this way". Otherwise an override is one-off and
the stored config is untouched. If it is genuinely unclear whether the user
means this run or from now on, ask; do not silently make a one-off permanent.

## Step 3 — Collect evidence from every enabled source

Load `references/sources.md` for the per-source query shapes, auth and
normalization rules. Run the sources you can in parallel; they are independent.

**First, check that at least one source is actually enabled.** A source is on
when `board.enabled` / `wiki.enabled` is true, or when `local_repos` /
`code_hosts` contains an entry that is not `"enabled": false`. If nothing is
enabled — or nothing enabled has usable access (Prerequisites) — **say that
plainly and stop**. Do not render an empty report: "No activity found" reads as
a quiet week, when the truth is that nothing was configured to look at.

1. **Local repos** — run `<SKILL_DIR>/scripts/collect_git.{py,mjs}` (Step 5 for
   the runtime order). Never hand-parse `git log`.
2. **Board (Jira)** — the user's status transitions and (if enabled) comments
   in range, plus **ticket titles for every id collected anywhere**.
3. **Wiki (Confluence)**, when `wiki.enabled` — pages created, edited and
   commented in range. This is the only source that makes documentation work
   visible; without it a week spent on an RFC reads as an empty week.
4. **Code hosts** — PRs/MRs opened and merged, and reviews/approvals/comments
   given, by this user in range.

`references/sources.md` opens with **five rules every adapter must follow** —
local-timezone rendering, full pagination, commit de-duplication, token
handling, and reporting failures. The first three are the ones that produce a
report that looks right and is wrong; read them before querying anything.

Every source normalizes to the event schema in `references/config.md`. Extract
ticket ids from commit subjects, branch names, PR titles and bodies; board and
wiki events carry theirs natively. Confluence events must set
`item_type: "confluence"`, `ticket_type: "Page"`, and always populate `url`.
Jira events must keep `issuetype` as `ticket_type` — it is already in the
response and dropping it disables both the `Type` column and any rule keyed on
the issue type.

**When a source fails, keep going and record it.** Partial failure is normal —
a token expired, a VPN is down, `gh` is logged out. Render what succeeded and
report each source's status in Step 7. A silently short timesheet is the worst
possible output of this skill, because it looks complete.

## Step 4 — Label the activity

Rules live in `config.activity_rules`, evaluated in order, **first match wins**;
anything unmatched gets `default_activity`. `build_report` applies them — do not
label events yourself, or two runs over the same week will disagree.

A rule with `"drop": true` instead of a label **suppresses the event**, so it
produces no row. The defaults drop bookkeeping — `jira_assigned`,
and transitions into terminal statuses — because a record
*about* work is not work, and a row saying `Other` is exactly the operational
noise a timesheet should not carry.

Load `references/activity-labels.md` when creating, editing or debugging rules.
The recurring trap is ordering: a narrow rule placed below the catch-all never
fires. The vocabulary is deliberately small — resist adding labels that split
one ticket-day into several rows.

## Step 5 — Render

Run `<SKILL_DIR>/scripts/build_report.{py,mjs}` with the merged events and the
effective config. Try runtimes in order, first one that works — the `.py` and
`.mjs` twins take identical flags and produce identical output:

1. `python3 "<SKILL_DIR>/scripts/build_report.py" [args]`
2. else `python "<SKILL_DIR>/scripts/build_report.py" [args]`
3. else `py -3 "<SKILL_DIR>/scripts/build_report.py" [args]`
4. else `node "<SKILL_DIR>/scripts/build_report.mjs" [args]`

If no runtime is available, say so and stop. Do not format the table by hand:
the grouping, sorting, truncation and CSV quoting are the parts that must be
identical between runs, and a ticket title containing a comma is exactly the
case hand-rolled CSV gets wrong.

Input is one JSON document — events plus the ticket titles fetched in Step 3:

```json
{
  "events": [ { "date": "2026-09-22", "type": "commit", "ticket_ids": ["ABC-1234"], "...": "..." } ],
  "ticket_titles": { "ABC-1234": "Fix login redirect loop" }
}
```

Flags: `--events PATH|-`, `--config PATH`, `--format terminal|csv`, `--out PATH`,
`--columns a,b,c`, `--include-time` / `--no-include-time`, `--title-width N`,
`--range-label TEXT`, `--summary` / `--no-summary`, `--weekday` /
`--no-weekday`, `--header` / `--no-header`, `--table-style grid|plain`,
`--bom` (CSV for Excel).

**Terminal** is the default: each day is its own boxed table, headed by the date
and weekday so the reader can orient without counting dates, with a per-activity
tally underneath.

```
Timesheet -- 2026-09-22 to 2026-09-23

2026-09-22 (Tue)
+------------+----------+----------------------------+---------------+
| System     | Id       | Title                      | Activity      |
+------------+----------+----------------------------+---------------+
| Jira       | ABC-1234 | Fix login redirect loop    | Coding        |
| Jira       | ABC-1240 | Add audit log to admin API | Code Review   |
| Confluence | 393217   | RFC: auth redesign         | Documentation |
+------------+----------+----------------------------+---------------+

2026-09-23 (Wed)
+------------+----------+----------------------------+---------------+
| System     | Id       | Title                      | Activity      |
+------------+----------+----------------------------+---------------+
| Jira       | ABC-1234 | Fix login redirect loop    | Investigation |
+------------+----------+----------------------------+---------------+
```

Three columns answer adjacent questions and are easy to mix up:

| Column | Header | Answers |
|---|---|---|
| `item_type` | **System** | which system the id lives in — `Jira`, `Confluence` |
| `ticket_type` | **Type** | what kind of item — `Bug`, `Task`, `Page` (opt-in) |
| `source` | **Source** | what evidence produced the row — `local-git, github` (opt-in) |

So a commit on `ABC-1234` is System `Jira`, Type `Bug`, Source `local-git`.
Jira rows sort before Confluence rows within a day.

Column widths are computed across the **whole report**, not per day, so the
boxes line up down the page. `--table-style plain` switches to indented columns
with a single header at the top — narrower, and better for piping somewhere
else.

`date` and `day` are the heading, so they are never repeated as columns here.
In CSV they are two ordinary columns instead — `Date` stays machine-parseable
(`2026-09-22`) and `Day` carries `Tue` separately, because `2026-09-22 (Tue)` in
one cell stops a spreadsheet recognizing it as a date.

**CSV** when asked, or when `output.format` is `csv`. Write it to `--out` (or
`output.csv_path`) and tell the user the path; do not dump a CSV into the
terminal, since the point of CSV is to open it somewhere else.

**Times** (`--include-time`) are off by default. Turning them on both adds the
`HH:MM` column *and* stops collapsing a day's events into one line — that is the
"+ hour and minute upon request" behavior, and it makes the report noticeably
longer. Without it, a collapsed line keeps the day's earliest timestamp and an
`evidence` count, so "7 commits" is available via `--columns` when a line needs
justifying.

## Step 6 — First-time setup

Run once, in order, then save to `~/.dev-timesheet-report/config.json` using
`references/default-config.json` as the starting shape.

**6a. Resolve identity — do not interrogate the user.** Nobody knows their Jira
accountId or Bitbucket UUID by heart. Detect what you can
(`references/sources.md` has the lookups), show the resolved table, and let the
user correct it. Scan the configured repos for distinct author addresses and
offer any that look like the same person — a work/personal email split silently
drops half the report.

**6b. Local repos.** Ask which local clones to scan. Offer the current
repository and any sibling directories that are git repos as candidates rather
than asking for paths to be typed.

**6c. Board.** Jira only in v1. Site URL, project keys, and which evidence to
pull (transitions, comments). Say plainly that project keys double as
the ticket-id whitelist: without them, commit parsing will also match `UTF-8`
and `SHA-256`.

Resolve access here too (Prerequisites): if an Atlassian MCP is already in the
session, use it and say no token is needed. If not, ask for the env var names
and mention **once** that an Atlassian MCP configured in Claude Code would
remove the token step. Do not treat its absence as a problem, and do not raise
it again on later runs.

**6d. Wiki.** Ask whether they use Confluence. If Jira is already configured,
say that this needs nothing new but the space keys — same site, same token,
same account id — and that it is what makes documentation days show up at all.
Off by default.

**6e. Code hosts.** Which of GitHub / GitLab / Bitbucket Cloud, and for each,
CLI or token. Check CLI *authentication*, not just that the binary exists.

**6f. Activity labels.** Present the default vocabulary from
`references/activity-labels.md` via `AskUserQuestion` and let the user rename,
drop or add — while saying that the small set is the point, and that extra
labels mostly buy longer reports.

**Then read the board's real workflow statuses** and map them, rather than
shipping the guessed defaults. Two rules depend on it:

- which statuses are *terminal* (the drop rule), and
- which mean *testing*.

The first matters most: a status wrongly listed as terminal silently suppresses
real activity. Show the user the mapping you derived and let them correct it
before saving.

**Ask whether the team has dedicated QA.** A developer's own transition into a
QA status is a handoff, not testing work — see `references/activity-labels.md`.

- **Dedicated QA** → **convert** the `Testing` rule into a drop rule in place,
  and remove `Testing` from `activity_labels`:

  ```json
  { "drop": true, "when": { "type": "jira_transition", "status_to": ["In Testing", "QA", "Ready for QA"] } }
  ```

  **Convert it, never just delete it.** Deleting leaves the QA statuses to fall
  through to the `Coding` catch-all two rules below — which silently relabels a
  handoff as development work, the opposite of what was asked for.
- **No dedicated QA** → keep the `Testing` rule as shipped.

**Do not add a label no source can populate.** If the user asks for one
(`Meeting` is the usual request), say plainly that nothing in git, Jira or
Confluence records it, so the label would always be empty — and that an
always-empty label is worse than none, because it implies the report tracks
something it does not. Point them at "What the tools cannot see" instead.

**6g. Output defaults.** Format, columns, whether times are on, default range,
and a default CSV path if they want one.

Then ask, once and optionally, whether there is anything else the report
should always do or take into account — free text, saved as `instructions`.
Offer an example or two (a ticket prefix that is always Investigation, a
standup summary after the table) so the question is concrete. "No" leaves it
`null`; do not push. If an answer maps cleanly onto a structured field (a
rule, a column, a disabled repo), set that field instead and say so — a
structured setting is checked by the scripts, free text is not.

**6h. Confirm and save.** Show the assembled config in plain language — not raw
JSON — and let the user correct it before writing. Mention that tokens are read
from environment variables and never stored in the file.

**Create `~/.dev-timesheet-report/` if it does not exist** before writing
`config.json` — on a first run it never does. The `cache/` subdirectory is
created the same way when titles are first cached.

Write the file only after the user has confirmed. If the write fails (a
read-only home directory, a permissions problem), say so and offer to run the
report anyway with the settings held for this session only — a config that
cannot be saved is not a reason to refuse the work.

Then run the report the user originally asked for.

### Partial reconfiguration

Handle these without redoing all of 6a-6h, writing the single change back
immediately: add or remove a repo, add a project key, rename a label, edit one
rule, change the default format/columns/range, re-resolve one identity field,
add to / replace / clear the custom `instructions` (show the resulting full
text before writing an addition).

## Step 7 — Deliver

Alongside the report, give a short status block — not a narrative:

- The **resolved absolute range**, always.
- **Per-source status**: how many events each contributed, and plainly which
  ones failed and why. A failed source means the report is incomplete, and that
  must be visible next to the numbers, not buried.
- A one-line note, **the first time only**, that meetings, pairing and other
  untraceable work leave no evidence in any of these sources, so the report is a
  floor on the week rather than a full account of it. Do not repeat it every
  run.
- If `board.projects` is empty, warn that generic ticket-key matching is in
  play and rows like `UTF-8` may be junk.
- If stored `instructions` were applied, one line saying so (not the full
  text), plus any part of them that could not be followed and why.

Offer to save any per-run overrides as the new default only when the user seems
to be repeating them; do not ask after every run.

## Error handling

- **No config** → Step 6, not a guessed report.
- **No Python or Node runtime** → say so and stop. There is no safe hand-rolled
  fallback for CSV quoting or grouping.
- **A source fails** → continue with the rest, report it (Step 3). Never
  silently omit.
- **Jira unreachable but commits collected** → still render, with
  `missing_title_placeholder` in the title column, and say the titles are
  missing rather than leaving blank cells to be misread as untitled tickets.
- **No source enabled** → say that nothing is configured to look at, and offer
  setup or a per-run source. Never render an empty report for this.
- **No activity in range** → say so directly. Check the obvious causes before
  concluding it is a quiet week: an author email missing from `git_authors`, a
  range resolved to the wrong week, every source failing at once, or sources
  switched off by an "only X" override earlier in the conversation.
- **Events dropped for a missing or malformed date** → `build_report` warns on
  stderr with a count. That is an adapter bug, not a user problem: the source
  did not render `date` per rule 1 of `sources.md`. Relay it, since those
  events are silently absent from the report otherwise.
- **The title cache is unreadable** → ignore it and fetch. It is a convenience,
  never a dependency, and a corrupt cache is not a source failure.
- **`git` not on PATH** → local repos are skipped with that reason; remote
  sources still work.
- **Ticket ids that are not tickets** (`UTF-8`, `SHA-256`) → `board.projects`
  is empty. Fill it rather than filtering the rows by hand.
- **Rows labelled `Other`** → no rule matched. `Other` should be rare; a
  cluster of it means an event type is unrouted. See the debugging list at the
  end of `references/activity-labels.md`.
- **A day the user knows they worked comes back empty or short** → check the
  drop rules before anything else. A working status wrongly listed as terminal
  suppresses real activity silently, which is the one failure mode of dropping
  events at all.
