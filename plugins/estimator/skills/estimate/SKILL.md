---
name: estimate
description: Estimate a Jira ticket's story points using the team's historical dataset. Use when the user asks to estimate/size/point a ticket (e.g. "estimate ABC-7777", "how many points is this ticket", "estimate 7777", or pastes a Jira ticket link). Fetches the ticket via the Atlassian MCP, compares it to ~/.estimator history, suggests an estimate, then records the outcome.
---

# Estimator — Estimate a Ticket

Suggest a story-point estimate for a Jira ticket, grounded in the team's
historical tickets, then record the outcome back into the dataset. The model
does the fetch + analysis; the bundled `build_csv` script does the CSV write.

## Read-only Jira access

This skill treats Jira purely as a **data source**. Use only read operations —
`atlassianUserInfo`, `getAccessibleAtlassianResources`, project/field metadata,
`searchJiraIssuesUsingJql`, `getJiraIssue`, `getJiraIssueRemoteIssueLinks`. You
MUST NOT call any operation that creates, edits, transitions, comments on,
links, assigns, deletes, or logs work against Jira issues (or writes to
Confluence). If a step seems to require a write, stop and tell the user instead
of proceeding.

## Data location

Resolve `<DATA_DIR>` exactly as the `sync` skill does — the per-user data dir `~/.estimator`:

- Bash: `DATA_DIR="$HOME/.estimator"`
- PowerShell: `$DATA_DIR = Join-Path $env:USERPROFILE '.estimator'`

Files: `<DATA_DIR>/history.csv` (the dataset) and `<DATA_DIR>/config.json`
(holds `story_point_field_id` and `project_keys`, written by `sync`).

## Step 1 — Preflight

1. Resolve `<DATA_DIR>`. If `history.csv` does not exist, tell the user to run
   `/sync` first to build the baseline, and stop. If it exists but has no rows
   with `estimate_basis` of `actual` or `final`, warn that the suggestion will be
   low-confidence (little real history to compare against).
2. Verify the Atlassian MCP is connected (`atlassianUserInfo`). If not, tell the
   user to connect it (`/mcp`) and stop.
3. Read `config.json` for `story_point_field_id` and `project_keys`.
4. Read `estimation_prefs` from `config.json`. If the key is **absent**, this is
   the first estimate run — run the first-run prompt in **Estimation
   preferences** below and persist the result before continuing. If it is
   present, load it silently (no prompt).

### Estimation preferences (scale + limits)

