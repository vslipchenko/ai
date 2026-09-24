import test from "node:test";
import assert from "node:assert/strict";
import { homedir } from "node:os";
import {
  weekday,
  earliest,
  matchRule,
  labelFor,
  expand,
  group,
  truncate,
  csvCell,
  renderCsv,
  renderTerminal,
  resolveColumns,
  parseArgs,
  ALL_COLUMNS,
  dedupeEvents,
  expandUser,
} from "../build_report.mjs";

const noop = () => {};
const collect = () => {
  const seen = [];
  const fn = (m) => seen.push(m);
  fn.seen = seen;
  return fn;
};

const commit = (over = {}) => ({
  date: "2026-09-22",
  time: "09:14",
  source: "local-git",
  type: "commit",
  repo: "web",
  ticket_ids: ["ABC-1"],
  subject: "ABC-1 add login",
  url: "",
  ...over,
});

const RULES = [
  { label: "Code Review", when: { type: ["pr_review", "pr_comment"] } },
  { label: "Bug Fixing", when: { type: "commit", subject_matches: "^(fix|hotfix)\\b" } },
  { label: "Coding", when: { type: "commit" } },
];

test("a leading ~ expands to the home directory", () => {
  // Matters for paths that never pass through a shell: output.csv_path in the
  // config file, and repo paths typed into setup.
  assert.equal(expandUser("~"), homedir());
  const expanded = expandUser("~/reports/sept.csv");
  assert.ok(expanded.startsWith(homedir()), "expanded under home");
  assert.ok(!expanded.includes("~"), "no tilde survives");
  assert.ok(expanded.endsWith("sept.csv"));
});

test("~otheruser is left alone, so both script twins agree", () => {
  // Python's expanduser would resolve this; Node cannot, so neither does.
  assert.equal(expandUser("~someone/x"), "~someone/x");
});

test("ordinary paths and empty values pass through untouched", () => {
  assert.equal(expandUser("reports/sept.csv"), "reports/sept.csv");
  assert.equal(expandUser("/abs/path.csv"), "/abs/path.csv");
  assert.equal(expandUser("a~b.csv"), "a~b.csv", "a tilde mid-path is not a home marker");
  assert.equal(expandUser(""), "");
  assert.equal(expandUser(null), null);
});

test("weekday names every day of one known week", () => {
  // 2026-09-21 is a Monday.
  const week = ["2026-09-21", "2026-09-22", "2026-09-23", "2026-09-24", "2026-09-25", "2026-09-26", "2026-09-27"];
  assert.deepEqual(week.map(weekday), ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]);
});

test("weekday is unaffected by the machine timezone", () => {
  // A UTC-based calculation keeps the date from sliding a day either way.
  assert.equal(weekday("2026-01-01"), "Thu");
  assert.equal(weekday("2026-12-31"), "Thu");
});

test("weekday returns empty for a non-date rather than a wrong day", () => {
  assert.equal(weekday(""), "");
  assert.equal(weekday("(no ticket)"), "");
  assert.equal(weekday(null), "");
  assert.equal(weekday("2026-02-31"), "", "a rolled-over date is not a date");
});

test("group attaches the day name to every row", () => {
  const rows = group(expand([commit()], { activity_rules: RULES }, noop), false, {}, "-");
  assert.equal(rows[0].day, "Tue");
});

test("earliest ignores unknown (empty) times instead of treating them as midnight", () => {
  assert.equal(earliest("", "09:14"), "09:14");
  assert.equal(earliest("11:00", "09:14"), "09:14");
  assert.equal(earliest("", ""), "");
});

test("a condition matches any value in its list", () => {
  assert.equal(matchRule(commit({ type: "pr_review" }), { type: ["pr_review", "pr_comment"] }, noop), true);
});

test("conditions AND together", () => {
  const when = { type: "commit", repo: "api" };
  assert.equal(matchRule(commit(), when, noop), false);
  assert.equal(matchRule(commit({ repo: "api" }), when, noop), true);
});

