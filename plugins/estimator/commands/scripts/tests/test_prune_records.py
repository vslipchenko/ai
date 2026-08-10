import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, ".."))                                  # prune_records
sys.path.insert(0, os.path.join(HERE, "..", "..", "..", "scripts"))  # build_csv

import prune_records as pr  # noqa: E402
import build_csv as bc  # noqa: E402

RECS = [
    {"key": "K-1", "summary": "good", "story_points": 3, "issue_type": "Story", "estimate_basis": "actual"},
    {"key": "K-2", "summary": "no points", "issue_type": "Bug", "estimate_basis": "final"},
    {"key": "K-3", "story_points": 5, "issue_type": "Task", "estimate_basis": "actual"},
    {"key": "K-4", "summary": "flag me", "story_points": 8, "issue_type": "Story"},
    {"key": "", "summary": "orphan", "story_points": 2, "issue_type": "Story", "estimate_basis": "actual"},
    {"key": "K-6", "summary": "bad pts", "story_points": "abc", "issue_type": "Story", "estimate_basis": "actual"},
]


def _rows():
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "history.csv")
        bc.write_csv(out, bc.build_rows([], RECS, "overwrite"))
        return bc.read_existing(out)


class DetectTest(unittest.TestCase):
    def test_classifies_prune_and_flag(self):
        res = pr.detect(_rows())
        prune = {p["row"]: p for p in res["prune"]}
        flag = {f["row"]: f for f in res["flag"]}
        self.assertEqual(sorted(prune), [2, 3, 5, 6])
        self.assertEqual(sorted(flag), [4])
        self.assertEqual(prune[2]["reasons"], ["missing/invalid story_points"])
        self.assertEqual(prune[2]["key"], "K-2")
        self.assertEqual(prune[3]["reasons"], ["missing summary"])
        self.assertEqual(prune[5]["reasons"], ["missing key"])
        self.assertEqual(prune[5]["key"], "")
        self.assertEqual(prune[6]["reasons"], ["missing/invalid story_points"])
        self.assertEqual(flag[4]["warnings"], ["blank/invalid estimate_basis"])

    def test_clean_row_in_neither(self):
        res = pr.detect(_rows())
        listed = {p["row"] for p in res["prune"]} | {f["row"] for f in res["flag"]}
        self.assertNotIn(1, listed)

    def test_prune_supersedes_flag(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "history.csv")
            bc.write_csv(out, bc.build_rows([], [{"key": "X-1", "story_points": 3}], "overwrite"))
            rows = bc.read_existing(out)
        res = pr.detect(rows)
        self.assertEqual([p["row"] for p in res["prune"]], [1])
        self.assertEqual(res["flag"], [])

    def test_story_points_numeric_definition(self):
        def prune_rows(sp):
            with tempfile.TemporaryDirectory() as d:
                out = os.path.join(d, "h.csv")
                bc.write_csv(out, bc.build_rows([], [{"key": "K", "summary": "s", "story_points": sp, "issue_type": "Story", "estimate_basis": "actual"}], "overwrite"))
                return [p["row"] for p in pr.detect(bc.read_existing(out))["prune"]]
        self.assertEqual(prune_rows("0"), [])      # zero is valid
        self.assertEqual(prune_rows("8.0"), [])    # decimal is valid
        self.assertEqual(prune_rows("inf"), [1])   # rejected
        self.assertEqual(prune_rows("nan"), [1])   # rejected
        self.assertEqual(prune_rows("1e3"), [1])   # rejected

    def test_header_only_csv_is_clean(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "h.csv")
            with open(out, "w", newline="", encoding="utf-8") as f:
                f.write(";".join(bc.HEADERS) + "\n")
            res = pr.detect(bc.read_existing(out))
        self.assertEqual(res, {"prune": [], "flag": []})

    def test_legacy_twelve_column_row_flagged_for_blank_basis(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "history.csv")
            with open(out, "w", newline="", encoding="utf-8") as f:
                f.write(";".join(bc.HEADERS[:12]) + "\n")
                f.write("LEG-1;;Story;has title;;;;3;;2026-01-01;;\n")
            rows = bc.read_existing(out)
        res = pr.detect(rows)
        self.assertEqual(res["prune"], [])
        self.assertEqual([f["row"] for f in res["flag"]], [1])
        self.assertIn("blank/invalid estimate_basis", res["flag"][0]["warnings"])


class ApplyRowsTest(unittest.TestCase):
    def test_deletes_by_row_number_incl_keyless(self):
        rows = _rows()
        res = pr.apply_rows(rows, [2, 5])
        self.assertEqual(res["deleted_rows"], [2, 5])
        self.assertEqual(res["deleted_keys"], ["K-2", ""])
        self.assertEqual([r[0] for r in res["rows"]], ["K-1", "K-3", "K-4", "K-6"])

    def test_out_of_range_and_empty_are_noops(self):
        rows = _rows()
        self.assertEqual(pr.apply_rows(rows, [99])["deleted_rows"], [])
        self.assertEqual(len(pr.apply_rows(rows, [])["rows"]), len(rows))

    def test_dedupes_duplicate_row_numbers(self):
        res = pr.apply_rows(_rows(), [2, 2])
        self.assertEqual(res["deleted_rows"], [2])

    def test_rejects_invalid_row_numbers(self):
        with self.assertRaises(ValueError):
            pr.apply_rows(_rows(), [0])
        with self.assertRaises(ValueError):
            pr.apply_rows(_rows(), [-1])
        with self.assertRaises(ValueError):
            pr.apply_rows(_rows(), [1.5])


class MainTest(unittest.TestCase):
    def test_main_apply_writes_file(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "history.csv")
            bc.write_csv(out, bc.build_rows([], RECS, "overwrite"))
            rows_json = os.path.join(d, "rows.json")
            with open(rows_json, "w", encoding="utf-8") as f:
                json.dump({"rows": [2, 3, 5, 6]}, f)
            pr.main(["prune_records.py", "apply", out, rows_json])
            rows = bc.read_existing(out)
        self.assertEqual([r[0] for r in rows], ["K-1", "K-4"])


if __name__ == "__main__":
    unittest.main()
