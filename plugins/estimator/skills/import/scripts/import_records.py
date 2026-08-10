"""Import an external history CSV into the estimator dataset (merge or replace).

Reuses build_csv's HEADERS/read_existing/write_csv. Header-aware: maps the
source's columns to canonical fields by the token in each header's trailing
parentheses, so reordered / 12-vs-13 / extra columns are tolerated.
Prints JSON: {"mode":...,"imported":N,"row_count":M,"project_keys":[...]}.
"""

import csv
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "scripts"))
import build_csv  # noqa: E402

FIELD_KEYS = build_csv.FIELD_KEYS
COL = {fk: i for i, fk in enumerate(FIELD_KEYS)}


def _header_map(header_row):
    mapping = {}
    for idx, cell in enumerate(header_row):
        m = re.search(r"\(([^)]+)\)\s*$", str(cell).strip())
        if m and m.group(1) in COL:
            # duplicate columns mapping to the same field: last occurrence wins
            mapping[m.group(1)] = idx
    return mapping


def map_source(parsed_rows):
    if not parsed_rows:
        raise ValueError("source is empty")
    header, data = parsed_rows[0], parsed_rows[1:]
    mapping = _header_map(header)
    if "key" not in mapping:
        raise ValueError(
            "source headers not recognized (no 'key' column); expected estimator history columns"
        )
    rows = []
    for row in data:
        if not row or all(str(c).strip() == "" for c in row):
            continue
        rows.append([
            row[mapping[fk]] if fk in mapping and mapping[fk] < len(row) else ""
            for fk in FIELD_KEYS
        ])
    return rows


def build_dataset(source_rows, target_rows, mode):
    if mode not in ("merge", "replace"):
        raise ValueError("mode must be 'merge' or 'replace', got: %r" % mode)
    # keys are matched verbatim (consistent with build_csv dedup)
    merged = {}
    if mode == "merge":
        for row in target_rows:
            if row:
                merged[row[0]] = row
    for row in source_rows:
        merged[row[0]] = row
    return list(merged.values())


def derive_project_keys(rows):
    prefixes = set()
    for row in rows:
        key = str(row[0]).strip() if row else ""
        if not key:
            continue
        prefixes.add(key.rsplit("-", 1)[0] if "-" in key else key)
    return sorted(prefixes)


def _emit(obj):
    sys.stdout.buffer.write(
        (json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    )


def main(argv):
    if len(argv) != 4:
        sys.exit("Usage: import_records.py <source.csv> <target.csv> <merge|replace>")
    source, target, mode = argv[1], argv[2], argv[3]
    with open(source, newline="", encoding="utf-8-sig") as f:
        parsed = list(csv.reader(f, delimiter=";"))
    try:
        source_rows = map_source(parsed)
        target_rows = build_csv.read_existing(target) if mode == "merge" else []
        result = build_dataset(source_rows, target_rows, mode)
    except ValueError as e:
        sys.exit("error: %s" % e)
    build_csv.write_csv(target, result)
    _emit({
        "mode": mode,
        "imported": len(source_rows),
        "row_count": len(result),
        "project_keys": derive_project_keys(result),
    })


if __name__ == "__main__":
    main(sys.argv)
