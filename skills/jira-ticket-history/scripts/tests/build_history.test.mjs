import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import {
  repairMojibake,
  textDiff,
  wordDiff,
  adfToWiki,
  toWiki,
  classify,
  toChange,
  buildModel,
  renderPage,
  toJson,
  toEpochMs,
  renderTs,
  htmlToText,
  firstLine,
  parseArgs,
  TYPES,
} from "../build_history.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const fixture = () => JSON.parse(readFileSync(path.join(here, "fixtures", "bundle.json"), "utf8"));
const config = () => JSON.parse(readFileSync(path.join(here, "fixtures", "config.json"), "utf8"));
const template = readFileSync(path.join(here, "..", "..", "assets", "template.html"), "utf8");
const model = (over = {}) => {
  const cfg = config();
  return buildModel(fixture(), {
    tz: "utc",
    automationAccounts: cfg.automation_accounts,
    excludeFields: cfg.history.exclude_fields,
    ...over,
  });
};
const byId = (m, id) => m.commits.find((c) => c.id === id);

// ------------------------------------------------------------- mojibake --
test("repairs UTF-8 read as Windows-1252", () => {
  const r = repairMojibake("a â€” b â€œqâ€\u009d cafÃ©");
  assert.equal(r.text, "a — b “q” café");
  assert.deepEqual(r.fixed.map((x) => x[1]), ["—", "“", "”", "é"]);
});

test("leaves genuine accented text alone", () => {
  for (const s of ["naïve Â façade", "Ångström", "€5 → 10×", "🎯 done", "Zürich — ok"]) {
    assert.equal(repairMojibake(s).text, s, s);
  }
});

// ----------------------------------------------------------------- diff --
test("escape-only and blank-line-only edits are markup only", () => {
  const d = textDiff("h2. Goal\nText a-b.", "h2. Goal\n\nText a\\-b\\.");
  assert.equal(d.markup_only, true);
  assert.equal(d.add, 0);
  assert.equal(d.del, 0);
  assert.deepEqual(d.hunks, []);
});

test("line diff pairs changed lines with word highlights and collapses context", () => {
  const a = ["one", "two", "three", "four", "five", "six"].join("\n");
  const b = ["one", "two", "three", "4", "five", "six"].join("\n");
  const d = textDiff(a, b);
  assert.equal(d.add, 1);
  assert.equal(d.del, 1);
  assert.deepEqual(d.hunks.map((h) => h.k), ["~", "=", "-", "+", "=", "~"]);
  assert.deepEqual(d.hunks[3].w, [["x", "4"]]);
  assert.equal(d.full.length, 6);
  assert.ok(d.full.every((l) => l.k !== "-"));
});

test("word diff marks only changed words", () => {
  const w = wordDiff("retry up to 3 times", "retry up to 5 times");
  assert.deepEqual(w.del, [["=", "retry up to "], ["x", "3"], ["=", " times"]]);
  assert.deepEqual(w.add, [["=", "retry up to "], ["x", "5"], ["=", " times"]]);
});

test("records which side carried broken characters", () => {
  const d = textDiff("x — y", "x â€” y");
  assert.equal(d.markup_only, true);
  assert.deepEqual(d.encoding, { before: [], after: ["â€” → —"] });
});

// ------------------------------------------------------------------ adf --
test("ADF converts to wiki markup", () => {
  const doc = { type: "doc", content: [
    { type: "heading", attrs: { level: 3 }, content: [{ type: "text", text: "Title" }] },
    { type: "paragraph", content: [{ type: "text", text: "bold", marks: [{ type: "strong" }] }, { type: "text", text: " and " },
      { type: "text", text: "link", marks: [{ type: "link", attrs: { href: "https://x.test" } }] }] },
    { type: "bulletList", content: [{ type: "listItem", content: [{ type: "paragraph", content: [{ type: "text", text: "a" }] },
      { type: "bulletList", content: [{ type: "listItem", content: [{ type: "paragraph", content: [{ type: "text", text: "b" }] }] }] }] }] },
  ] };
  assert.equal(adfToWiki(doc), "h3. Title\n\n*bold* and [link|https://x.test]\n\n* a\n\n** b");
});

