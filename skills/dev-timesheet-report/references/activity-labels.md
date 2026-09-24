# Activity labels and rules

## Default vocabulary

Presented at setup as a starting point, not a fixed set. The user can rename,
drop or add any of them; only the rules that reference a label need to change
with it.

| Label | What it usually means |
|---|---|
| `Coding` | commits, branches, PRs opened/merged, tickets moved into a working status |
| `Code Review` | reviews, approvals and review comments on others' work |
| `Investigation` | ticket comments, tickets opened, analysis with no commit to show |
| `Testing` | moves into a QA/testing status — only when the team has no dedicated QA, see below |
| `Documentation` | Confluence pages created, edited or commented |
| `Other` | the `default_activity` fallback; should be rare |

Every label here is produced by a rule from real evidence. **A label no source
can populate does not belong in the vocabulary** — it reads as a category the
report tracks when in fact it is always empty, which is worse than not offering
it. `Meeting` was in an earlier version for exactly that reason and was removed:
nothing in git, Jira or Confluence records a meeting, and the one source that
could is not reliable enough to add (see "What the tools cannot see").

Note that `activity_labels` is **advisory** — it drives the setup prompts and
tells you what the rules are expected to produce. The renderer does not enforce
it, so an event carrying an explicit `activity` may use any label at all.

**The set is deliberately small.** Every label answers "what was I doing", and
every row means a person spent time. Past roughly this many, precision costs
more than it returns: misclassification rises, the config grows, and one day's
work on one ticket starts splitting across several lines.

Two rules from earlier versions were **removed on purpose**:

- **`Bug Fixing`** (keyed on `^fix` commits) — fixing a bug *is* coding, and
  the commit prefix was a proxy for the work rather than the work itself.
  Worse, it split a single ticket-day in two whenever one commit out of several
  started with `fix:`. If you need the distinction for billing or CapEx/OpEx
  accounting, re-key it to the ticket's own type — see the cookbook.
- **The `^docs` commit rule** — a docs commit inside a feature ticket is not a
  separate activity, and it split that ticket-day the same way. Confluence
  pages are genuinely separate items, so they keep their own rows.

## Default rules

Shipped in `default-config.json`, in this order:

```json
[
  { "drop": true,             "when": { "type": "jira_assigned" } },
  { "drop": true,             "when": { "type": "jira_transition", "status_to": ["Done", "Closed", "Resolved", "Cancelled", "Won't Do"] } },
  { "label": "Code Review",   "when": { "type": ["pr_review", "pr_comment", "pr_approved"] } },
  { "label": "Testing",       "when": { "type": "jira_transition", "status_to": ["In Testing", "QA", "Ready for QA"] } },
  { "label": "Documentation", "when": { "type": ["confluence_created", "confluence_updated", "confluence_comment"] } },
  { "label": "Investigation", "when": { "type": ["jira_comment", "jira_created"] } },
  { "label": "Coding",        "when": { "type": ["commit", "branch_created", "pr_opened", "pr_updated", "pr_merged", "jira_transition"] } }
]
```

The last rule is deliberately the widest. Every narrower rule must sit above it
or it can never fire — this is the single most common way a custom rule set
goes wrong.

## `Testing` depends on whether the team has dedicated QA

The evidence for `Testing` is the user's own transition into a QA status — and
the user moving a ticket there is a **handoff**, not testing work.

- **Dedicated QA on the team** → the transition means "I handed this to QA".
  Labelling it `Testing` credits the developer with QA's work. Convert the
  `Testing` rule into a drop rule in place and take `Testing` out of the
  vocabulary:

  ```json
  { "drop": true, "when": { "type": "jira_transition", "status_to": ["In Testing", "QA", "Ready for QA"] } }
  ```

  Converting matters: simply deleting the rule lets those statuses fall through
  to the `Coding` catch-all, relabelling a handoff as development work.
- **No dedicated QA** → the transition plausibly means "I am now verifying
  this myself", so the label is worth keeping.

Neither is right for everyone, so setup asks (`SKILL.md` step 6f) rather than
guessing. In both cases the transition marks a moment, never a duration: the
testing itself leaves no trace either way.

## Dropping events

A rule with `"drop": true` instead of a `label` **suppresses the event** — it
produces no row at all.

This is how bookkeeping stays out of the report. Assigning a ticket to yourself or
dragging it to Done is a record *about* work, not work; it takes two seconds
and deserves no line. Without the drop rules these events matched nothing and
landed in `Other`, which put a row on the report saying, in effect, "something
happened here" — the exact operational noise a timesheet should not carry.

Drop rules obey the same first-match-wins ordering as everything else, which is
what lets `-> Done` be dropped while `-> In Progress` falls through to
`Coding` two rules later. An **explicit `activity` on an event still wins over
a drop rule** — pinning a label is always deliberate.

