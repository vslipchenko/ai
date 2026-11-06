import test from "node:test";
import assert from "node:assert/strict";
import { HEADERS, recordToRow, formatField, formatRow } from "../build_csv.mjs";

test("headers have thirteen columns", () => {
  assert.equal(HEADERS.length, 13);
  assert.equal(HEADERS[1], "Parent (parent_key)");
  assert.equal(HEADERS[HEADERS.length - 1], "Estimate Basis (estimate_basis)");
});

test("recordToRow maps full record in header order", () => {
  const rec = {
    key: "PROJ-1", parent_key: "PROJ-100", issue_type: "Story",
    summary: "Add login", description: "Desc",
    components: ["Backend", "Frontend"], labels: ["auth", "mvp"],
    story_points: 5, time_spent_seconds: 14400, resolution_date: "2026-01-15",
    comments: ["first", "second"], design_link: "https://figma.com/x",
    estimate_basis: "actual",
  };
  assert.deepEqual(recordToRow(rec), [
    "PROJ-1", "PROJ-100", "Story", "Add login", "Desc",
    "Backend, Frontend", "auth, mvp", "5", "14400",
    "2026-01-15", "first\n\nsecond", "https://figma.com/x", "actual",
  ]);
});

test("recordToRow blanks missing fields", () => {
  const row = recordToRow({ key: "PROJ-2" });
  assert.equal(row.length, 13);
  assert.ok(row.slice(1).every((c) => c === ""));
});

test("formatField quotes delimiter, quotes, and newlines", () => {
  assert.equal(formatField("plain"), "plain");
  assert.equal(formatField("a;b"), '"a;b"');
  assert.equal(formatField('a"b'), '"a""b"');
  assert.equal(formatField("a\nb"), '"a\nb"');
});

test("formatRow joins with semicolons", () => {
  assert.equal(formatRow(["a", "b;c", "d"]), 'a;"b;c";d');
});

import { parseCsv } from "../build_csv.mjs";

test("parseCsv handles quoted delimiters, quotes, and newlines", () => {
  const text = 'Key (key);Title (summary)\nPROJ-1;"a;b"\nPROJ-2;"line\nbreak ""q"""\n';
  const rows = parseCsv(text);
  assert.deepEqual(rows[0], ["Key (key)", "Title (summary)"]);
  assert.deepEqual(rows[1], ["PROJ-1", "a;b"]);
  assert.deepEqual(rows[2], ["PROJ-2", 'line\nbreak "q"']);
});

test("parseCsv round-trips formatRow output", () => {
  const original = ["PROJ-9", "a;b", 'a"b', "x\ny"];
  const rows = parseCsv(formatRow(original) + "\n");
  assert.deepEqual(rows[0], original);
});

import { buildRows, readExisting, writeCsv, main } from "../build_csv.mjs";
import { mkdtempSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

test("buildRows overwrite ignores existing", () => {
  const rows = buildRows([["OLD-1"]], [{ key: "NEW-1" }], "overwrite");
  assert.deepEqual(rows.map((r) => r[0]), ["NEW-1"]);
});

test("buildRows append merges then overrides same key", () => {
  const existing = [["PROJ-1", "", "", "old"]];
  const rows = buildRows(existing, [{ key: "PROJ-1", summary: "new" }], "append");
  assert.equal(rows.length, 1);
  assert.equal(rows[0][3], "new");
});

test("writeCsv + readExisting round-trip with special chars", () => {
  const dir = mkdtempSync(join(tmpdir(), "est-"));
  try {
    const out = join(dir, "sub", "history.csv");
    writeCsv(out, buildRows([], [{
      key: "PROJ-9", summary: "has ; semicolon",
      description: 'a "quote" and\nnewline', comments: ["c;1", "x"],
    }], "overwrite"));
    const rows = readExisting(out);
    assert.equal(rows.length, 1);
    assert.equal(rows[0][3], "has ; semicolon");
    assert.equal(rows[0][4], 'a "quote" and\nnewline');
    assert.equal(rows[0][10], "c;1\n\nx");
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("main appends via CLI", () => {
  const dir = mkdtempSync(join(tmpdir(), "est-"));
  try {
    const out = join(dir, "history.csv");
    writeCsv(out, buildRows([], [{ key: "OLD-1" }], "overwrite"));
    const inp = join(dir, "in.json");
    writeFileSync(inp, JSON.stringify([{ key: "NEW-1" }]));
    main([inp, out, "append"]);
    assert.deepEqual(readExisting(out).map((r) => r[0]), ["OLD-1", "NEW-1"]);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("buildRows dedup within records keeps last occurrence", () => {
  const rows = buildRows([], [
    { key: "PROJ-1", summary: "first" },
    { key: "PROJ-1", summary: "second" },
  ], "overwrite");
  assert.equal(rows.length, 1);
  assert.equal(rows[0][3], "second");
});

test("buildRows append preserves existing-then-new order", () => {
  const existing = [["A-1"], ["A-2"]];
  const rows = buildRows(existing, [{ key: "A-3" }, { key: "A-1" }], "append");
  assert.deepEqual(rows.map((r) => r[0]), ["A-1", "A-2", "A-3"]);
});

test("readExisting returns empty array for missing file", () => {
  const dir = mkdtempSync(join(tmpdir(), "est-"));
  assert.deepEqual(readExisting(join(dir, "nope.csv")), []);
});

test("append pads legacy 12-column rows out to 13", () => {
  const dir = mkdtempSync(join(tmpdir(), "est-"));
  try {
    const out = join(dir, "history.csv");
    // CSV written before the estimate_basis column existed: 12 fields.
    const header = HEADERS.slice(0, 12).join(";");
    writeFileSync(out, header + "\nLEG-1;;Story;old;;;;3;;2026-01-01;;\n", "utf8");
    const rows = buildRows(
      readExisting(out),
      [{ key: "NEW-1", estimate_basis: "final" }],
      "append",
    );
    writeCsv(out, rows);
    const result = readExisting(out);
    assert.deepEqual(result.map((r) => r[0]), ["LEG-1", "NEW-1"]);
    assert.ok(result.every((r) => r.length === 13));
    assert.equal(result[0][12], "");       // legacy row: blank basis
    assert.equal(result[1][12], "final");  // new row: basis set
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("recordToRow: string scalar for array field is not char-split", () => {
  const row = recordToRow({ key: "K-1", components: "Backend" });
  assert.equal(row[5], "Backend");
});

test("recordToRow: string scalar comments not char-split", () => {
  const row = recordToRow({ key: "K-1", comments: "one comment" });
  assert.equal(row[10], "one comment");
});

test("recordToRow: empty array is blank", () => {
  const row = recordToRow({ key: "K-1", components: [] });
  assert.equal(row[5], "");
});
