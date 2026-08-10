"""Scan / prune low-quality records in the estimator history CSV.

Reuses build_csv's parser/HEADERS/writer.
- detect <history.csv>: print {"prune":[{row,key,reasons}],"flag":[{row,key,warnings}]}
- apply <history.csv> <rows.json {"rows":[...]}>: delete those 1-based data rows,
  print {"deleted_rows":[...],"deleted_keys":[...],"row_count":N}
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
import build_csv  # noqa: E402

FIELD_KEYS = build_csv.FIELD_KEYS
COL = {fk: i for i, fk in enumerate(FIELD_KEYS)}
VALID_BASIS = {"actual", "final", "suggested"}


def _cell(row, fk):
    i = COL[fk]
    return row[i] if i < len(row) else ""


def _blank(value):
    return value is None or str(value).strip() == ""


_NUMBER_RE = re.compile(r"^\d+(\.\d+)?$")


def _is_number(value):
    return bool(_NUMBER_RE.match(str(value).strip()))


def detect(rows):
    prune = []
    flag = []
    for i, row in enumerate(rows, start=1):
        key = _cell(row, "key")
        reasons = []
        if _blank(key):
            reasons.append("missing key")
        if _blank(_cell(row, "summary")):
            reasons.append("missing summary")
        if not _is_number(_cell(row, "story_points")):
            reasons.append("missing/invalid story_points")
        if reasons:
            prune.append({"row": i, "key": key, "reasons": reasons})
            continue
        warnings = []
        if _cell(row, "estimate_basis").strip() not in VALID_BASIS:
            warnings.append("blank/invalid estimate_basis")
        if _blank(_cell(row, "issue_type")):
            warnings.append("missing issue_type")
        if warnings:
            flag.append({"row": i, "key": key, "warnings": warnings})
    return {"prune": prune, "flag": flag}


def apply_rows(rows, row_numbers):
    for n in row_numbers:
        if isinstance(n, bool) or not isinstance(n, int) or n < 1:
            raise ValueError("row numbers must be positive integers, got: %r" % (n,))
    delete_set = set(row_numbers)
    result = []
    deleted_rows = []
    deleted_keys = []
    for i, row in enumerate(rows, start=1):
        if i in delete_set:
            deleted_rows.append(i)
            deleted_keys.append(row[0] if row else "")
        else:
            result.append(row)
    return {"rows": result, "deleted_rows": deleted_rows, "deleted_keys": deleted_keys}


def _emit(obj):
    sys.stdout.buffer.write(
        (json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    )


def main(argv):
    # argv is sys.argv: argv[1] is mode, argv[2] is history.csv, argv[3] is rows.json
    if len(argv) < 3:
        sys.exit("Usage: prune_records.py <detect|apply> <history.csv> [rows.json]")
    mode, history_csv = argv[1], argv[2]
    rows = build_csv.read_existing(history_csv)
    if mode == "detect":
        _emit(detect(rows))
    elif mode == "apply":
        if len(argv) != 4:
            sys.exit("Usage: prune_records.py apply <history.csv> <rows.json>")
        with open(argv[3], encoding="utf-8") as f:
            row_numbers = json.load(f).get("rows") or []
        try:
            result = apply_rows(rows, row_numbers)
        except ValueError as e:
            sys.exit("error: %s" % e)
        build_csv.write_csv(history_csv, result["rows"])
        _emit({
            "deleted_rows": result["deleted_rows"],
            "deleted_keys": result["deleted_keys"],
            "row_count": len(result["rows"]),
        })
    else:
        sys.exit("unknown mode: %s" % mode)


if __name__ == "__main__":
    main(sys.argv)
