import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, ".."))                          # edit_records
sys.path.insert(0, os.path.join(HERE, "..", "..", "..", "..", "scripts"))  # build_csv

import edit_records as er  # noqa: E402
import build_csv as bc  # noqa: E402

RECS = [
    {"key": "K-1", "issue_type": "Story", "summary": "first", "story_points": 3, "estimate_basis": "actual"},
    {"key": "K-2", "issue_type": "Bug", "summary": "second", "comments": ["a\nb"], "story_points": 5, "estimate_basis": "final"},
    {"key": "K-3", "issue_type": "Task", "summary": "third", "story_points": 8, "estimate_basis": "suggested"},
]
COL = {fk: i for i, fk in enumerate(er.FIELD_KEYS)}


def _rows():
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "history.csv")
        bc.write_csv(out, bc.build_rows([], RECS, "overwrite"))
        return bc.read_existing(out)


class ApplyChangesTest(unittest.TestCase):
    def test_edit_single_field(self):
        res = er.apply_changes(_rows(), [{"key": "K-1", "fields": {"summary": "changed"}}], [])
        self.assertEqual(res["updated"], ["K-1"])
        self.assertEqual(res["deleted"], [])
        self.assertEqual(res["missing"], [])
        self.assertEqual([r[0] for r in res["rows"]], ["K-1", "K-2", "K-3"])
        self.assertEqual(res["rows"][0][COL["summary"]], "changed")

    def test_edit_multiple_fields_per_record(self):
        res = er.apply_changes(_rows(), [
            {"key": "K-1", "fields": {"summary": "s1", "story_points": "13"}},
            {"key": "K-2", "fields": {"estimate_basis": "actual"}},
        ], [])
        self.assertEqual(res["updated"], ["K-1", "K-2"])
        self.assertEqual(res["rows"][0][COL["summary"]], "s1")
        self.assertEqual(res["rows"][0][COL["story_points"]], "13")
        self.assertEqual(res["rows"][1][COL["estimate_basis"]], "actual")

    def test_delete_preserves_order(self):
        res = er.apply_changes(_rows(), [], ["K-2"])
        self.assertEqual(res["deleted"], ["K-2"])
        self.assertEqual([r[0] for r in res["rows"]], ["K-1", "K-3"])

    def test_missing_keys_reported(self):
        res = er.apply_changes(_rows(), [{"key": "NOPE", "fields": {"summary": "x"}}], ["GONE"])
        self.assertEqual(res["updated"], [])
        self.assertEqual(res["deleted"], [])
        self.assertEqual(res["missing"], ["NOPE", "GONE"])
        self.assertEqual(len(res["rows"]), 3)

    def test_edit_key_field_raises(self):
        with self.assertRaises(ValueError):
            er.apply_changes(_rows(), [{"key": "K-1", "fields": {"key": "X-9"}}], [])

    def test_unknown_field_raises(self):
        with self.assertRaises(ValueError):
            er.apply_changes(_rows(), [{"key": "K-1", "fields": {"bogus": "x"}}], [])

    def test_combined_edit_and_delete(self):
        res = er.apply_changes(_rows(), [{"key": "k-1", "fields": {"summary": "z"}}], ["K-3"])
        self.assertEqual(res["updated"], ["K-1"])
        self.assertEqual(res["deleted"], ["K-3"])
        self.assertEqual([r[0] for r in res["rows"]], ["K-1", "K-2"])
        self.assertEqual(res["rows"][0][COL["summary"]], "z")

    def test_key_in_both_edits_and_deletes_raises(self):
        with self.assertRaises(ValueError):
            er.apply_changes(_rows(), [{"key": "K-1", "fields": {"summary": "x"}}], ["K-1"])

    def test_blank_keys_skipped(self):
        res = er.apply_changes(_rows(), [{"key": "  ", "fields": {"summary": "x"}}], ["  "])
        self.assertEqual(res["updated"], [])
        self.assertEqual(res["deleted"], [])
        self.assertEqual(res["missing"], [])
        self.assertEqual(len(res["rows"]), 3)

    def test_duplicate_edit_keys_last_wins(self):
        res = er.apply_changes(_rows(), [
            {"key": "K-1", "fields": {"summary": "a"}},
            {"key": "K-1", "fields": {"summary": "b"}},
        ], [])
        self.assertEqual(res["updated"], ["K-1"])
        self.assertEqual(res["rows"][0][COL["summary"]], "b")

    def test_empty_fields_counts_as_updated_no_change(self):
        res = er.apply_changes(_rows(), [{"key": "K-1", "fields": {}}], [])
        self.assertEqual(res["updated"], ["K-1"])
        self.assertEqual(res["rows"][0][COL["summary"]], "first")

    def test_null_field_value_becomes_blank(self):
        res = er.apply_changes(_rows(), [{"key": "K-1", "fields": {"summary": None}}], [])
        self.assertEqual(res["rows"][0][COL["summary"]], "")


class MainTest(unittest.TestCase):
    def test_main_writes_file_and_legacy_upgrade(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "history.csv")
            with open(out, "w", newline="", encoding="utf-8") as f:
                f.write(";".join(bc.HEADERS[:12]) + "\n")
                f.write("LEG-1;;Story;old;;;;3;;2026-01-01;;\n")
                f.write("LEG-2;;Bug;two;;;;5;;2026-01-02;;\n")
            instr = os.path.join(d, "i.json")
            with open(instr, "w", encoding="utf-8") as f:
                json.dump({"edits": [{"key": "LEG-1", "fields": {"estimate_basis": "final"}}],
                           "deletes": ["LEG-2"]}, f)
            er.main(["edit_records.py", out, instr])
            rows = bc.read_existing(out)
        self.assertEqual([r[0] for r in rows], ["LEG-1"])
        self.assertTrue(all(len(r) == 13 for r in rows))
        self.assertEqual(rows[0][COL["estimate_basis"]], "final")


if __name__ == "__main__":
    unittest.main()
