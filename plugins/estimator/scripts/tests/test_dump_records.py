import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))  # dump_records + build_csv share scripts/
import dump_records as dr  # noqa: E402
import build_csv as bc  # noqa: E402

RECS = [
    {"key": "K-1", "summary": "first", "story_points": 3, "estimate_basis": "actual"},
    {"key": "K-2", "summary": "two; semi", "description": 'a "q" and\nnl',
     "comments": ["c;1", "x"], "story_points": 5, "estimate_basis": "final"},
]


def _rows():
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "history.csv")
        bc.write_csv(out, bc.build_rows([], RECS, "overwrite"))
        return bc.read_existing(out)


class DumpTest(unittest.TestCase):
    def test_field_keys_match_schema(self):
        self.assertEqual(dr.FIELD_KEYS[0], "key")
        self.assertEqual(dr.FIELD_KEYS[-1], "estimate_basis")
        self.assertEqual(len(dr.FIELD_KEYS), len(bc.HEADERS))

    def test_dump_full_records_with_row(self):
        recs = dr.dump(_rows())
        self.assertEqual([r["row"] for r in recs], [1, 2])
        self.assertEqual(recs[0]["key"], "K-1")
        self.assertEqual(recs[0]["story_points"], "3")
        self.assertEqual(recs[0]["estimate_basis"], "actual")
        self.assertEqual(len(recs[0]), len(bc.HEADERS) + 1)  # fields + row

    def test_special_chars_preserved(self):
        recs = dr.dump(_rows())
        self.assertEqual(recs[1]["summary"], "two; semi")
        self.assertEqual(recs[1]["description"], 'a "q" and\nnl')
        self.assertEqual(recs[1]["comments"], "c;1\n\nx")

    def test_empty_history_is_empty_list(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "history.csv")
            with open(out, "w", newline="", encoding="utf-8") as f:
                f.write(";".join(bc.HEADERS) + "\n")
            self.assertEqual(dr.dump(bc.read_existing(out)), [])

    def test_legacy_12_col_row_padded(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "history.csv")
            with open(out, "w", newline="", encoding="utf-8") as f:
                f.write(";".join(bc.HEADERS[:12]) + "\n")
                f.write("LEG-1;;Story;t;;;;3;;2026-01-01;;\n")
            recs = dr.dump(bc.read_existing(out))
        self.assertEqual(recs[0]["row"], 1)
        self.assertEqual(recs[0]["estimate_basis"], "")

    def test_short_raw_row_fills_blanks(self):
        recs = dr.dump([["K-X"]])
        self.assertEqual(recs[0]["row"], 1)
        self.assertEqual(recs[0]["key"], "K-X")
        self.assertEqual(recs[0]["estimate_basis"], "")
        self.assertEqual(len(recs[0]), len(bc.HEADERS) + 1)


if __name__ == "__main__":
    unittest.main()