test("ADF stored with wiki escapes still parses", () => {
  const raw = '{"type":"doc","content":\\[{"type":"paragraph","content":\\[{"type":"text","text":"a\\-b"}\\]}\\]}';
  assert.equal(toWiki(raw), "a-b");
});

// -------------------------------------------------------- classification --
test("each activity type comes from Jira's own field identity", () => {
  const cases = [
    [{ field: "status", fieldId: "status" }, "status"],
    [{ field: "assignee", fieldId: "assignee" }, "assignee"],
    [{ field: "description", fieldId: "description" }, "description"],
    [{ field: "summary", fieldId: "summary" }, "title"],
    [{ field: "Link" }, "links"],
    [{ field: "IssueParentAssociation" }, "links"],
    [{ field: "RemoteWorkItemLink" }, "weblinks"],
    [{ field: "Attachment" }, "attachments"],
    [{ field: "Comment", fieldId: "comment" }, "comments"],
    [{ field: "WorklogId" }, "worklogs"],
    [{ field: "timespent", fieldId: "timespent" }, "worklogs"],
    [{ field: "Story Points", fieldId: "customfield_10016" }, "fields"],
    [{ field: "Sprint", fieldId: "customfield_10020" }, "fields"],
  ];
  for (const [item, want] of cases) assert.equal(classify(item), want, JSON.stringify(item));
  assert.deepEqual([...new Set(cases.map((c) => c[1]))].sort(), [...TYPES].sort(), "every type is covered");
});

test("an item without toString is a removal, not a change", () => {
  const c = toChange({ field: "Comment", fieldId: "comment", fromString: "old text" });
  assert.equal(c.subject, "Delete comment");
  assert.equal(c.deleted, "old text");
});

test("labels, cascading selects and generic fields get readable subjects", () => {
  assert.equal(toChange({ field: "labels", fieldId: "labels", fromString: "a b", toString: "b c" }).subject, "Labels +c −a");
  assert.equal(toChange({ field: "Area", fieldId: "customfield_1", toString: "Parent values: A(1)Level 1 values: B(2)" }).to, "A / B");
  assert.equal(toChange({ field: "Team", fieldId: "customfield_2", fromString: "X", toString: "Y" }).subject, "Team: X → Y");
  assert.equal(toChange({ field: "Team", fieldId: "customfield_2", fromString: "X" }).subject, "Clear Team");
});

test("multi-line custom text fields are diffed like the description", () => {
  const c = toChange({ field: "Notes", fieldId: "customfield_3", fromString: "a", toString: "a\nb" });
  assert.equal(c.cat, "fields");
  assert.equal(c.subject, "Edit Notes (+1 −0)");
  assert.ok(c.diff);
});

// ---------------------------------------------------------------- model --
test("builds one commit per changelog entry, comment and worklog, plus creation", () => {
  const m = model();
  const b = fixture();
  assert.equal(m.commits.length, 1 + b.changelog.length - 1 + b.comments.length + b.worklogs.length); // Rank entry excluded
  assert.deepEqual(m.excluded_fields, ["Rank"]);
  assert.ok(!m.commits.some((c) => c.changes.some((x) => x.label === "Rank")));
  const times = m.commits.map((c) => toEpochMs(c.ts));
  assert.deepEqual(times, [...times].sort((x, y) => x - y));
});

test("creation shows the original values, recovered from the first change", () => {
  const created = model().commits[0];
  assert.equal(created.kind, "created");
  const get = (label) => created.changes.find((x) => x.label === label);
  assert.equal(get("Status").to, "To Do");
  assert.equal(get("Priority").to, "Major");
  assert.equal(get("Title").to, "Add retry");
  assert.equal(get("Description").initial[0], "h2. Goal");
  assert.ok(!created.changes.some((x) => x.label === "Assignee"), "was unassigned at creation");
});

