import test from "node:test";
import assert from "node:assert/strict";
import { detect, applyRows, main } from "../prune_records.mjs";
import { HEADERS, buildRows, writeCsv, readExisting } from "../../../scripts/build_csv.mjs";
import { mkdtempSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const RECS = [
  { key: "K-1", summary: "good", story_points: 3, issue_type: "Story", estimate_basis: "actual" },
  { key: "K-2", summary: "no points", issue_type: "Bug", estimate_basis: "final" },
  { key: "K-3", story_points: 5, issue_type: "Task", estimate_basis: "actual" },
  { key: "K-4", summary: "flag me", story_points: 8, issue_type: "Story" },
  { key: "", summary: "orphan", story_points: 2, issue_type: "Story", estimate_basis: "actual" },
  { key: "K-6", summary: "bad pts", story_points: "abc", issue_type: "Story", estimate_basis: "actual" },
];

function fixtureRows() {
  const dir = mkdtempSync(join(tmpdir(), "est-prune-"));
  try {
    const out = join(dir, "history.csv");
    writeCsv(out, buildRows([], RECS, "overwrite"));
    return readExisting(out);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

test("classifies prune and flag", () => {
  const res = detect(fixtureRows());
  const prune = Object.fromEntries(res.prune.map((p) => [p.row, p]));
  const flag = Object.fromEntries(res.flag.map((f) => [f.row, f]));
  assert.deepEqual(res.prune.map((p) => p.row).sort((a, b) => a - b), [2, 3, 5, 6]);
  assert.deepEqual(res.flag.map((f) => f.row), [4]);
  assert.deepEqual(prune[2].reasons, ["missing/invalid story_points"]);
  assert.equal(prune[2].key, "K-2");
  assert.deepEqual(prune[3].reasons, ["missing summary"]);
  assert.deepEqual(prune[5].reasons, ["missing key"]);
  assert.equal(prune[5].key, "");
  assert.deepEqual(prune[6].reasons, ["missing/invalid story_points"]);
  assert.deepEqual(flag[4].warnings, ["blank/invalid estimate_basis"]);
});

test("clean row in neither", () => {
  const res = detect(fixtureRows());
  const listed = new Set([...res.prune.map((p) => p.row), ...res.flag.map((f) => f.row)]);
  assert.ok(!listed.has(1));
});

test("prune supersedes flag", () => {
  const dir = mkdtempSync(join(tmpdir(), "est-prune-"));
  try {
    const out = join(dir, "history.csv");
    writeCsv(out, buildRows([], [{ key: "X-1", story_points: 3 }], "overwrite"));
    const res = detect(readExisting(out));
    assert.deepEqual(res.prune.map((p) => p.row), [1]);
    assert.deepEqual(res.flag, []);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("legacy 12-column row flagged for blank basis", () => {
  const dir = mkdtempSync(join(tmpdir(), "est-prune-"));
  try {
    const out = join(dir, "history.csv");
    writeFileSync(out, HEADERS.slice(0, 12).join(";") + "\nLEG-1;;Story;has title;;;;3;;2026-01-01;;\n", "utf8");
    const res = detect(readExisting(out));
    assert.deepEqual(res.prune, []);
    assert.deepEqual(res.flag.map((f) => f.row), [1]);
    assert.ok(res.flag[0].warnings.includes("blank/invalid estimate_basis"));
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("applyRows deletes by row number incl keyless", () => {
  const res = applyRows(fixtureRows(), [2, 5]);
  assert.deepEqual(res.deleted_rows, [2, 5]);
  assert.deepEqual(res.deleted_keys, ["K-2", ""]);
  assert.deepEqual(res.rows.map((r) => r[0]), ["K-1", "K-3", "K-4", "K-6"]);
});

test("applyRows out-of-range and empty are no-ops", () => {
  const rows = fixtureRows();
  assert.deepEqual(applyRows(rows, [99]).deleted_rows, []);
  assert.equal(applyRows(rows, []).rows.length, rows.length);
});

test("story_points numeric definition (cross-runtime safe)", () => {
  const pruneRows = (sp) => {
    const dir = mkdtempSync(join(tmpdir(), "est-prune-"));
    try {
      const out = join(dir, "h.csv");
      writeCsv(out, buildRows([], [{ key: "K", summary: "s", story_points: sp, issue_type: "Story", estimate_basis: "actual" }], "overwrite"));
      return detect(readExisting(out)).prune.map((p) => p.row);
    } finally { rmSync(dir, { recursive: true, force: true }); }
  };
  assert.deepEqual(pruneRows("0"), []);
  assert.deepEqual(pruneRows("8.0"), []);
  assert.deepEqual(pruneRows("inf"), [1]);
  assert.deepEqual(pruneRows("nan"), [1]);
  assert.deepEqual(pruneRows("1e3"), [1]);
});

test("header-only csv is clean", () => {
  const dir = mkdtempSync(join(tmpdir(), "est-prune-"));
  try {
    const out = join(dir, "h.csv");
    writeFileSync(out, HEADERS.join(";") + "\n", "utf8");
    assert.deepEqual(detect(readExisting(out)), { prune: [], flag: [] });
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

test("applyRows dedupes duplicate row numbers", () => {
  assert.deepEqual(applyRows(fixtureRows(), [2, 2]).deleted_rows, [2]);
});

test("applyRows rejects invalid row numbers", () => {
  assert.throws(() => applyRows(fixtureRows(), [0]));
  assert.throws(() => applyRows(fixtureRows(), [-1]));
  assert.throws(() => applyRows(fixtureRows(), [1.5]));
});

test("main apply writes file", () => {
  const dir = mkdtempSync(join(tmpdir(), "est-prune-"));
  try {
    const out = join(dir, "history.csv");
    writeCsv(out, buildRows([], RECS, "overwrite"));
    const rj = join(dir, "r.json");
    writeFileSync(rj, JSON.stringify({ rows: [2, 3, 5, 6] }));
    main(["apply", out, rj]);
    assert.deepEqual(readExisting(out).map((r) => r[0]), ["K-1", "K-4"]);
  } finally { rmSync(dir, { recursive: true, force: true }); }
});