test("subject_matches is a case-insensitive regex", () => {
  assert.equal(matchRule(commit({ subject: "FIX login" }), { subject_matches: "^fix" }, noop), true);
});

test("a condition on a list field matches if any element matches", () => {
  assert.equal(matchRule(commit({ ticket_ids: ["ABC-1", "OPS-9"] }), { ticket_ids: "ops-9" }, noop), true);
});

test("an unrecognized condition warns instead of silently matching everything", () => {
  const warn = collect();
  assert.equal(matchRule(commit(), { titel: "x" }, warn), false);
  assert.match(warn.seen[0], /not a recognized field/);
});

test("first matching rule wins, so Bug Fixing must precede the generic commit rule", () => {
  assert.equal(labelFor(commit({ subject: "fix login loop" }), RULES, "Other", noop), "Bug Fixing");
  assert.equal(labelFor(commit(), RULES, "Other", noop), "Coding");
});

test("an explicit activity on the event beats every rule", () => {
  assert.equal(labelFor(commit({ activity: "Investigation" }), RULES, "Other", noop), "Investigation");
});

test("an event matching no rule falls back to the default activity", () => {
  assert.equal(labelFor(commit({ type: "deploy" }), RULES, "Other", noop), "Other");
});

const DROP_RULES = [
  { drop: true, when: { type: ["jira_assigned", "jira_worklog"] } },
  { drop: true, when: { type: "jira_transition", status_to: ["Done", "Closed"] } },
  { label: "Coding", when: { type: ["commit", "jira_transition"] } },
];

test("a drop rule suppresses the event instead of labelling it", () => {
  assert.equal(labelFor(commit({ type: "jira_assigned" }), DROP_RULES, "Other", noop), null);
});

test("drop is decided by first match, like any other rule", () => {
  // -> Done is dropped; -> In Progress falls through to the Coding rule.
  const done = commit({ type: "jira_transition", status_to: "Done" });
  const wip = commit({ type: "jira_transition", status_to: "In Progress" });
  assert.equal(labelFor(done, DROP_RULES, "Other", noop), null);
  assert.equal(labelFor(wip, DROP_RULES, "Other", noop), "Coding");
});

test("an explicit activity beats a drop rule, since pinning is deliberate", () => {
  const event = commit({ type: "jira_assigned", activity: "Planning" });
  assert.equal(labelFor(event, DROP_RULES, "Other", noop), "Planning");
});

test("dropped events produce no rows at all", () => {
  const events = [
    commit({ type: "jira_assigned" }),
    commit({ type: "jira_worklog" }),
    commit(),
  ];
  const rows = expand(events, { activity_rules: DROP_RULES }, noop);
  assert.equal(rows.length, 1);
  assert.equal(rows[0].activity, "Coding");
});

test("a day of nothing but bookkeeping yields an empty report, not Other rows", () => {
  const events = [commit({ type: "jira_assigned" }), commit({ type: "jira_worklog" })];
  const rows = group(expand(events, { activity_rules: DROP_RULES }, noop), false, {}, "-");
  assert.deepEqual(rows, []);
});

// The two rule sets setup generates, differing only in how QA statuses are
// handled. Ordering is what makes them work, so both are pinned here.
const NO_QA_TEAM = [
  { drop: true, when: { type: "jira_transition", status_to: ["Done", "Closed"] } },
  { label: "Testing", when: { type: "jira_transition", status_to: ["In Testing", "QA"] } },
  { label: "Coding", when: { type: ["commit", "jira_transition"] } },
];
const DEDICATED_QA_TEAM = [
  { drop: true, when: { type: "jira_transition", status_to: ["Done", "Closed"] } },
  { drop: true, when: { type: "jira_transition", status_to: ["In Testing", "QA"] } },
  { label: "Coding", when: { type: ["commit", "jira_transition"] } },
];
const toQa = () => commit({ type: "jira_transition", status_to: "In Testing" });

