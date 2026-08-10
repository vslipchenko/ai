// Import an external history CSV into the estimator dataset (merge or replace).
// Reuses build_csv's HEADERS/readExisting/writeCsv/parseCsv. Header-aware mapping.
// Prints {"mode":...,"imported":N,"row_count":M,"project_keys":[...]}.
import { HEADERS, FIELD_KEYS as _FIELD_KEYS, readExisting, writeCsv, parseCsv } from "../../../scripts/build_csv.mjs";
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

export const FIELD_KEYS = _FIELD_KEYS;
const COL = Object.fromEntries(FIELD_KEYS.map((fk, i) => [fk, i]));

function headerMap(headerRow) {
  const mapping = {};
  headerRow.forEach((cell, idx) => {
    const m = String(cell).trim().match(/\(([^)]+)\)\s*$/);
    // duplicate columns mapping to the same field: last occurrence wins
    if (m && m[1] in COL) mapping[m[1]] = idx;
  });
  return mapping;
}

export function mapSource(parsedRows) {
  if (!parsedRows.length) throw new Error("source is empty");
  const [header, ...data] = parsedRows;
  const mapping = headerMap(header);
  if (!("key" in mapping)) {
    throw new Error("source headers not recognized (no 'key' column); expected estimator history columns");
  }
  const rows = [];
  for (const row of data) {
    if (!row.length || row.every((c) => String(c).trim() === "")) continue;
    rows.push(FIELD_KEYS.map((fk) => {
      const j = mapping[fk];
      return j !== undefined && j < row.length ? row[j] : "";
    }));
  }
  return rows;
}

export function buildDataset(sourceRows, targetRows, mode) {
  if (mode !== "merge" && mode !== "replace") {
    throw new Error(`mode must be 'merge' or 'replace', got: ${mode}`);
  }
  // keys are matched verbatim (consistent with build_csv dedup)
  const merged = new Map();
  if (mode === "merge") {
    for (const row of targetRows) if (row && row.length) merged.set(row[0], row);
  }
  for (const row of sourceRows) merged.set(row[0], row);
  return [...merged.values()];
}

export function deriveProjectKeys(rows) {
  const prefixes = new Set();
  for (const row of rows) {
    const key = row && row.length ? String(row[0]).trim() : "";
    if (!key) continue;
    prefixes.add(key.includes("-") ? key.slice(0, key.lastIndexOf("-")) : key);
  }
  return [...prefixes].sort();
}

export function main(argv) {
  if (argv.length !== 3) {
    console.error("Usage: import_records.mjs <source.csv> <target.csv> <merge|replace>");
    process.exit(1);
  }
  const [source, target, mode] = argv;
  const parsed = parseCsv(readFileSync(source, "utf8").replace(/^﻿/, ""));
  let sourceRows, result;
  try {
    sourceRows = mapSource(parsed);
    const targetRows = mode === "merge" ? readExisting(target) : [];
    result = buildDataset(sourceRows, targetRows, mode);
  } catch (e) {
    console.error(`error: ${e.message}`);
    process.exit(1);
  }
  writeCsv(target, result);
  console.log(JSON.stringify({
    mode,
    imported: sourceRows.length,
    row_count: result.length,
    project_keys: deriveProjectKeys(result),
  }));
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main(process.argv.slice(2));
}
