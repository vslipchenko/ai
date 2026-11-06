import test from "node:test";
import assert from "node:assert/strict";
import { findRecords, FIELD_KEYS } from "../find_records.mjs";
import { HEADERS, buildRows, writeCsv, readExisting } from "../../../../scripts/build_csv.mjs";
import { mkdtempSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const RECS = [
  { key: "K-1", issue_type: "Story", summary: "first", story_points: 3, estimate_basis: "actual" },
  { key: "K-2", issue_type: "Bug", summary: "second", comments: ["line1\nline2", "c;2"], story_points: 5, estimate_basis: "final" },
  { key: "K-3", issue_type: "Task", summary: "third", story_points: 8, estimate_basis: "suggested" },
];

function fixtureRows() {
  const dir = mkdtempSync(join(tmpdir(), "est-find-"));
  try {
    const out = join(dir, "history.csv");
    writeCsv(out, buildRows([], RECS, "overwrite"));
    return readExisting(out);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

test("FIELD_KEYS match schema", () => {
  assert.equal(FIELD_KEYS[0], "key");
  assert.equal(FIELD_KEYS[FIELD_KEYS.length - 1], "estimate_basis");
  assert.equal(FIELD_KEYS.length, HEADERS.length);
});

test("single key found with row", () => {
  const res = findRecords(fixtureRows(), ["K-1"]);
  assert.deepEqual(res.missing, []);
  assert.equal(res.found.length, 1);
  assert.equal(res.found[0].row, 1);
  assert.equal(res.found[0].key, "K-1");
  assert.equal(res.found[0].story_points, "3");
  assert.equal(res.found[0].estimate_basis, "actual");
});

test("multiple keys mixed and in request order", () => {
  const res = findRecords(fixtureRows(), ["K-3", "k-1", "NOPE"]);
  assert.deepEqual(res.found.map((r) => r.key), ["K-3", "K-1"]);
  assert.deepEqual(res.found.map((r) => r.row), [3, 1]);
  assert.deepEqual(res.missing, ["NOPE"]);
});

test("multiline comment does not shift later rows", () => {
  const res = findRecords(fixtureRows(), ["K-3"]);
  assert.equal(res.found[0].row, 3);
});

test("legacy 12-column row resolves with blank basis", () => {
  const dir = mkdtempSync(join(tmpdir(), "est-find-"));
  try {
    const out = join(dir, "history.csv");
    writeFileSync(out, HEADERS.slice(0, 12).join(";") + "\nLEG-1;;Story;old;;;;3;;2026-01-01;;\n", "utf8");
    const res = findRecords(readExisting(out), ["LEG-1"]);
    assert.equal(res.found[0].row, 1);
    assert.equal(res.found[0].estimate_basis, "");
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("duplicate input keys return multiple entries", () => {
  const res = findRecords(fixtureRows(), ["K-1", "K-1"]);
  assert.equal(res.found.length, 2);
  assert.deepEqual(res.missing, []);
});

test("blank keys are skipped", () => {
  const res = findRecords(fixtureRows(), ["K-1", "   ", ""]);
  assert.deepEqual(res.found.map((r) => r.key), ["K-1"]);
  assert.deepEqual(res.missing, []);
});