test("without dedicated QA, a move to QA is the developer's own testing", () => {
  assert.equal(labelFor(toQa(), NO_QA_TEAM, "Other", noop), "Testing");
});

test("with dedicated QA, a move to QA is a handoff and is dropped", () => {
  assert.equal(labelFor(toQa(), DEDICATED_QA_TEAM, "Other", noop), null);
});

test("deleting the Testing rule instead of converting it mislabels the handoff", () => {
  // Guards the one silent failure of the dedicated-QA setup path: with the
  // rule merely removed, QA statuses fall through to the Coding catch-all.
  const deletedNotConverted = NO_QA_TEAM.filter((r) => r.label !== "Testing");
  assert.equal(labelFor(toQa(), deletedNotConverted, "Other", noop), "Coding");
  assert.equal(labelFor(toQa(), DEDICATED_QA_TEAM, "Other", noop), null);
});

test("either QA setup still labels ordinary working transitions as Coding", () => {
  const wip = commit({ type: "jira_transition", status_to: "In Progress" });
  assert.equal(labelFor(wip, NO_QA_TEAM, "Other", noop), "Coding");
  assert.equal(labelFor(wip, DEDICATED_QA_TEAM, "Other", noop), "Coding");
});

test("a rule with neither label nor drop warns rather than silently defaulting", () => {
  const warn = collect();
  assert.equal(labelFor(commit(), [{ when: { type: "commit" } }], "Other", warn), "Other");
  assert.match(warn.seen[0], /neither a label nor drop/);
});

test("an event with no date is dropped and reported, not rendered blank", () => {
  const warn = collect();
  const rows = expand(
    [commit({ date: undefined }), commit({ date: "" }), commit()],
    { activity_rules: RULES },
    warn
  );
  assert.equal(rows.length, 1);
  assert.match(warn.seen[0], /dropped 2 event\(s\) with a missing or malformed date/);
});

test("a malformed date is dropped too, since dates sort as strings", () => {
  // "22/09/2026" would sort before every ISO date and silently reorder the report.
  const warn = collect();
  const rows = expand([commit({ date: "22/09/2026" }), commit()], { activity_rules: RULES }, warn);
  assert.equal(rows.length, 1);
  assert.equal(rows[0].date, "2026-09-22");
  assert.match(warn.seen[0], /malformed date/);
});

test("a date that looks real but is not gets dropped", () => {
  const warn = collect();
  assert.equal(expand([commit({ date: "2026-02-31" })], { activity_rules: RULES }, warn).length, 0);
});

test("valid dates produce no warning at all", () => {
  const warn = collect();
  expand([commit(), commit({ date: "2026-12-31" })], { activity_rules: RULES }, warn);
  assert.deepEqual(warn.seen, []);
});

test("an event touching two tickets becomes two rows", () => {
  const rows = expand([commit({ ticket_ids: ["ABC-1", "ABC-2"] })], { activity_rules: RULES }, noop);
  assert.deepEqual(rows.map((r) => r.id), ["ABC-1", "ABC-2"]);
});

test("untracked=include keeps ticketless work under a placeholder", () => {
  const rows = expand([commit({ ticket_ids: [] })], { activity_rules: RULES }, noop);
  assert.equal(rows[0].id, "(no ticket)");
});

test("untracked=omit drops ticketless work entirely", () => {
  const config = { activity_rules: RULES, output: { untracked: "omit" } };
  assert.equal(expand([commit({ ticket_ids: [] })], config, noop).length, 0);
});

test("untracked=group collapses stray commits to one line per date and activity", () => {
  const config = { activity_rules: RULES, output: { untracked: "group" } };
  const events = [
    commit({ ticket_ids: [], time: "11:00" }),
    commit({ ticket_ids: [], time: "09:14" }),
    commit({ ticket_ids: [], date: "2026-09-23" }),
  ];
  const rows = expand(events, config, noop);
  assert.equal(rows.length, 2);
  assert.equal(rows.find((r) => r.date === "2026-09-22").time, "09:14");
});

