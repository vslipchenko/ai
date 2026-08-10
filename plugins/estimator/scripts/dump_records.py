"""Dump the estimator history CSV as a JSON array of record objects.

Reuses build_csv's reader/HEADERS. Each record: {"row": <1-based>, <field>: value, ...}.
Usage: dump_records.py <history.csv>
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))  # build_csv is in the same dir
import build_csv  # noqa: E402

FIELD_KEYS = build_csv.FIELD_KEYS


def dump(rows):
    out = []
    for i, row in enumerate(rows, start=1):
        if not row:
            continue
        rec = {"row": i}
        for j, fk in enumerate(FIELD_KEYS):
            rec[fk] = row[j] if j < len(row) else ""
        out.append(rec)
    return out


def main(argv):
    if len(argv) != 2:
        sys.exit("Usage: dump_records.py <history.csv>")
    rows = build_csv.read_existing(argv[1])
    sys.stdout.buffer.write(
        (json.dumps(dump(rows), ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    )


if __name__ == "__main__":
    main(sys.argv)
