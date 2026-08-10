"""Query the estimator history CSV for records by Jira key.

Reuses build_csv's parser and HEADERS so the schema stays in sync. Prints JSON:
  {"found": [{"row": <1-based data-row index>, <field>: value, ...}], "missing": [...]}
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "scripts"))
import build_csv  # noqa: E402

FIELD_KEYS = build_csv.FIELD_KEYS


def find_records(rows, keys):
    # history.csv keys are unique (build_csv dedups on write); if a hand-edited
    # file ever has duplicate keys, the last occurrence wins (newest is appended last).
    index = {}
    for i, row in enumerate(rows, start=1):
        if row:
            index[row[0]] = (i, row)
    found = []
    missing = []
    for key in keys:
        k = key.strip().upper()
        if not k:
            continue
        if k in index:
            i, row = index[k]
            record = {"row": i}
            record.update({fk: (row[j] if j < len(row) else "") for j, fk in enumerate(FIELD_KEYS)})
            found.append(record)
        else:
            missing.append(k)
    return {"found": found, "missing": missing}


def main(argv):
    if len(argv) < 3:
        sys.exit("Usage: find_records.py <history.csv> <KEY> [KEY ...]")
    history_csv, keys = argv[1], argv[2:]
    rows = build_csv.read_existing(history_csv)
    result = find_records(rows, keys)
    out = json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n"
    sys.stdout.buffer.write(out.encode("utf-8"))


if __name__ == "__main__":
    main(sys.argv)