test("an invalid untracked mode warns and falls back to include", () => {
  const warn = collect();
  const rows = expand([commit({ ticket_ids: [] })], { output: { untracked: "maybe" } }, warn);
  assert.equal(rows.length, 1);
  assert.match(warn.seen[0], /include\/omit\/group/);
});

test("without include_time a day's commits on one ticket collapse to one line", () => {
  const rows = group(
    expand([commit({ time: "09:14" }), commit({ time: "16:02" })], { activity_rules: RULES }, noop),
    false,
    { "ABC-1": "Add login" },
    "(title unavailable)"
  );
  assert.equal(rows.length, 1);
  assert.equal(rows[0].evidence, 2);
  assert.equal(rows[0].time, "09:14", "the collapsed line keeps the earliest time");
});

test("with include_time each timestamped event stays its own line", () => {
  const rows = group(
    expand([commit({ time: "09:14" }), commit({ time: "16:02" })], { activity_rules: RULES }, noop),
    true,
    {},
    "(title unavailable)"
  );
  assert.equal(rows.length, 2);
});

test("different activities on one ticket stay separate lines", () => {
  const events = [commit(), commit({ type: "pr_review", subject: "review ABC-1" })];
  const rows = group(expand(events, { activity_rules: RULES }, noop), false, {}, "-");
  assert.deepEqual(rows.map((r) => r.activity), ["Code Review", "Coding"]);
});

test("a missing title gets the placeholder rather than an empty cell", () => {
  const rows = group(expand([commit()], { activity_rules: RULES }, noop), false, {}, "(title unavailable)");
  assert.equal(rows[0].title, "(title unavailable)");
});

test("a ticketless row falls back to the commit subject, not the placeholder", () => {
  const rows = group(
    expand([commit({ ticket_ids: [], subject: "chore: bump deps" })], { activity_rules: RULES }, noop),
    false,
    {},
    "(title unavailable)"
  );
  assert.equal(rows[0].id, "(no ticket)");
  assert.equal(rows[0].title, "chore: bump deps");
});

test("a known title still beats the subject fallback", () => {
  const rows = group(
    expand([commit()], { activity_rules: RULES }, noop),
    false,
    { "ABC-1": "Add login" },
    "(title unavailable)"
  );
  assert.equal(rows[0].title, "Add login");
});

const page = (over = {}) => ({
  date: "2026-09-22",
  time: "13:20",
  source: "confluence",
  type: "confluence_updated",
  item_type: "confluence",
  ticket_ids: ["393217"],
  subject: "RFC: auth redesign",
  url: "https://acme.atlassian.net/wiki/spaces/ENG/pages/393217",
  ...over,
});

test("events default to the jira item type, so existing sources are unaffected", () => {
  const rows = expand([commit()], { activity_rules: RULES }, noop);
  assert.equal(rows[0].item_type, "Jira");
});

test("a commit is item_type Jira because its id is a Jira key", () => {
  // The Type column describes what the Id refers to, not where the evidence
  // came from -- `source` carries that.
  const rows = group(expand([commit()], { activity_rules: RULES }, noop), false, {}, "-");
  assert.equal(rows[0].item_type, "Jira");
  assert.equal(rows[0].source, "local-git");
});

test("a confluence event carries the Confluence item type and its page id", () => {
  const rows = group(
    expand([page()], { activity_rules: [{ label: "Documentation", when: {} }] }, noop),
    false,
    { 393217: "RFC: auth redesign" },
    "-"
  );
  assert.equal(rows[0].item_type, "Confluence");
  assert.equal(rows[0].id, "393217");
  assert.equal(rows[0].title, "RFC: auth redesign");
  assert.equal(rows[0].url, "https://acme.atlassian.net/wiki/spaces/ENG/pages/393217");
});

test("an untracked row has no item type, since there is no item behind it", () => {
  const rows = expand([commit({ ticket_ids: [] })], { activity_rules: RULES }, noop);
  assert.equal(rows[0].item_type, "");
});

