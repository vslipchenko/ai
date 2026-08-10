// Scan / prune low-quality records in the estimator history CSV.
// Reuses build_csv's parser/HEADERS/writer.
//   detect <history.csv> → {"prune":[{row,key,reasons}],"flag":[{row,key,warnings}]}
//   apply  <history.csv> <rows.json {"rows":[...]}> → {"deleted_rows":[...],"deleted_keys":[...],"row_count":N}
import { HEADERS, FIELD_KEYS as _FIELD_KEYS, readExisting, writeCsv } from "../../scripts/build_csv.mjs";
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

export const FIELD_KEYS = _FIELD_KEYS;
const COL = Object.fromEntries(FIELD_KEYS.map((fk, i) => [fk, i]));
const VALID_BASIS = new Set(["actual", "final", "suggested"]);

const cell = (row, fk) => (COL[fk] < row.length ? row[COL[fk]] : "");
const blank = (v) => v === null || v === undefined || String(v).trim() === "";
const NUMBER_RE = /^\d+(\.\d+)?$/;
const isNumber = (v) => NUMBER_RE.test(String(v).trim());

export function detect(rows) {
  const prune = [];
  const flag = [];
  rows.forEach((row, idx) => {
    const i = idx + 1;
    const key = cell(row, "key");
    const reasons = [];
    if (blank(key)) reasons.push("missing key");
    if (blank(cell(row, "summary"))) reasons.push("missing summary");
    if (!isNumber(cell(row, "story_points"))) reasons.push("missing/invalid story_points");
    if (reasons.length) { prune.push({ row: i, key, reasons }); return; }
    const warnings = [];
    if (!VALID_BASIS.has(cell(row, "estimate_basis").trim())) warnings.push("blank/invalid estimate_basis");
    if (blank(cell(row, "issue_type"))) warnings.push("missing issue_type");
    if (warnings.length) flag.push({ row: i, key, warnings });
  });
  return { prune, flag };
}

export function applyRows(rows, rowNumbers) {
  for (const n of rowNumbers) {
    if (!Number.isInteger(n) || n < 1) throw new Error(`row numbers must be positive integers, got: ${n}`);
  }
  const deleteSet = new Set(rowNumbers);
  const result = [];
  const deletedRows = [];
  const deletedKeys = [];
  rows.forEach((row, idx) => {
    const i = idx + 1;
    if (deleteSet.has(i)) { deletedRows.push(i); deletedKeys.push(row && row.length ? row[0] : ""); }
    else result.push(row);
  });
  return { rows: result, deleted_rows: deletedRows, deleted_keys: deletedKeys };
}

export function main(argv) {
  // argv is already sliced (process.argv.slice(2)): [mode, historyCsv, rowsJson]
  if (argv.length < 2) {
    console.error("Usage: prune_records.mjs <detect|apply> <history.csv> [rows.json]");
    process.exit(1);
  }
  const [mode, historyCsv] = argv;
  const rows = readExisting(historyCsv);
  if (mode === "detect") {
    console.log(JSON.stringify(detect(rows)));
  } else if (mode === "apply") {
    if (argv.length !== 3) { console.error("Usage: prune_records.mjs apply <history.csv> <rows.json>"); process.exit(1); }
    const rowNumbers = JSON.parse(readFileSync(argv[2], "utf8")).rows || [];
    let result;
    try { result = applyRows(rows, rowNumbers); }
    catch (e) { console.error(`error: ${e.message}`); process.exit(1); }
    writeCsv(historyCsv, result.rows);
    console.log(JSON.stringify({ deleted_rows: result.deleted_rows, deleted_keys: result.deleted_keys, row_count: result.rows.length }));
  } else {
    console.error(`unknown mode: ${mode}`);
    process.exit(1);
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main(process.argv.slice(2));
}