`status_to` values are team-specific, and this now matters twice over: get the
*terminal* status names wrong and real work gets suppressed. Read the actual
workflow statuses out of the board at setup rather than assuming `"In Testing"`
or `"Done"` exist.

## Rule cookbook

**Defect work as its own activity, for billing or CapEx/OpEx accounting.** Key
it on the ticket's own type, not on commit text — that is ground truth about
the work item, and because it is per-ticket rather than per-commit it yields
one row per ticket-day instead of splitting one:

```json
{ "label": "Bug Fixing", "when": { "ticket_type": ["Bug", "Defect", "Incident"] } }
```

Place it above the `Coding` catch-all. This needs the Jira adapter to populate
`ticket_type` (it already requests `issuetype`).

**Conventional commits**, if your team uses them consistently and you do want
the finer split. Each of these must sit above the `Coding` catch-all:

```json
{ "label": "Refactoring",  "when": { "type": "commit", "subject_matches": "^refactor(\\(.+\\))?!?:" } }
{ "label": "Testing",      "when": { "type": "commit", "subject_matches": "^test(\\(.+\\))?!?:" } }
{ "label": "Maintenance",  "when": { "type": "commit", "subject_matches": "^(chore|build|ci)(\\(.+\\))?!?:" } }
```

Be aware of what this buys and costs: a ticket whose day contains both a
`feat:` and a `refactor:` commit becomes two rows. That is the same split that
got `Bug Fixing` removed from the defaults, so add these only if the
distinction is worth a longer report to you.

**A repo that is always one kind of work:**

```json
{ "label": "Documentation", "when": { "repo": "handbook" } }
{ "label": "Deployment",    "when": { "repo": ["infra", "terraform"] } }
```

**A branch convention:**

```json
{ "label": "Deployment", "when": { "branch": "release" } }
```

`branch` matches the whole value case-insensitively, so this catches a branch
literally named `release`. For a prefix like `release/2.1`, use
`subject_matches` against the commit subject instead, or add the branch pattern
to the collector's `--ticket-pattern` work — branch *substring* matching is
deliberately not supported, to keep rule semantics uniform.

**Separating wiki work from code docs**, when "Documentation" is too coarse:

```json
{ "label": "Doc Review",    "when": { "type": "confluence_comment" } }
{ "label": "Spec Writing",  "when": { "type": ["confluence_created", "confluence_updated"] } }
```

The default maps all three Confluence types to `Documentation`, which is the
safe choice but does lump "wrote the RFC" together with "left one comment on
someone else's page."

**Splitting review types:**

```json
{ "label": "Peer Review",     "when": { "type": "pr_approved" } }
{ "label": "Review Feedback", "when": { "type": ["pr_review", "pr_comment"] } }
```

## What the tools cannot see

State this once when first presenting a report, then drop it — repeating it
every run is noise.

Meetings, pairing, mentoring, whiteboard design, reading, support chat and
anything done with no commit, comment or transition behind it leave **no trace
in any of these sources**. A report is a floor on the week's activity, not a
complete account of it. The user can add those lines by hand after export, or
give an event an explicit `activity` to pin one.

**Meetings specifically.** A calendar can be read, and structurally a calendar
event fits this report the same way a Confluence page does — stable id, title,
URL. What it cannot do is establish that the meeting *happened*: every other
source here is proof of work (a commit exists because someone wrote code),
while a calendar invite is proof of intent. Accepted-but-not-attended,
recurring meetings nobody cancels, and meetings that end early all inflate the
week, and a personal calendar carries private appointments that have no place
in a work timesheet. The APIs that do prove attendance (Teams attendance
reports, Meet participant data) are normally organizer- or admin-gated, so the
accurate path is the one most developers cannot reach.

That is why there is no `Meeting` label and no calendar source: the evidence
would be weaker than everything around it, and a row a reader cannot trust
devalues the rows they can.

## Reviewing the labelling

When a report's labels look wrong, the fix is almost always one of:

1. **Anything is `Other`.** No rule matched — usually a `type` this skill emits
   that no rule covers, or a rule field typo (which warns on stderr). `Other`
   should be rare; a cluster of it means a whole event type is unrouted.
2. **Everything is `Coding`.** A narrow rule is sitting below the catch-all.
3. **A label never appears.** Its rule is unreachable, or its source is
   disabled/failing — check the per-source status lines before editing rules.
   `Testing` is the usual suspect: its `status_to` list has to match the team's
   real workflow statuses or it can never fire.
4. **A day you know you worked is empty or short.** Check the drop rules first
   — a terminal status name that is actually a working status in your workflow
   will suppress real activity silently.
5. **Junk ticket ids like `UTF-8`.** `board.projects` is empty, so the generic
   key pattern is in play. Fill in the project keys.
