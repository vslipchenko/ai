import test from "node:test";
import assert from "node:assert/strict";
import { mapSource, buildDataset, deriveProjectKeys, main } from "../import_records.mjs";
import { HEADERS, buildRows, writeCsv, readExisting } from "../../../../scripts/build_csv.mjs";
import { mkdtempSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

test("mapSource: reordered + unknown columns", () => {
  const header = ["Key (key)", "Bogus (bogus)", "Title (summary)", "Story Points (story_points)"];
  const data = ["K-1", "junk", "hello", "5"];
  const rows = mapSource([header, data]);
  assert.equal(rows.length, 1);
  assert.equal(rows[0].length, HEADERS.length);
  assert.equal(rows[0][0], "K-1");
  assert.equal(rows[0][3], "hello");
  assert.equal(rows[0][7], "5");
  assert.equal(rows[0][1], "");
  assert.equal(rows[0][12], "");
});

test("mapSource: legacy 12-col source", () => {
  const header = HEADERS.slice(0, 12);
  const data = ["K-1", "", "Story", "title", "", "", "", "3", "", "2026-01-01", "", ""];
  const rows = mapSource([header, data]);
  assert.equal(rows[0][0], "K-1");
  assert.equal(rows[0][12], "");
});

test("mapSource: no key column throws", () => {
  assert.throws(() => mapSource([["Title (summary)", "Story Points (story_points)"], ["hello", "5"]]));
});

test("mapSource: skips all-blank rows", () => {
  const header = [...HEADERS];
  const blank = Array(13).fill("");
  const keep = ["K-2", ...Array(12).fill("")];
  const rows = mapSource([header, blank, keep]);
  assert.deepEqual(rows.map((r) => r[0]), ["K-2"]);
});

test("buildDataset: replace uses source only", () => {
  const res = buildDataset([["S-1", ...Array(12).fill("")]], [["T-1", ...Array(12).fill("")]], "replace");
  assert.deepEqual(res.map((r) => r[0]), ["S-1"]);
});

test("buildDataset: merge imported wins and order", () => {
  const target = [["A-1", "", "", "old", ...Array(9).fill("")], ["A-2", ...Array(12).fill("")]];
  const source = [["A-3", ...Array(12).fill("")], ["A-1", "", "", "new", ...Array(9).fill("")]];
  const res = buildDataset(source, target, "merge");
  assert.deepEqual(res.map((r) => r[0]), ["A-1", "A-2", "A-3"]);
  assert.equal(res[0][3], "new");
});

test("buildDataset: invalid mode throws", () => {
  assert.throws(() => buildDataset([], [], "append"));
});

test("deriveProjectKeys: distinct sorted prefixes, skip blank", () => {
  const rows = [["ABC-7", ...Array(12).fill("")], ["ABC-8", ...Array(12).fill("")], ["CORE-1", ...Array(12).fill("")], ["", ...Array(12).fill("")]];
  assert.deepEqual(deriveProjectKeys(rows), ["ABC", "CORE"]);
});

test("main replace writes target", () => {
  const dir = mkdtempSync(join(tmpdir(), "est-import-"));
  try {
    const source = join(dir, "src.csv");
    writeFileSync(source, HEADERS.join(";") + "\nABC-1;;Story;t;;;;3;;2026-01-01;;actual\n", "utf8");
    const target = join(dir, "history.csv");
    main([source, target, "replace"]);
    assert.deepEqual(readExisting(target).map((r) => r[0]), ["ABC-1"]);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("main merge combines", () => {
  const dir = mkdtempSync(join(tmpdir(), "est-import-"));
  try {
    const target = join(dir, "history.csv");
    writeCsv(target, buildRows([], [{ key: "OLD-1", summary: "keep" }], "overwrite"));
    const source = join(dir, "src.csv");
    writeFileSync(source, HEADERS.join(";") + "\nNEW-1;;Story;t;;;;3;;;;actual\n", "utf8");
    main([source, target, "merge"]);
    assert.deepEqual(readExisting(target).map((r) => r[0]), ["OLD-1", "NEW-1"]);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("mapSource: header-only source imports nothing", () => {
  assert.deepEqual(mapSource([[...HEADERS]]), []);
});

test("buildDataset: replace dedups source-internal duplicates (last wins)", () => {
  const source = [["X-1", "", "", "a", ...Array(9).fill("")], ["X-1", "", "", "b", ...Array(9).fill("")]];
  const res = buildDataset(source, [], "replace");
  assert.equal(res.length, 1);
  assert.equal(res[0][3], "b");
});

test("main: source CSV with UTF-8 BOM imports correctly", () => {
  const dir = mkdtempSync(join(tmpdir(), "est-import-bom-"));
  try {
    const source = join(dir, "bom_src.csv");
    // Write UTF-8 BOM (U+FEFF) followed by the header and a data row
    const content = "﻿" + HEADERS.join(";") + "\nBOM-1;;Story;t;;;;3;;2026-01-01;;actual\n";
    writeFileSync(source, content, "utf8");
    const target = join(dir, "history.csv");
    main([source, target, "replace"]);
    const rows = readExisting(target);
    assert.equal(rows.length, 1);
    assert.equal(rows[0][0], "BOM-1");
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