test("automation is Jira app accounts plus configured account ids only", () => {
  const m = model();
  assert.equal(byId(m, "1001").bot, true, "accountType app");
  assert.equal(byId(m, "1011").bot, true, "configured id");
  assert.equal(byId(m, "1002").bot, false);
  assert.equal(model({ automationAccounts: [] }).commits.find((c) => c.id === "1011").bot, false);
});

test("status changes carry their transition; entries put the primary change first", () => {
  const c = byId(model(), "1002");
  assert.deepEqual(c.transition, { from: "To Do", to: "In Progress" });
  assert.equal(c.changes[0].cat, "status");
  assert.equal(c.subject, "Move to In Progress (+1 more)");
});

test("description history: edit, markup-only, broken characters saved and fixed, ADF", () => {
  const m = model();
  assert.equal(byId(m, "1004").subject, "Edit description (+3 −2)");
  assert.equal(byId(m, "1005").subject, "Reformat description (markup only)");
  assert.equal(byId(m, "1006").subject, "Save description with broken characters");
  assert.equal(byId(m, "1007").subject, "Fix broken characters in description");
  const adf = byId(m, "1008").changes[0].diff;
  assert.equal(adf.adf, true);
  assert.equal(byId(m, "1008").subject, "Edit description (+1 −0)");
  // Only the notes quote the broken form ("â€” → —"); no displayed text keeps it.
  const text = JSON.stringify(m, (k, v) => (k === "encoding" ? undefined : v));
  assert.ok(!text.includes("â€"), "no broken characters survive into displayed text");
  assert.deepEqual(byId(m, "1006").changes[0].diff.encoding.after, ["â€” → —"]);
});

test("comments keep Jira's rendered HTML, replies, edits and visibility", () => {
  const m = model();
  const c1 = byId(m, "c3001"), c2 = byId(m, "c3002"), c3 = byId(m, "c3003");
  assert.equal(c1.body.format, "html");
  assert.equal(c1.subject, "Can we cap it? See DEMO-7.");
  assert.equal(c2.body.format, "wiki");
  assert.equal(c2.parent, "c3001");
  assert.equal(c2.edited, "2026-03-02T10:45:00+00:00");
  assert.equal(c3.visibility, "Developers");
  assert.equal(c1.edited, undefined);
});

test("worklogs record time spent and when the work started", () => {
  const w = byId(model(), "w7001");
  assert.equal(w.subject, "Log 1h");
  assert.equal(w.started, "2026-03-03T11:00:00+00:00");
  assert.equal(w.body.text, "Load test of the *backoff*.");
});

test("development summary is found by field schema, not by name", () => {
  assert.deepEqual(model().dev, { branches: 0, commits: 4, pull_requests: 2, pull_request_state: "MERGED", builds: 3, failed_builds: 1, deployments: 0 });
  const b = fixture();
  b.issue.schema = {};
  assert.equal(buildModel(b, { tz: "utc" }).dev, null);
});

test("a short fetch is reported, never passed off as complete", () => {
  const b = fixture();
  b.completeness.changelog = { got: 18, total: 40, pages: 1, complete: false };
  delete b.completeness.worklogs;
  b.errors = [{ source: "comments", message: "no permission" }];
  const m = buildModel(b, { tz: "utc" });
  assert.equal(m.fetch[0].complete, false);
  assert.equal(m.fetch[2].complete, false);
  assert.ok(m.warnings.some((w) => w.includes("fetched 18 of 40")));
  assert.ok(m.warnings.some((w) => w.includes("Worklogs")));
  assert.ok(m.warnings.some((w) => w.includes("no permission")));
  assert.deepEqual(model().warnings, []);
});

test("defaults follow options and config", () => {
  const m = model({ types: ["comments", "status"], order: "asc", hideAutomation: true });
  assert.deepEqual(m.defaults, { types: ["status", "comments"], order: "asc", hide_automation: true });
});

