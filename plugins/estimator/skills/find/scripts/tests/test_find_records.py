import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, ".."))                          # find_records
sys.path.insert(0, os.path.join(HERE, "..", "..", "..", "..", "scripts"))  # build_csv

import find_records as fr  # noqa: E402
import build_csv as bc  # noqa: E402

RECS = [
    {"key": "K-1", "issue_type": "Story", "summary": "first",
     "story_points": 3, "estimate_basis": "actual"},
    {"key": "K-2", "issue_type": "Bug", "summary": "second",
     "comments": ["line1\nline2", "c;2"], "story_points": 5, "estimate_basis": "final"},
    {"key": "K-3", "issue_type": "Task", "summary": "third",
     "story_points": 8, "estimate_basis": "suggested"},
]


def _fixture_rows():
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "history.csv")
        bc.write_csv(out, bc.build_rows([], RECS, "overwrite"))
        return bc.read_existing(out)


class FindRecordsTest(unittest.TestCase):
    def test_field_keys_match_schema(self):
        self.assertEqual(fr.FIELD_KEYS[0], "key")
        self.assertEqual(fr.FIELD_KEYS[-1], "estimate_basis")
        self.assertEqual(len(fr.FIELD_KEYS), len(bc.HEADERS))

    def test_single_key_found_with_row(self):
        res = fr.find_records(_fixture_rows(), ["K-1"])
        self.assertEqual(res["missing"], [])
        self.assertEqual(len(res["found"]), 1)
        rec = res["found"][0]
        self.assertEqual(rec["row"], 1)
        self.assertEqual(rec["key"], "K-1")
        self.assertEqual(rec["story_points"], "3")
        self.assertEqual(rec["estimate_basis"], "actual")

    def test_multiple_keys_mixed_and_in_request_order(self):
        res = fr.find_records(_fixture_rows(), ["K-3", "k-1", "NOPE"])
        self.assertEqual([r["key"] for r in res["found"]], ["K-3", "K-1"])
        self.assertEqual([r["row"] for r in res["found"]], [3, 1])
        self.assertEqual(res["missing"], ["NOPE"])

    def test_multiline_comment_does_not_shift_rows(self):
        res = fr.find_records(_fixture_rows(), ["K-3"])
        self.assertEqual(res["found"][0]["row"], 3)

    def test_legacy_twelve_column_row_resolves_blank_basis(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "history.csv")
            with open(out, "w", newline="", encoding="utf-8") as f:
                f.write(";".join(bc.HEADERS[:12]) + "\n")
                f.write("LEG-1;;Story;old;;;;3;;2026-01-01;;\n")
            rows = bc.read_existing(out)
        res = fr.find_records(rows, ["LEG-1"])
        self.assertEqual(res["found"][0]["row"], 1)
        self.assertEqual(res["found"][0]["estimate_basis"], "")

    def test_duplicate_input_keys_return_multiple_entries(self):
        res = fr.find_records(_fixture_rows(), ["K-1", "K-1"])
        self.assertEqual(len(res["found"]), 2)
        self.assertEqual(res["missing"], [])

    def test_blank_keys_are_skipped(self):
        res = fr.find_records(_fixture_rows(), ["K-1", "   ", ""])
        self.assertEqual([r["key"] for r in res["found"]], ["K-1"])
        self.assertEqual(res["missing"], [])


if __name__ == "__main__":
    unittest.main()
