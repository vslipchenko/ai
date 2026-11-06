import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, ".."))                                  # import_records
sys.path.insert(0, os.path.join(HERE, "..", "..", "..", "..", "scripts"))   # build_csv

import import_records as ir  # noqa: E402
import build_csv as bc  # noqa: E402


class MapSourceTest(unittest.TestCase):
    def test_reordered_and_unknown_columns(self):
        header = ["Key (key)", "Bogus (bogus)", "Title (summary)", "Story Points (story_points)"]
        data = ["K-1", "junk", "hello", "5"]
        rows = ir.map_source([header, data])
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(rows[0]), len(bc.HEADERS))
        self.assertEqual(rows[0][0], "K-1")
        self.assertEqual(rows[0][3], "hello")
        self.assertEqual(rows[0][7], "5")
        self.assertEqual(rows[0][1], "")
        self.assertEqual(rows[0][12], "")

    def test_legacy_12_col_source(self):
        header = bc.HEADERS[:12]
        data = ["K-1", "", "Story", "title", "", "", "", "3", "", "2026-01-01", "", ""]
        rows = ir.map_source([header, data])
        self.assertEqual(rows[0][0], "K-1")
        self.assertEqual(rows[0][12], "")

    def test_no_key_column_raises(self):
        with self.assertRaises(ValueError):
            ir.map_source([["Title (summary)", "Story Points (story_points)"], ["hello", "5"]])

    def test_skips_all_blank_rows(self):
        header = list(bc.HEADERS)
        blank = [""] * 13
        keep = ["K-2"] + [""] * 12
        rows = ir.map_source([header, blank, keep])
        self.assertEqual([r[0] for r in rows], ["K-2"])

    def test_header_only_source_imports_nothing(self):
        self.assertEqual(ir.map_source([list(bc.HEADERS)]), [])


class BuildDatasetTest(unittest.TestCase):
    def test_replace_uses_source_only(self):
        res = ir.build_dataset([["S-1"] + [""] * 12], [["T-1"] + [""] * 12], "replace")
        self.assertEqual([r[0] for r in res], ["S-1"])

    def test_merge_imported_wins_and_order(self):
        target = [["A-1", "", "", "old"] + [""] * 9, ["A-2"] + [""] * 12]
        source = [["A-3"] + [""] * 12, ["A-1", "", "", "new"] + [""] * 9]
        res = ir.build_dataset(source, target, "merge")
        self.assertEqual([r[0] for r in res], ["A-1", "A-2", "A-3"])
        self.assertEqual(res[0][3], "new")

    def test_invalid_mode_raises(self):
        with self.assertRaises(ValueError):
            ir.build_dataset([], [], "append")

    def test_replace_dedups_source_internal_duplicates_last_wins(self):
        source = [["X-1", "", "", "a"] + [""] * 9, ["X-1", "", "", "b"] + [""] * 9]
        res = ir.build_dataset(source, [], "replace")
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0][3], "b")


class DeriveProjectKeysTest(unittest.TestCase):
    def test_distinct_sorted_prefixes_skip_blank(self):
        rows = [["ABC-7"] + [""] * 12, ["ABC-8"] + [""] * 12, ["CORE-1"] + [""] * 12, [""] + [""] * 12]
        self.assertEqual(ir.derive_project_keys(rows), ["ABC", "CORE"])


class MainTest(unittest.TestCase):
    def test_main_replace_writes_target(self):
        with tempfile.TemporaryDirectory() as d:
            source = os.path.join(d, "src.csv")
            with open(source, "w", newline="", encoding="utf-8") as f:
                f.write(";".join(bc.HEADERS) + "\n")
                f.write("ABC-1;;Story;t;;;;3;;2026-01-01;;actual\n")
            target = os.path.join(d, "history.csv")
            ir.main(["import_records.py", source, target, "replace"])
            rows = bc.read_existing(target)
        self.assertEqual([r[0] for r in rows], ["ABC-1"])
        self.assertTrue(all(len(r) == 13 for r in rows))

    def test_main_merge_combines(self):
        with tempfile.TemporaryDirectory() as d:
            target = os.path.join(d, "history.csv")
            bc.write_csv(target, bc.build_rows([], [{"key": "OLD-1", "summary": "keep"}], "overwrite"))
            source = os.path.join(d, "src.csv")
            with open(source, "w", newline="", encoding="utf-8") as f:
                f.write(";".join(bc.HEADERS) + "\n")
                f.write("NEW-1;;Story;t;;;;3;;;;actual\n")
            ir.main(["import_records.py", source, target, "merge"])
            rows = bc.read_existing(target)
        self.assertEqual([r[0] for r in rows], ["OLD-1", "NEW-1"])


class BomTest(unittest.TestCase):
    def test_source_with_bom_imports_correctly(self):
        with tempfile.TemporaryDirectory() as d:
            source = os.path.join(d, "bom_src.csv")
            # Write a UTF-8 BOM followed by the header and one data row
            with open(source, "wb") as f:
                f.write(b"\xef\xbb\xbf")  # UTF-8 BOM
                f.write((";".join(bc.HEADERS) + "\n").encode("utf-8"))
                f.write(b"BOM-1;;Story;t;;;;3;;2026-01-01;;actual\n")
            target = os.path.join(d, "history.csv")
            ir.main(["import_records.py", source, target, "replace"])
            rows = bc.read_existing(target)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "BOM-1")


if __name__ == "__main__":
    unittest.main()
