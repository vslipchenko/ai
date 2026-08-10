// Deterministic CSV builder (Node fallback) (shared core) for the estimator plugin.
import { readFileSync, writeFileSync, existsSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { pathToFileURL } from "node:url";

export const HEADERS = [
  "Key (key)",
  "Parent (parent_key)",
  "Issue Type (issue_type)",
  "Title (summary)",
  "Description (description)",
  "Components (components)",
  "Labels (labels)",
  "Story Points (story_points)",
  "Time Spent [s] (time_spent_seconds)",
  "Resolution Date (resolution_date)",
  "Comments (comments)",
  "Design Link (design_link)",
  "Estimate Basis (estimate_basis)",
];

export const FIELD_KEYS = HEADERS.map((h) => h.match(/\(([^)]+)\)\s*$/)[1]);

export const MULTIVALUE_SEP = ", ";
export const COMMENT_SEP = "\n\n";

const s = (v) => (v === null || v === undefined ? "" : String(v));
const join = (v, sep) => {
  if (v === null || v === undefined || v === "" || (Array.isArray(v) && v.length === 0)) {
    return "";
  }
  return Array.isArray(v) ? v.map(String).join(sep) : String(v);
};

export function recordToRow(rec) {
  return [
    s(rec.key),
    s(rec.parent_key),
    s(rec.issue_type),
    s(rec.summary),
    s(rec.description),
    join(rec.components, MULTIVALUE_SEP),
    join(rec.labels, MULTIVALUE_SEP),
    s(rec.story_points),
    s(rec.time_spent_seconds),
    s(rec.resolution_date),
    join(rec.comments, COMMENT_SEP),
    s(rec.design_link),
    s(rec.estimate_basis),
  ];
}

export function formatField(value) {
  const v = value === null || value === undefined ? "" : String(value);
  return /[;"\n\r]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v;
}

export function formatRow(fields) {
  return fields.map(formatField).join(";");
}

export function parseCsv(text) {
  const rows = [];
  let row = [];
  let field = "";
  let inQuotes = false;
  let i = 0;
  while (i < text.length) {
    const ch = text[i];
    if (inQuotes) {
      if (ch === '"') {
        if (text[i + 1] === '"') { field += '"'; i += 2; continue; }
        inQuotes = false; i += 1; continue;
      }
      field += ch; i += 1; continue;
    }
    if (ch === '"') { inQuotes = true; i += 1; continue; }
    if (ch === ";") { row.push(field); field = ""; i += 1; continue; }
    if (ch === "\n" || ch === "\r") {
      if (ch === "\r" && text[i + 1] === "\n") i += 1;
      row.push(field); field = "";
      rows.push(row); row = [];
      i += 1; continue;
    }
    field += ch; i += 1;
  }
  if (field.length > 0 || row.length > 0) {
    row.push(field);
    rows.push(row);
  }
  return rows;
}

export function buildRows(existingRows, records, mode) {
  if (mode !== "overwrite" && mode !== "append") {
    throw new Error(`mode must be 'overwrite' or 'append', got: ${mode}`);
  }
  const merged = new Map();
  if (mode === "append" && existingRows) {
    for (const row of existingRows) {
      if (row && row.length) merged.set(row[0], row);
    }
  }
  for (const rec of records) {
    const row = recordToRow(rec);
    merged.set(row[0], row);
  }
  return [...merged.values()];
}

function normalize(row) {
  // Pad legacy rows that predate a column addition out to the header width.
  return row.length < HEADERS.length
    ? row.concat(Array(HEADERS.length - row.length).fill(""))
    : row;
}

export function readExisting(path) {
  if (!existsSync(path)) return [];
  const rows = parseCsv(readFileSync(path, "utf8"));
  return rows.length ? rows.slice(1).map(normalize) : [];
}

export function writeCsv(path, rows) {
  mkdirSync(dirname(resolve(path)), { recursive: true });
  const lines = [formatRow(HEADERS), ...rows.map(formatRow)];
  writeFileSync(path, lines.join("\n") + "\n", "utf8");
}

export function main(argv) {
  if (argv.length !== 3) {
    console.error("Usage: build_csv.mjs <input.json> <output.csv> <overwrite|append>");
    process.exit(1);
  }
  const [inputJson, outputCsv, mode] = argv;
  const records = JSON.parse(readFileSync(inputJson, "utf8"));
  const existing = mode === "append" ? readExisting(outputCsv) : [];
  const rows = buildRows(existing, records, mode);
  writeCsv(outputCsv, rows);
  console.log(`Wrote ${rows.length} rows to ${outputCsv}`);
  console.log(JSON.stringify({ row_count: rows.length }));
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main(process.argv.slice(2));
}
