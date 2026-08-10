"""Deterministic CSV builder (shared core) for the estimator plugin.

Reads a JSON array of Jira ticket records and writes/merges them into the
global history CSV with delimiter-aware escaping and dedup-by-key.
"""

import csv
import json
import os
import re
import sys

HEADERS = [
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
]

FIELD_KEYS = [re.search(r"\(([^)]+)\)\s*$", h).group(1) for h in HEADERS]

MULTIVALUE_SEP = ", "
COMMENT_SEP = "\n\n"


def _str(value):
    return "" if value is None else str(value)


def _join(values, sep):
    if not values:
        return ""
    if isinstance(values, (list, tuple)):
        return sep.join(_str(v) for v in values)
    return _str(values)


def record_to_row(rec):
    return [
        _str(rec.get("key")),
        _str(rec.get("parent_key")),
        _str(rec.get("issue_type")),
        _str(rec.get("summary")),
        _str(rec.get("description")),
        _join(rec.get("components"), MULTIVALUE_SEP),
        _join(rec.get("labels"), MULTIVALUE_SEP),
        _str(rec.get("story_points")),
        _str(rec.get("time_spent_seconds")),
        _str(rec.get("resolution_date")),
        _join(rec.get("comments"), COMMENT_SEP),
        _str(rec.get("design_link")),
        _str(rec.get("estimate_basis")),
    ]


def build_rows(existing_rows, records, mode):
    if mode not in ("overwrite", "append"):
        raise ValueError("mode must be 'overwrite' or 'append', got: %r" % mode)
    merged = {}
    if mode == "append" and existing_rows:
        for row in existing_rows:
            if row:
                merged[row[0]] = row
    for rec in records:
        row = record_to_row(rec)
        merged[row[0]] = row
    return list(merged.values())


def _normalize(row):
    """Pad legacy rows that predate a column addition out to the header width."""
    if len(row) < len(HEADERS):
        return row + [""] * (len(HEADERS) - len(row))
    return row


def read_existing(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f, delimiter=";"))
    return [_normalize(r) for r in rows[1:]] if rows else []


def write_csv(path, rows):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(
            f, delimiter=";", quoting=csv.QUOTE_MINIMAL, lineterminator="\n"
        )
        writer.writerow(HEADERS)
        writer.writerows(rows)


def main(argv):
    if len(argv) != 4:
        sys.exit("Usage: build_csv.py <input.json> <output.csv> <overwrite|append>")
    input_json, output_csv, mode = argv[1], argv[2], argv[3]
    with open(input_json, encoding="utf-8") as f:
        records = json.load(f)
    existing = read_existing(output_csv) if mode == "append" else []
    rows = build_rows(existing, records, mode)
    write_csv(output_csv, rows)
    print("Wrote %d rows to %s" % (len(rows), output_csv))
    print(json.dumps({"row_count": len(rows)}, separators=(",", ":")))


if __name__ == "__main__":
    main(sys.argv)
