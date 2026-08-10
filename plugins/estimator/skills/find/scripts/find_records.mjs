// Query the estimator history CSV for records by Jira key.
// Reuses build_csv's parser/HEADERS; prints {"found":[{row,...fields}],"missing":[...]}.
import { HEADERS, FIELD_KEYS as _FIELD_KEYS, readExisting } from "../../../scripts/build_csv.mjs";
import { pathToFileURL } from "node:url";

export const FIELD_KEYS = _FIELD_KEYS;

export function findRecords(rows, keys) {
  // history.csv keys are unique (build_csv dedups on write); if a hand-edited
  // file ever has duplicate keys, the last occurrence wins (newest is appended last).
  const index = new Map();
  rows.forEach((row, i) => {
    if (row && row.length) index.set(row[0], [i + 1, row]);
  });
  const found = [];
  const missing = [];
  for (const key of keys) {
    const k = key.trim().toUpperCase();
    if (!k) continue;
    if (index.has(k)) {
      const [rowNum, row] = index.get(k);
      const record = { row: rowNum };
      FIELD_KEYS.forEach((fk, j) => { record[fk] = row[j] ?? ""; });
      found.push(record);
    } else {
      missing.push(k);
    }
  }
  return { found, missing };
}

export function main(argv) {
  if (argv.length < 2) {
    console.error("Usage: find_records.mjs <history.csv> <KEY> [KEY ...]");
    process.exit(1);
  }
  const [historyCsv, ...keys] = argv;
  const rows = readExisting(historyCsv);
  console.log(JSON.stringify(findRecords(rows, keys)));
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main(process.argv.slice(2));
}
