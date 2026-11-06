import test from "node:test";
import assert from "node:assert/strict";
import { dump, FIELD_KEYS } from "../dump_records.mjs";
import { HEADERS, buildRows, writeCsv, readExisting } from "../build_csv.mjs";
import { mkdtempSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const RECS = [
  { key: "K-1", summary: "first", story_points: 3, estimate_basis: "actual" },
  { key: "K-2", summary: "two; semi", description: 'a "q" and\nnl', comments: ["c;1", "x"], story_points: 5, estimate_basis: "final" },
];

function rows() {
  const dir = mkdtempSync(join(tmpdir(), "est-dump-"));
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

test("dump full records with row", () => {
  const recs = dump(rows());
  assert.deepEqual(recs.map((r) => r.row), [1, 2]);
  assert.equal(recs[0].key, "K-1");
  assert.equal(recs[0].story_points, "3");
  assert.equal(recs[0].estimate_basis, "actual");
  assert.equal(Object.keys(recs[0]).length, HEADERS.length + 1);
});

test("special chars preserved", () => {
  const recs = dump(rows());
  assert.equal(recs[1].summary, "two; semi");
  assert.equal(recs[1].description, 'a "q" and\nnl');
  assert.equal(recs[1].comments, "c;1\n\nx");
});

test("empty history is empty list", () => {
  const dir = mkdtempSync(join(tmpdir(), "est-dump-"));
  try {
    const out = join(dir, "history.csv");
    writeFileSync(out, HEADERS.join(";") + "\n", "utf8");
    assert.deepEqual(dump(readExisting(out)), []);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("legacy 12-col row padded", () => {
  const dir = mkdtempSync(join(tmpdir(), "est-dump-"));
  try {
    const out = join(dir, "history.csv");
    writeFileSync(out, HEADERS.slice(0, 12).join(";") + "\nLEG-1;;Story;t;;;;3;;2026-01-01;;\n", "utf8");
    const recs = dump(readExisting(out));
    assert.equal(recs[0].row, 1);
    assert.equal(recs[0].estimate_basis, "");
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("short raw row fills blanks", () => {
  const recs = dump([["K-X"]]);
  assert.equal(recs[0].row, 1);
  assert.equal(recs[0].key, "K-X");
  assert.equal(recs[0].estimate_basis, "");
  assert.equal(Object.keys(recs[0]).length, HEADERS.length + 1);
});
