# How the page is built

What `build_history` decides, and why. Load this when debugging a surprising
entry, or before changing the scripts or the template.

## Division of labour

- **`build_history.{py,mjs}`** decides everything that must be the same on every
  run: which entries exist, their order, their type, their one-line message,
  diffs, broken-character repair, what counts as automation, and completeness
  warnings. The two runtimes are twins and produce **byte-identical** pages;
  a test enforces it.
- **`assets/template.html`** is fixed. It renders the data it is given: the
  header, filters, rows, diffs, the wiki-markup converter and the sanitiser for
  Jira's HTML. The data goes in at the `/*__DATA__*/null` placeholder as JSON with
  every `<` escaped, and `__TITLE__` becomes `<KEY> History`.

Never hand-write or hand-edit the page. A page assembled by the model would
drift from the design between runs, which is the one thing this skill exists
to prevent.

## Entries ("commits")

One per changelog entry, one per comment, one per worklog, plus a root
**Create** entry. Ids are Jira's own ids — changelog ids as-is, `c<id>` for
comments, `w<id>` for worklogs, `i<issue id>` for creation — so any entry can be
traced back.

- **Order:** by instant, then creation < changelog < comment < worklog, then id.
- **Create** shows the values the ticket was created with. Jira does not store
  them directly, so each is taken from the `fromString` of the first change to
  that field, or from the current value if the field never changed.
- **Message:** the entry's primary change (status, then assignee, then title,
  then description, then anything else), plus `(+N more)`.
- **Status changes** carry the new status as a label, like a branch name in
  `git log`. There is no HEAD marker — the current status is in the header.

## Text fields

`description`, `environment`, and any field whose value contains a newline or
is ADF, are treated as multi-line text:

1. **Repair broken characters** (below), then convert ADF to wiki markup, so the
   two storage formats compare as one.
2. **Diff lines** (LCS), pairing each changed line with its replacement for a
   **word-level** highlight. Unchanged runs collapse to `⋯ N unchanged lines`
   with one line of context either side.
3. **Full text**: the whole value after the edit, rendered as Jira would, with
   changed blocks and words marked.
4. If the only differences are backslash escapes or blank lines, the entry is
   **"Reformat … (markup only)"** and shows a note instead of a diff.

Escapes Jira adds when converting editor content (`\-`, `\(`, `\.`, …) are
dropped for display. `\*` and `\_` are kept, so the renderer shows a literal
asterisk instead of starting bold text.

Titles get a word diff of old against new. Other single-line fields show
`old → new`. Labels show `+added −removed`. Cascading selects, which Jira logs
as `Parent values: A(10)Level 1 values: B(11)`, show as `A / B`.

Past about 4 million comparison cells a diff degrades to "whole value replaced"
rather than hanging on a huge field.

## Broken characters (mojibake)

Some tools save UTF-8 text decoded as Windows-1252, so Jira stores `â€”` where
the author typed `—`. Every text value is repaired before use, **conservatively**:
a run is rewritten only if re-encoding it as cp1252 gives exactly one valid
UTF-8 character. Genuine text such as `naïve`, `Â` or `Zürich` is never touched.

The history stays honest about it:

| Situation | Message | Note on the page |
|---|---|---|
| An edit's only change was repairing them | Fix broken characters in … | "only repaired broken characters that an earlier save had stored" |
| An edit's only change was introducing them | Save … with broken characters | "saved the text with broken characters … shown repaired" |
| A real edit whose result contains them | Edit … | "Jira stored this version with broken characters … shown repaired" |

## Comments

- Jira's own rendered HTML (`renderedBody`) is preferred, so a comment looks as
  it does in Jira. The template sanitises it with an allowlist: no scripts,
  styles, forms or frames, and links only to `http(s)`, `mailto` or site-relative
  paths. Images need a Jira login, so they become `[image: name]` placeholders.
- Replies show `reply to c<id>`. Restricted comments show `visible only to <group>`.
- **Jira keeps no earlier versions of a comment.** An edited comment shows its
  latest text and the time of the edit, nothing more. A **deleted** comment
  appears only through its changelog `Comment` item, with its last text.

## Automation

An entry is automation if its author has `accountType: "app"` (Jira's own flag,
Cloud only) or the author's id is in `automation_accounts`. Display names are
never matched: a person could be called "Bot", and bots are renamed. Automation
entries are dimmed, tagged, and can be hidden with one checkbox.

## Development panel

Shown only when the issue has Jira's development-summary field, found by its
schema type (`…:devsummarycf`), never by its display name. It gives **counts
only** — branches, commits, pull requests, builds, deployments — because that is
all the field holds. Individual pull requests appear in the log only if someone
linked them to the ticket (as web links).

## Times

Every timestamp is shown in one zone, the machine's local one by default
(`output.timezone`), with the offset visible in each entry's detail line.