`estimation_prefs` is a cached object that shapes the skill's **suggestion**
(never the team's entered value):

```json
"estimation_prefs": {
  "point_scale": [1, 2, 3, 5, 8, 13, 21],
  "point_scale_note": "",
  "min_story_points": 1,
  "max_story_points": 13
}
```

- `point_scale` — allowed values the suggestion snaps to; `null` → infer from
  history.
- `point_scale_note` — optional free text for a custom scale to interpret (e.g.
  `"XS/S/M/L map to 1/3/5/8"`); may be `""`.
- `min_story_points` / `max_story_points` — optional numeric caps; either/both
  may be `null`.

**First-run prompt** (only when the `estimation_prefs` key is absent). Ask the
user, one at a time:

1. **Point scale** — offer:
   - Fibonacci — `1, 2, 3, 5, 8, 13, 21`
   - Modified Fibonacci — `0.5, 1, 2, 3, 5, 8, 13, 20, 40, 100`
   - Linear — `1, 2, 3, 4, 5`
   - Powers of two — `1, 2, 4, 8, 16`
   - **Custom** — the user gives explicit values and/or a short description;
     store numeric values in `point_scale` and any description in
     `point_scale_note`.
   - **Skip** — leave `point_scale` `null` and infer from history.
2. **Min / max** — optional; either or both may be left blank (→ `null`).
   Validate `min ≤ max` when both are given; on inversion, re-ask.

Then write the `estimation_prefs` object into `config.json`, **preserving every
other existing key** (`story_point_field_id`, `project_keys`, …). Create
`config.json` if it does not exist. To change these later the user edits
`config.json` (or deletes the `estimation_prefs` key to be re-prompted).

## Step 2 — Resolve the ticket reference

Take the reference from the user's message/argument. Accept any of:
- **Jira URL** (e.g. `https://site.atlassian.net/browse/ABC-7777`) → extract the
  key `ABC-7777`.
- **Issue key** (`ABC-7777`) → use as-is.
- **Bare number** (`7777`) → expand using `config.json` `project_keys`: if
  exactly one project key is cached, prefix it (`ABC-7777`); if several, ask the
  user which project; if none cached, ask for the project key.
- **Nothing provided** → ask the user for the ticket id or link.

## Step 3 — Fetch the target ticket

Use `getJiraIssue` for the resolved key, requesting the same fields `sync`
captures: `summary, issuetype, description, components, labels, parent,
timespent, <story_point_field_id>, comment`; also fetch remote/web links
(`getJiraIssueRemoteIssueLinks`) for the design link. Render description and
comments to plain text (strip ADF/markup). Collect: `key, parent_key,
issue_type, summary, description, components` (array), `labels` (array),
`comments` (array), `design_link`. The target is usually open, so
`story_points`, `time_spent_seconds`, and `resolution_date` are typically empty
(capture any existing story-point value for reference, but the goal is to
suggest one).

If the ticket cannot be fetched (not found / no access), report it and stop.

(MCP responses can be large — if you save a response to inspect it, parse it with
the runtime, and request only the fields listed above.)

## Step 4 — Produce the suggested estimate (core analysis)

First **load all history records as JSON** with the first available runtime
(`<PLUGIN_ROOT>` resolves as described in Step 7 below):
1. `python3 "<PLUGIN_ROOT>/scripts/dump_records.py" "<DATA_DIR>/history.csv"`
2. else `python "<PLUGIN_ROOT>/scripts/dump_records.py" "<DATA_DIR>/history.csv"`
3. else `py -3 "<PLUGIN_ROOT>/scripts/dump_records.py" "<DATA_DIR>/history.csv"`
4. else `node "<PLUGIN_ROOT>/scripts/dump_records.mjs" "<DATA_DIR>/history.csv"`
5. else **fallback**: read `<DATA_DIR>/history.csv` yourself (`;`-delimited, RFC
   4180 quoting). Do NOT hand-write an ad-hoc parser in `node -e`/`python -c` —
   prefer the script.

It prints a JSON array of `{ "row": N, ...all 13 fields }` to stdout — read that
output directly. If you redirect it to a scratch file, delete that file when done
(do not leave a `_dump.json` in `<DATA_DIR>`). Over those records, find the
tickets most comparable to the target:
1. **Narrow** first by `issue_type` and overlapping `components`/`labels`
   (cheap filter; keeps large histories manageable).
2. **Compare** the target's `summary`/`description`/`comments` to the narrowed
   candidates semantically to rank similarity. Pull in parent context where
   useful (`parent_key`).
3. **Weight by `estimate_basis`**: trust `actual` rows most (real outcomes),
   `final` rows next (team-agreed), and discount `suggested` rows and blank-basis
   legacy rows (avoid letting prior guesses drive the estimate).
4. **Determine the point scale.** If `estimation_prefs.point_scale` is set, snap
   the suggestion to the nearest value in that list (use
   `estimation_prefs.point_scale_note` to interpret a custom scale). If it is
   `null`, infer the scale from the `story_points` distribution (e.g. Fibonacci
   1/2/3/5/8/13) and snap to it.
5. **Apply the limits last.** Produce the **nearest in-scale value that also
   respects `[min_story_points, max_story_points]`**: both set → clamp into the
   range (raw 21, max 13 → 13; raw 0.5, min 1 → 1); only `min` → floor; only
   `max` → ceiling; neither → no cap. If a configured scale and a bound disagree,
   the scale governs the snap and the bound only narrows it.

Present a **rich** result:
- the **suggested estimate** (in the team's scale),
- a short **rationale**,
- the **top comparable tickets** (key, story points, `estimate_basis`, and why
  similar),
- a **confidence** level / range, lowered when evidence is thin or mostly
  `suggested`/blank-basis.

When a configured scale or limit changed the raw result, say so in the rationale
(e.g. "analysis pointed to ~21; capped to your max of 13").

Format the output as **plain text** — no HTML entities (`&nbsp;`, etc.) or markup;
it renders in a terminal.

## Step 5 — Prompt for the team's final estimate

Ask: **"What did the team settle on? (enter a value, or press Enter to record
the suggested estimate of X)."**
- If the user gives a value → record `story_points` = that value,
  `estimate_basis` = `final`.
- If the user skips/accepts → record `story_points` = the suggested value,
  `estimate_basis` = `suggested`.

## Step 6 — Override check

Check whether the ticket's key already exists in `history.csv` (match a line
starting `KEY;`). If it does, show the stored `story_points` and
`estimate_basis`, and ask the user to confirm overwriting it. If the user
declines, stop without writing.

