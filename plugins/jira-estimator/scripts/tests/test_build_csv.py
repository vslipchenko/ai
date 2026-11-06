import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import build_csv as bc  # noqa: E402


class RecordToRowTest(unittest.TestCase):
    def test_headers_have_thirteen_columns(self):
        self.assertEqual(len(bc.HEADERS), 13)
        self.assertEqual(bc.HEADERS[0], "Key (key)")
        self.assertEqual(bc.HEADERS[1], "Parent (parent_key)")
        self.assertEqual(bc.HEADERS[-1], "Estimate Basis (estimate_basis)")

    def test_full_record_maps_in_header_order(self):
        rec = {
            "key": "PROJ-1",
            "parent_key": "PROJ-100",
            "issue_type": "Story",
            "summary": "Add login",
            "description": "Desc",
            "components": ["Backend", "Frontend"],
            "labels": ["auth", "mvp"],
            "story_points": 5,
            "time_spent_seconds": 14400,
            "resolution_date": "2026-01-15",
            "comments": ["first", "second"],
            "design_link": "https://figma.com/x",
            "estimate_basis": "actual",
        }
        self.assertEqual(
            bc.record_to_row(rec),
            [
                "PROJ-1", "PROJ-100", "Story", "Add login", "Desc",
                "Backend, Frontend", "auth, mvp", "5", "14400",
                "2026-01-15", "first\n\nsecond", "https://figma.com/x", "actual",
            ],
        )

    def test_missing_optional_fields_are_blank(self):
        row = bc.record_to_row({"key": "PROJ-2"})
        self.assertEqual(len(row), 13)
        self.assertEqual(row[0], "PROJ-2")
        self.assertTrue(all(cell == "" for cell in row[1:]))


class BuildRowsTest(unittest.TestCase):
    def _rec(self, key, summary="s"):
        return {"key": key, "summary": summary}

    def test_overwrite_ignores_existing(self):
        existing = [["OLD-1"] + [""] * 11]
        rows = bc.build_rows(existing, [self._rec("NEW-1")], "overwrite")
        self.assertEqual([r[0] for r in rows], ["NEW-1"])

    def test_append_merges_existing_then_new(self):
        existing = [["OLD-1"] + [""] * 11]
        rows = bc.build_rows(existing, [self._rec("NEW-1")], "append")
        self.assertEqual([r[0] for r in rows], ["OLD-1", "NEW-1"])

    def test_append_new_record_overrides_same_key(self):
        existing = [["PROJ-1", "", "", "old title"] + [""] * 8]
        rows = bc.build_rows(existing, [self._rec("PROJ-1", "new title")], "append")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][3], "new title")

    def test_dedup_within_records_last_wins(self):
        recs = [self._rec("PROJ-1", "first"), self._rec("PROJ-1", "second")]
        rows = bc.build_rows([], recs, "overwrite")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][3], "second")


class RoundTripTest(unittest.TestCase):
    def test_special_chars_survive_write_then_read(self):
        rec = {
            "key": "PROJ-9",
            "summary": "has ; semicolon",
            "description": 'a "quote" and\na newline',
            "components": ["A", "B"],
            "comments": ["c;1", "line\nbreak"],
        }
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "sub", "history.csv")
            bc.write_csv(out, bc.build_rows([], [rec], "overwrite"))
            rows = bc.read_existing(out)  # header dropped
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "PROJ-9")
        self.assertEqual(rows[0][3], "has ; semicolon")
        self.assertEqual(rows[0][4], 'a "quote" and\na newline')
        self.assertEqual(rows[0][5], "A, B")
        self.assertEqual(rows[0][10], "c;1\n\nline\nbreak")

    def test_read_existing_missing_file_returns_empty(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(bc.read_existing(os.path.join(d, "none.csv")), [])

    def test_main_appends_via_cli(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "history.csv")
            bc.write_csv(out, bc.build_rows([], [{"key": "OLD-1"}], "overwrite"))
            inp = os.path.join(d, "in.json")
            with open(inp, "w", encoding="utf-8") as f:
                json.dump([{"key": "NEW-1"}], f)
            bc.main(["build_csv.py", inp, out, "append"])
            rows = bc.read_existing(out)
        self.assertEqual([r[0] for r in rows], ["OLD-1", "NEW-1"])

    def test_append_pads_legacy_twelve_column_rows(self):
        # A CSV written before the estimate_basis column existed: 12 fields.
        legacy = "LEG-1;;Story;old;;;;3;;2026-01-01;;\n"
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "history.csv")
            with open(out, "w", newline="", encoding="utf-8") as f:
                f.write(";".join(bc.HEADERS[:12]) + "\n")
                f.write(legacy)
            rows = bc.build_rows(
                bc.read_existing(out),
                [{"key": "NEW-1", "estimate_basis": "final"}],
                "append",
            )
            bc.write_csv(out, rows)
            result = bc.read_existing(out)
        self.assertEqual([r[0] for r in result], ["LEG-1", "NEW-1"])
        self.assertTrue(all(len(r) == 13 for r in result))
        self.assertEqual(result[0][12], "")        # legacy row: blank basis
        self.assertEqual(result[1][12], "final")    # new row: basis set


class ModeValidationTest(unittest.TestCase):
    def test_invalid_mode_raises(self):
        with self.assertRaises(ValueError):
            bc.build_rows([], [{"key": "X-1"}], "merge")


class JoinScalarTest(unittest.TestCase):
    def test_string_scalar_for_array_field_not_char_split(self):
        row = bc.record_to_row({"key": "K-1", "components": "Backend"})
        self.assertEqual(row[5], "Backend")

    def test_string_scalar_comments_not_char_split(self):
        row = bc.record_to_row({"key": "K-1", "comments": "one comment"})
        self.assertEqual(row[10], "one comment")

    def test_empty_array_is_blank(self):
        row = bc.record_to_row({"key": "K-1", "components": []})
        self.assertEqual(row[5], "")


if __name__ == "__main__":
    unittest.main()