test("an unknown item type is capitalized rather than dropped", () => {
  const rows = expand([commit({ item_type: "linear" })], { activity_rules: RULES }, noop);
  assert.equal(rows[0].item_type, "Linear");
});

test("Jira rows sort before Confluence rows within a day", () => {
  // Without a type rank, numeric page ids sort before ABC-123 keys purely
  // because digits precede letters.
  const events = [page(), commit()];
  const rows = group(
    expand(events, { activity_rules: [{ label: "Doc", when: {} }] }, noop),
    false,
    {},
    "-"
  );
  assert.deepEqual(rows.map((r) => `${r.item_type} ${r.id}`), ["Jira ABC-1", "Confluence 393217"]);
});

test("a Jira key and a page id that look alike never merge into one row", () => {
  const events = [commit({ ticket_ids: ["123"] }), page({ ticket_ids: ["123"] })];
  const rows = group(expand(events, { activity_rules: [{ label: "X", when: {} }] }, noop), false, {}, "-");
  assert.equal(rows.length, 2, "item_type is part of the grouping key");
});

test("the same commit from two sources is counted once", () => {
  const fromGit = commit({ ref: "9f3c1ab", source: "local-git" });
  const fromHost = commit({ ref: "9f3c1ab", source: "github" });
  const rows = group(
    expand(dedupeEvents([fromHost, fromGit]), { activity_rules: RULES }, noop),
    false,
    {},
    "-"
  );
  assert.equal(rows.length, 1);
  assert.equal(rows[0].evidence, 1, "evidence must not double-count");
  assert.equal(rows[0].source, "local-git", "the local copy wins, whatever the order");
});

test("dedup keeps genuinely different work on the same ticket", () => {
  const events = [
    commit({ ref: "9f3c1ab" }),
    commit({ ref: "aaa1111" }),
    commit({ ref: "9f3c1ab", type: "pr_review", source: "github" }),
  ];
  // Two distinct commits, plus a review that happens to reference the same sha.
  assert.equal(dedupeEvents(events).length, 3);
});

test("dedup leaves events without a ref alone", () => {
  const events = [
    commit({ ref: "", source: "jira", type: "jira_comment" }),
    commit({ ref: "", source: "jira", type: "jira_comment" }),
  ];
  assert.equal(dedupeEvents(events).length, 2);
});

test("ticket_type comes through onto the row, and is empty when absent", () => {
  const withType = expand([commit({ ticket_type: "Bug" })], { activity_rules: RULES }, noop);
  const without = expand([commit()], { activity_rules: RULES }, noop);
  assert.equal(withType[0].ticket_type, "Bug");
  assert.equal(without[0].ticket_type, "");
});

test("a merged row takes the issue type from whichever event knew it", () => {
  // Only board events carry an issue type; commits on the same ticket do not.
  const events = [
    commit({ subject: "ABC-1 fix it" }),
    commit({ type: "jira_transition", source: "jira", ticket_type: "Bug" }),
  ];
  const rows = group(
    expand(events, { activity_rules: [{ label: "Coding", when: {} }] }, noop),
    false,
    {},
    "-"
  );
  assert.equal(rows.length, 1, "the untyped commit must not split the ticket-day");
  assert.equal(rows[0].ticket_type, "Bug");
  assert.equal(rows[0].evidence, 2);
});

test("issue type is not part of the grouping key", () => {
  // Same ticket, same day, same activity: one row regardless of which events
  // happened to carry a type.
  const events = [commit(), commit({ ticket_type: "Story" }), commit({ ticket_type: "" })];
  const rows = group(
    expand(events, { activity_rules: [{ label: "Coding", when: {} }] }, noop),
    false,
    {},
    "-"
  );
  assert.equal(rows.length, 1);
  assert.equal(rows[0].ticket_type, "Story");
});

test("Confluence rows carry Page as their type", () => {
  const rows = group(
    expand([page({ ticket_type: "Page" })], { activity_rules: [{ label: "Doc", when: {} }] }, noop),
    false,
    {},
    "-"
  );
  assert.equal(rows[0].item_type, "Confluence");
  assert.equal(rows[0].ticket_type, "Page");
});