## Step 7 — Write the record

Write a single-record JSON array to `<DATA_DIR>/_records.tmp.json` with all
fields for the target ticket: `key, parent_key, issue_type, summary,
description, components` (array), `labels` (array), `story_points` = the chosen
value, `time_spent_seconds` = "" , `resolution_date` = "" , `comments` (array),
`design_link`, `estimate_basis` = `final` or `suggested`.

Then append it using the same runtime-detection ladder as `sync`
(`mode = append`, which dedups by key — new row wins, so a confirmed override
just replaces the old row):

1. `python3 "<PLUGIN_ROOT>/scripts/build_csv.py" "<DATA_DIR>/_records.tmp.json" "<DATA_DIR>/history.csv" append`
2. else `python "<PLUGIN_ROOT>/scripts/build_csv.py" "<DATA_DIR>/_records.tmp.json" "<DATA_DIR>/history.csv" append`
3. else `py -3 "<PLUGIN_ROOT>/scripts/build_csv.py" "<DATA_DIR>/_records.tmp.json" "<DATA_DIR>/history.csv" append`
4. else `node "<PLUGIN_ROOT>/scripts/build_csv.mjs" "<DATA_DIR>/_records.tmp.json" "<DATA_DIR>/history.csv" append`
5. else **fallback**: append the row yourself with the Write tool, applying the
   exact CSV rules in `scripts/build_csv.py` — `;` delimiter,
   multi-value cells joined with `, `, comments joined with `\n\n`, RFC 4180
   quoting (wrap any cell containing `;`, `"`, a newline, or a carriage return in
   double quotes and double internal `"`), 13 columns in header order. Read and
   merge existing rows, dedup by key (new wins), and pad any legacy 12-column
   rows to 13 (blank `estimate_basis`).

**Resolving `<PLUGIN_ROOT>`:** `$CLAUDE_PLUGIN_ROOT` is usually empty inside a
skill's shell, so don't rely on it. `<PLUGIN_ROOT>` is the directory **two levels
above this skill's announced base directory** (the base dir shown when this skill
loaded is `…/skills/<name>`, so its parent's parent is the plugin root).
Substitute that absolute path for `<PLUGIN_ROOT>` in the commands above.

Delete `_records.tmp.json` when done. Update `config.json` `row_count` to the
value `build_csv` prints as `{"row_count":N}`, preserving every other key. Then
report: the ticket key, the recorded story points, the `estimate_basis`, and the
absolute `history.csv` path.

## Error handling

- No `history.csv` → guide the user to run `/sync`; do not fabricate a baseline.
- Atlassian MCP not connected → guide to connect; stop.
- Ticket not found / invalid reference → report or re-prompt.
- Write failure (no runtime + Write fallback also fails) → report the error;
  never claim the record was saved when it was not.
- Never silently overwrite an existing row — always confirm (Step 6).