// ------------------------------------------------------------ rendering --
test("the page embeds the data safely and names itself after the ticket", () => {
  const html = renderPage(template, model());
  assert.ok(html.includes("<title>DEMO-42 History</title>"));
  assert.ok(!html.includes("/*__DATA__*/null"));
  const data = html.slice(html.indexOf("const DATA = ") + 13, html.indexOf(";\nconst T = DATA.ticket"));
  assert.ok(!data.includes("<"), "no raw < inside the embedded JSON");
  assert.equal(JSON.parse(data).ticket.key, "DEMO-42");
  assert.ok(toJson({ a: "</script>" }).includes("\\u003c/script>"));
  assert.throws(() => renderPage("no marker", model()), /placeholder/);
});

// -------------------------------------------------------------- helpers --
test("timestamps parse with and without colons and render in the chosen zone", () => {
  assert.equal(toEpochMs("2026-03-02T10:00:05.000+0200"), Date.UTC(2026, 2, 2, 8, 0, 5));
  assert.equal(toEpochMs("2026-03-02T10:00:05+02:00"), Date.UTC(2026, 2, 2, 8, 0, 5));
  assert.equal(toEpochMs("2026-03-02T08:00:05Z"), Date.UTC(2026, 2, 2, 8, 0, 5));
  assert.equal(toEpochMs("yesterday"), null);
  assert.equal(renderTs(Date.UTC(2026, 2, 2, 8, 0, 5), "utc"), "2026-03-02T08:00:05+00:00");
});

test("html and wiki bodies reduce to a one-line subject", () => {
  assert.equal(htmlToText("<p>a &amp; b</p><p>c</p>"), "a & b\nc\n");
  assert.equal(firstLine("\n\n  hello  \nworld"), "hello");
  assert.equal(firstLine("x".repeat(100)).length, 79);
});

test("arguments are validated", () => {
  assert.throws(() => parseArgs([]), /--bundle/);
  assert.throws(() => parseArgs(["--bundle", "b", "--tz", "mars"]), /--tz/);
  assert.throws(() => parseArgs(["--bundle", "b", "--types", "status,bogus"]), /unknown type/);
  assert.deepEqual(parseArgs(["--bundle", "b", "--types", "status,comments", "--hide-automation"]).types, ["status", "comments"]);
});

// ------------------------------------------------------------ twin check --
function python() {
  const order = process.platform === "win32" ? [["py", "-3"], ["python3"], ["python"]] : [["python3"], ["python"], ["py", "-3"]];
  for (const cmd of order) {
    const r = spawnSync(cmd[0], [...cmd.slice(1), "-c", "import sys; print(sys.version_info[0])"], { encoding: "utf8" });
    if (r.status === 0 && r.stdout.trim() === "3") return cmd;
  }
  return null;
}

// The node build runs before the Python probe: on some Windows setups, spawning
// the Microsoft Store "python" stub breaks every later process spawn.
test("the Python twin writes a byte-identical page", (t) => {
  const dir = mkdtempSync(path.join(tmpdir(), "jth-"));
  try {
    const args = ["--bundle", path.join(here, "fixtures", "bundle.json"), "--config", path.join(here, "fixtures", "config.json"), "--tz", "utc"];
    const js = path.join(dir, "js.html"), py = path.join(dir, "py.html");
    const a = spawnSync(process.execPath, [path.join(here, "..", "build_history.mjs"), ...args, "--out", js], { encoding: "utf8" });
    assert.equal(a.status, 0, a.stderr);
    const cmd = python();
    if (!cmd) return t.skip("no Python 3 available");
    const b = spawnSync(cmd[0], [...cmd.slice(1), path.join(here, "..", "build_history.py"), ...args, "--out", py], { encoding: "utf8" });
    assert.equal(b.status, 0, b.stderr);
    assert.ok(readFileSync(js).equals(readFileSync(py)), "pages differ between runtimes");
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
