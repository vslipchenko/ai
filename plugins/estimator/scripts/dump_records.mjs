// Dump the estimator history CSV as a JSON array of record objects.
// Reuses build_csv's reader/HEADERS. Each record: {"row":N, <field>:value, ...}.
// Usage: dump_records.mjs <history.csv>
import { HEADERS, FIELD_KEYS as _FIELD_KEYS, readExisting } from "./build_csv.mjs";
import { pathToFileURL } from "node:url";

export const FIELD_KEYS = _FIELD_KEYS;

export function dump(rows) {
  const out = [];
  rows.forEach((row, idx) => {
    if (!row || !row.length) return;
    const rec = { row: idx + 1 };
    FIELD_KEYS.forEach((fk, j) => { rec[fk] = row[j] ?? ""; });
    out.push(rec);
  });
  return out;
}

export function main(argv) {
  if (argv.length !== 1) {
    console.error("Usage: dump_records.mjs <history.csv>");
    process.exit(1);
  }
  console.log(JSON.stringify(dump(readExisting(argv[0]))));
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main(process.argv.slice(2));
}
