import test from "node:test";
import assert from "node:assert/strict";
import { applyChanges, FIELD_KEYS, main } from "../edit_records.mjs";
import { HEADERS, buildRows, writeCsv, readExisting } from "../../../../scripts/build_csv.mjs";
import { mkdtempSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const RECS = [
  { key: "K-1", issue_type: "Story", summary: "first", story_points: 3, estimate_basis: "actual" },
  { key: "K-2", issue_type: "Bug", summary: "second", comments: ["a\nb"], story_points: 5, estimate_basis: "final" },
  { key: "K-3", issue_type: "Task", summary: "third", story_points: 8, estimate_basis: "suggested" },
];
const COL = Object.fromEntries(FIELD_KEYS.map((fk, i) => [fk, i]));

function rows() {
  const dir = mkdtempSync(join(tmpdir(), "est-edit-"));
  try {
    const out = join(dir, "history.csv");
    writeCsv(out, buildRows([], RECS, "overwrite"));
    return readExisting(out);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

test("edit single field", () => {
  const res = applyChanges(rows(), [{ key: "K-1", fields: { summary: "changed" } }], []);
  assert.deepEqual(res.updated, ["K-1"]);
  assert.deepEqual(res.deleted, []);
  assert.deepEqual(res.missing, []);
  assert.deepEqual(res.rows.map((r) => r[0]), ["K-1", "K-2", "K-3"]);
  assert.equal(res.rows[0][COL.summary], "changed");
});

test("edit multiple fields per record", () => {
  const res = applyChanges(rows(), [
    { key: "K-1", fields: { summary: "s1", story_points: "13" } },
    { key: "K-2", fields: { estimate_basis: "actual" } },
  ], []);
  assert.deepEqual(res.updated, ["K-1", "K-2"]);
  assert.equal(res.rows[0][COL.summary], "s1");
  assert.equal(res.rows[0][COL.story_points], "13");
  assert.equal(res.rows[1][COL.estimate_basis], "actual");
});

test("delete preserves order", () => {
  const res = applyChanges(rows(), [], ["K-2"]);
  assert.deepEqual(res.deleted, ["K-2"]);
  assert.deepEqual(res.rows.map((r) => r[0]), ["K-1", "K-3"]);
});

test("missing keys reported", () => {
  const res = applyChanges(rows(), [{ key: "NOPE", fields: { summary: "x" } }], ["GONE"]);
  assert.deepEqual(res.updated, []);
  assert.deepEqual(res.deleted, []);
  assert.deepEqual(res.missing, ["NOPE", "GONE"]);
  assert.equal(res.rows.length, 3);
});

test("editing key field throws", () => {
  assert.throws(() => applyChanges(rows(), [{ key: "K-1", fields: { key: "X-9" } }], []));
});

test("unknown field throws", () => {
  assert.throws(() => applyChanges(rows(), [{ key: "K-1", fields: { bogus: "x" } }], []));
});

test("combined edit and delete", () => {
  const res = applyChanges(rows(), [{ key: "k-1", fields: { summary: "z" } }], ["K-3"]);
  assert.deepEqual(res.updated, ["K-1"]);
  assert.deepEqual(res.deleted, ["K-3"]);
  assert.deepEqual(res.rows.map((r) => r[0]), ["K-1", "K-2"]);
  assert.equal(res.rows[0][COL.summary], "z");
});

test("key in both edits and deletes throws", () => {
  assert.throws(() => applyChanges(rows(), [{ key: "K-1", fields: { summary: "x" } }], ["K-1"]));
});

test("blank keys skipped", () => {
  const res = applyChanges(rows(), [{ key: "  ", fields: { summary: "x" } }], ["  "]);
  assert.deepEqual(res.updated, []);
  assert.deepEqual(res.deleted, []);
  assert.deepEqual(res.missing, []);
  assert.equal(res.rows.length, 3);
});

test("duplicate edit keys last wins", () => {
  const res = applyChanges(rows(), [
    { key: "K-1", fields: { summary: "a" } },
    { key: "K-1", fields: { summary: "b" } },
  ], []);
  assert.deepEqual(res.updated, ["K-1"]);
  assert.equal(res.rows[0][COL.summary], "b");
});

test("empty fields counts as updated, no change", () => {
  const res = applyChanges(rows(), [{ key: "K-1", fields: {} }], []);
  assert.deepEqual(res.updated, ["K-1"]);
  assert.equal(res.rows[0][COL.summary], "first");
});

test("null field value becomes blank", () => {
  const res = applyChanges(rows(), [{ key: "K-1", fields: { summary: null } }], []);
  assert.equal(res.rows[0][COL.summary], "");
});

test("main writes file and upgrades legacy rows", () => {
  const dir = mkdtempSync(join(tmpdir(), "est-edit-"));
  try {
    const out = join(dir, "history.csv");
    writeFileSync(out,
      HEADERS.slice(0, 12).join(";") + "\nLEG-1;;Story;old;;;;3;;2026-01-01;;\nLEG-2;;Bug;two;;;;5;;2026-01-02;;\n",
      "utf8");
    const instr = join(dir, "i.json");
    writeFileSync(instr, JSON.stringify({ edits: [{ key: "LEG-1", fields: { estimate_basis: "final" } }], deletes: ["LEG-2"] }));
    main([out, instr]);
    const result = readExisting(out);
    assert.deepEqual(result.map((r) => r[0]), ["LEG-1"]);
    assert.ok(result.every((r) => r.length === 13));
    assert.equal(result[0][COL.estimate_basis], "final");
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