test("merged rows list every contributing source and repo", () => {
  const events = [commit(), commit({ source: "github", repo: "api", type: "pr_review" })];
  const rows = group(expand(events, { activity_rules: [{ label: "Coding", when: {} }] }, noop), false, {}, "-");
  assert.equal(rows[0].source, "local-git, github");
  assert.equal(rows[0].repo, "web, api");
});

test("rows sort by date then ticket", () => {
  const events = [
    commit({ date: "2026-09-23", ticket_ids: ["ABC-9"] }),
    commit({ date: "2026-09-22", ticket_ids: ["ABC-4"] }),
    commit({ date: "2026-09-22", ticket_ids: ["ABC-2"] }),
  ];
  const rows = group(expand(events, { activity_rules: RULES }, noop), false, {}, "-");
  assert.deepEqual(rows.map((r) => `${r.date} ${r.id}`), [
    "2026-09-22 ABC-2",
    "2026-09-22 ABC-4",
    "2026-09-23 ABC-9",
  ]);
});

test("csv quotes commas, quotes and newlines per RFC 4180", () => {
  assert.equal(csvCell("plain"), "plain");
  assert.equal(csvCell("a,b"), '"a,b"');
  assert.equal(csvCell('say "hi"'), '"say ""hi"""');
  assert.equal(csvCell("two\nlines"), '"two\nlines"');
});

test("a ticket title containing a comma survives a csv round-trip", () => {
  const rows = [{ date: "2026-09-22", id: "ABC-1", title: "Fix login, again", activity: "Coding" }];
  const csv = renderCsv(rows, ["date", "id", "title", "activity"]);
  assert.equal(csv.split("\n")[0], "Date,Id,Title,Activity");
  assert.equal(csv.split("\n")[1], '2026-09-22,ABC-1,"Fix login, again",Coding');
});

test("titles truncate with an ASCII ellipsis, not a Unicode one", () => {
  assert.equal(truncate("abcdefghij", 8), "abcde...");
  assert.equal(truncate("short", 60), "short");
  assert.equal(truncate("abcdef", 0), "abcdef", "width 0 means no truncation");
});

const TWO_DAYS = [
  { date: "2026-09-22", id: "ABC-1", title: "Add login", activity: "Coding" },
  { date: "2026-09-23", id: "ABC-2", title: "Review", activity: "Code Review" },
];

test("grid draws a boxed table per day, closed top and bottom", () => {
  const lines = renderTerminal([TWO_DAYS[0]], LAYOUT(), 60, null, false, true, true, "grid")
    .trimEnd()
    .split("\n");
  assert.deepEqual(lines, [
    "2026-09-22 (Tue)",
    "+-------+-----------+----------+",
    "| Id    | Title     | Activity |",
    "+-------+-----------+----------+",
    "| ABC-1 | Add login | Coding   |",
    "+-------+-----------+----------+",
  ]);
});

test("grid repeats the header under every date group", () => {
  const text = renderTerminal(TWO_DAYS, LAYOUT(), 60, null, false, true, true, "grid");
  assert.equal(text.split("| Id").length - 1, 2);
  assert.match(text, /2026-09-22 \(Tue\)/);
  assert.match(text, /2026-09-23 \(Wed\)/);
});

test("grid column widths are shared across days so the boxes line up", () => {
  const rows = [
    { date: "2026-09-22", id: "ABC-1", title: "short", activity: "Coding" },
    { date: "2026-09-23", id: "ABC-2", title: "a much longer title here", activity: "Coding" },
  ];
  const borders = renderTerminal(rows, LAYOUT(), 60, null, false, true, true, "grid")
    .split("\n")
    .filter((l) => l.startsWith("+"));
  assert.equal(new Set(borders).size, 1, "every border line is identical");
});

