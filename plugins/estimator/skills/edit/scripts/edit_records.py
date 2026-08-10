"""Edit or delete records in the estimator history CSV.

Reuses build_csv's parser/HEADERS/writer. Driven by an instructions file:
  {"edits": [{"key": "ABC-1", "fields": {"summary": "...", ...}}], "deletes": ["ABC-2"]}
Prints JSON: {"updated":[...],"deleted":[...],"missing":[...],"row_count":N}
`key` is read-only; unknown field names are rejected (validated before any change).
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "scripts"))
import build_csv  # noqa: E402

FIELD_KEYS = build_csv.FIELD_KEYS
COL = {fk: i for i, fk in enumerate(FIELD_KEYS)}


def _dedup(seq):
    seen = set()
    out = []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def apply_changes(rows, edits, deletes):
    # Validate everything before mutating, so a bad instruction changes nothing.
    for edit in edits:
        for fk in (edit.get("fields") or {}):
            if fk == "key":
                raise ValueError("'key' is read-only and cannot be edited")
            if fk not in COL:
                raise ValueError("unknown field: %r" % fk)
    edit_keys = {str(e.get("key", "")).strip().upper() for e in edits}
    delete_keys_set = {str(k).strip().upper() for k in deletes}
    overlap = (edit_keys & delete_keys_set) - {""}
    if overlap:
        raise ValueError("key(s) appear in both edits and deletes: %s" % ", ".join(sorted(overlap)))
    index = {}
    for row in rows:
        if row:
            index[row[0]] = row
    updated = []
    delete_keys = []
    missing = []
    for edit in edits:
        k = str(edit.get("key", "")).strip().upper()
        if not k:
            continue
        if k in index:
            row = index[k]
            for fk, val in (edit.get("fields") or {}).items():
                row[COL[fk]] = "" if val is None else str(val)
            updated.append(k)
        else:
            missing.append(k)
    for key in deletes:
        k = str(key).strip().upper()
        if not k:
            continue
        if k in index:
            delete_keys.append(k)
        else:
            missing.append(k)
    delete_set = set(delete_keys)
    result_rows = [row for row in rows if row and row[0] not in delete_set]
    return {
        "rows": result_rows,
        "updated": _dedup(updated),
        "deleted": _dedup(delete_keys),
        "missing": _dedup(missing),
    }


def main(argv):
    # argv is sys.argv: argv[0] is the script name, argv[1]/argv[2] are the args
    if len(argv) != 3:
        sys.exit("Usage: edit_records.py <history.csv> <instructions.json>")
    history_csv, instructions_path = argv[1], argv[2]
    with open(instructions_path, encoding="utf-8") as f:
        instructions = json.load(f)
    rows = build_csv.read_existing(history_csv)
    try:
        result = apply_changes(rows, instructions.get("edits") or [], instructions.get("deletes") or [])
    except ValueError as e:
        sys.exit("error: %s" % e)
    build_csv.write_csv(history_csv, result["rows"])
    summary = {
        "updated": result["updated"],
        "deleted": result["deleted"],
        "missing": result["missing"],
        "row_count": len(result["rows"]),
    }
    sys.stdout.buffer.write(
        (json.dumps(summary, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    )


if __name__ == "__main__":
    main(sys.argv)
