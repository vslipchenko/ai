// Edit or delete records in the estimator history CSV.
// Reuses build_csv's parser/HEADERS/writer. Instructions:
//   {"edits":[{"key":"ABC-1","fields":{"summary":"..."}}],"deletes":["ABC-2"]}
// Prints {"updated":[...],"deleted":[...],"missing":[...],"row_count":N}.
import { HEADERS, FIELD_KEYS as _FIELD_KEYS, readExisting, writeCsv } from "../../../scripts/build_csv.mjs";
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

export const FIELD_KEYS = _FIELD_KEYS;
const COL = new Map(FIELD_KEYS.map((fk, i) => [fk, i]));

function dedup(seq) {
  const seen = new Set();
  const out = [];
  for (const x of seq) if (!seen.has(x)) { seen.add(x); out.push(x); }
  return out;
}

export function applyChanges(rows, edits, deletes) {
  // Validate before mutating so a bad instruction changes nothing.
  for (const edit of edits) {
    for (const fk of Object.keys(edit.fields || {})) {
      if (fk === "key") throw new Error("'key' is read-only and cannot be edited");
      if (!COL.has(fk)) throw new Error(`unknown field: ${fk}`);
    }
  }
  const editKeys = new Set(edits.map((e) => String(e.key ?? "").trim().toUpperCase()));
  const deleteKeysSet = new Set(deletes.map((k) => String(k).trim().toUpperCase()));
  const overlap = [...editKeys].filter((k) => k && deleteKeysSet.has(k)).sort();
  if (overlap.length) throw new Error(`key(s) appear in both edits and deletes: ${overlap.join(", ")}`);
  const index = new Map();
  for (const row of rows) if (row && row.length) index.set(row[0], row);
  const updated = [];
  const deleteKeys = [];
  const missing = [];
  for (const edit of edits) {
    const k = String(edit.key ?? "").trim().toUpperCase();
    if (!k) continue;
    if (index.has(k)) {
      const row = index.get(k);
      for (const [fk, val] of Object.entries(edit.fields || {})) {
        row[COL.get(fk)] = val === null || val === undefined ? "" : String(val);
      }
      updated.push(k);
    } else {
      missing.push(k);
    }
  }
  for (const key of deletes) {
    const k = String(key).trim().toUpperCase();
    if (!k) continue;
    if (index.has(k)) deleteKeys.push(k);
    else missing.push(k);
  }
  const deleteSet = new Set(deleteKeys);
  const resultRows = rows.filter((row) => row && row.length && !deleteSet.has(row[0]));
  return { rows: resultRows, updated: dedup(updated), deleted: dedup(deleteKeys), missing: dedup(missing) };
}

export function main(argv) {
  // argv is already sliced (process.argv.slice(2)): [historyCsv, instructionsPath]
  if (argv.length !== 2) {
    console.error("Usage: edit_records.mjs <history.csv> <instructions.json>");
    process.exit(1);
  }
  const [historyCsv, instructionsPath] = argv;
  const instructions = JSON.parse(readFileSync(instructionsPath, "utf8"));
  const rows = readExisting(historyCsv);
  let result;
  try {
    result = applyChanges(rows, instructions.edits || [], instructions.deletes || []);
  } catch (e) {
    console.error(`error: ${e.message}`);
    process.exit(1);
  }
  writeCsv(historyCsv, result.rows);
  const summary = {
    updated: result.updated,
    deleted: result.deleted,
    missing: result.missing,
    row_count: result.rows.length,
  };
  console.log(JSON.stringify(summary));
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main(process.argv.slice(2));
}