test("grid without a header still boxes the rows", () => {
  const lines = renderTerminal([TWO_DAYS[0]], LAYOUT(), 60, null, false, true, false, "grid")
    .trimEnd()
    .split("\n");
  assert.deepEqual(lines, [
    "2026-09-22 (Tue)",
    "+-------+-----------+----------+",
    "| ABC-1 | Add login | Coding   |",
    "+-------+-----------+----------+",
  ]);
});

test("plain output groups by date and does not repeat it per line", () => {
  const text = renderTerminal(TWO_DAYS, LAYOUT(), 60, null, false, false, false, "plain");
  const lines = text.trimEnd().split("\n");
  assert.equal(lines[0], "2026-09-22");
  // Columns pad to the widest of header and values ("Id" is 2 wide, so ABC-1 sets the width), and
  // trailing padding is trimmed off the end of each line.
  assert.equal(lines[1], "  ABC-1  Add login  Coding");
  assert.equal(lines[2], "");
  assert.equal(lines[3], "2026-09-23");
  assert.equal(lines[4], "  ABC-2  Review     Code Review");
});

test("the date heading carries the day name", () => {
  const lines = renderTerminal([TWO_DAYS[0]], LAYOUT(), 60, null, false, true, false, "plain")
    .trimEnd()
    .split("\n");
  assert.equal(lines[0], "2026-09-22 (Tue)");
});

test("the day name can be turned off", () => {
  const lines = renderTerminal([TWO_DAYS[0]], LAYOUT(), 60, null, false, false, false, "plain")
    .trimEnd()
    .split("\n");
  assert.equal(lines[0], "2026-09-22");
});

test("plain puts one header row with a rule above the first date group", () => {
  const lines = renderTerminal([TWO_DAYS[0]], LAYOUT(), 60, null, false, true, true, "plain")
    .trimEnd()
    .split("\n");
  assert.equal(lines[0], "  Id     Title      Activity");
  assert.equal(lines[1], "  -----  ---------  --------");
  assert.equal(lines[2], "");
  assert.equal(lines[3], "2026-09-22 (Tue)");
  assert.equal(lines[4], "  ABC-1  Add login  Coding");
});

test("plain prints the header once, not above every date group", () => {
  const text = renderTerminal(TWO_DAYS, LAYOUT(), 60, null, false, true, true, "plain");
  assert.equal(text.split("Id ").length - 1, 1);
});

test("date and day are never repeated as line columns in terminal output", () => {
  const rows = [{ date: "2026-09-22", day: "Tue", id: "ABC-1", title: "a", activity: "Coding" }];
  for (const style of ["grid", "plain"]) {
    const text = renderTerminal(rows, LAYOUT(), 60, null, false, true, true, style);
    assert.equal(text.split("2026-09-22").length - 1, 1, `${style}: date appears once`);
    assert.equal(text.split("Tue").length - 1, 1, `${style}: day appears once`);
  }
});

test("asking for only heading columns degrades to bare date headings", () => {
  const rows = [
    { date: "2026-09-22", id: "ABC-1", title: "a", activity: "Coding" },
    { date: "2026-09-23", id: "ABC-2", title: "b", activity: "Coding" },
  ];
  const text = renderTerminal(rows, ["date", "day"], 60, null, false, true, true, "grid");
  assert.equal(text, "2026-09-22 (Tue)\n2026-09-23 (Wed)\n");
});

test("an empty report says so instead of printing a bare header", () => {
  assert.equal(renderTerminal([], LAYOUT(), 60, "2026-09-01 to 2026-09-07", true),
    "No activity found for 2026-09-01 to 2026-09-07.\n");
});
function DEFAULTS() {
  return ["date", "day", "item_type", "id", "title", "activity"];
}

// Layout tests drop the Type column so the expected boxes stay readable; the
// Type column has its own tests below.
function LAYOUT() {
  return ["date", "day", "id", "title", "activity"];
}

test("the summary tallies lines per activity", () => {
  const rows = [
    { date: "2026-09-22", id: "ABC-1", title: "a", activity: "Coding" },
    { date: "2026-09-22", id: "ABC-2", title: "b", activity: "Coding" },
    { date: "2026-09-22", id: "ABC-3", title: "c", activity: "Code Review" },
  ];
  const text = renderTerminal(rows, LAYOUT(), 60, null, true);
  assert.match(text, /Coding {15}2 entries/);
  assert.match(text, /Code Review {10}1 entry/);
  assert.match(text, /total lines {10}3/);
});

test("include_time injects the time column after date and day", () => {
  assert.deepEqual(resolveColumns(null, true, noop), [
    "date", "day", "time", "item_type", "id", "title", "activity",
  ]);
});

test("include_time slots time first when there is no leading date column", () => {
  assert.deepEqual(resolveColumns(["id", "activity"], true, noop), [
    "time", "id", "activity",
  ]);
});

test("no include_time strips a time column even if configured", () => {
  assert.deepEqual(resolveColumns(["date", "time", "activity"], false, noop), ["date", "activity"]);
});

test("an unknown column warns and is dropped rather than rendering blank", () => {
  const warn = collect();
  assert.deepEqual(resolveColumns(["date", "tickt_id"], false, warn), ["date"]);
  assert.match(warn.seen[0], /unknown column/);
});

test("the old ticket_id column name still resolves to id", () => {
  assert.deepEqual(resolveColumns(["date", "ticket_id", "activity"], false, noop), [
    "date", "id", "activity",
  ]);
});

test("type means the issue type; system means the Jira/Confluence column", () => {
  assert.deepEqual(resolveColumns(["type", "system", "id"], false, noop), [
    "ticket_type", "item_type", "id",
  ]);
  assert.deepEqual(resolveColumns(["issue_type"], false, noop), ["ticket_type"]);
});

test("the System, Type and Id headers render with those names", () => {
  const rows = [
    {
      date: "2026-09-22",
      item_type: "Confluence",
      ticket_type: "Page",
      id: "393217",
      title: "RFC",
      activity: "Documentation",
    },
  ];
  const columns = ["date", "day", "item_type", "ticket_type", "id", "title", "activity"];
  const text = renderTerminal(rows, columns, 60, null, false, false, true, "grid");
  assert.match(text, /\| System {5}\| Type \| Id {5}\| Title \| Activity {6}\|/);
  assert.match(text, /\| Confluence \| Page \| 393217 \| RFC {3}\| Documentation \|/);
});

test("the issue-type column is opt-in, not in the defaults", () => {
  assert.ok(!DEFAULTS().includes("ticket_type"));
  assert.ok(ALL_COLUMNS.includes("ticket_type"));
});

test("dropping every column falls back to the defaults", () => {
  assert.deepEqual(resolveColumns(["nope"], false, noop), DEFAULTS());
});

test("parseArgs keeps include_time tri-state so config can win", () => {
  assert.equal(parseArgs(["--events", "e.json"]).includeTime, null);
  assert.equal(parseArgs(["--events", "e.json", "--include-time"]).includeTime, true);
  assert.equal(parseArgs(["--events", "e.json", "--no-include-time"]).includeTime, false);
});

test("parseArgs keeps weekday and header tri-state so config can win", () => {
  assert.equal(parseArgs(["--events", "e.json"]).weekday, null);
  assert.equal(parseArgs(["--events", "e.json"]).header, null);
  assert.equal(parseArgs(["--events", "e.json", "--no-weekday"]).weekday, false);
  assert.equal(parseArgs(["--events", "e.json", "--no-header"]).header, false);
});

test("parseArgs rejects an unknown output format", () => {
  assert.throws(() => parseArgs(["--events", "e.json", "--format", "pdf"]), /terminal or csv/);
});

test("parseArgs rejects an unknown table style", () => {
  assert.throws(() => parseArgs(["--events", "e.json", "--table-style", "ascii"]), /grid or plain/);
  assert.equal(parseArgs(["--events", "e.json", "--table-style", "plain"]).tableStyle, "plain");
  assert.equal(parseArgs(["--events", "e.json"]).tableStyle, null);
});
