import math
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import generate_password as gp

SCRIPT = Path(__file__).resolve().parent.parent / "generate_password.py"


class BuildCharsetTest(unittest.TestCase):
    def test_all_classes_by_default(self):
        classes = gp.build_charset(True, True, True, True, False)
        self.assertEqual(len(classes), 4)

    def test_no_classes_selected_exits(self):
        with self.assertRaises(SystemExit):
            gp.build_charset(False, False, False, False, False)

    def test_no_ambiguous_strips_confusable_chars(self):
        classes = gp.build_charset(True, True, True, False, True)
        joined = "".join(classes)
        for ch in "O0Il1":
            self.assertNotIn(ch, joined)

    def test_no_ambiguous_emptying_a_class_exits(self):
        original = gp.AMBIGUOUS
        gp.AMBIGUOUS = set(gp.DIGITS)
        try:
            with self.assertRaises(SystemExit):
                gp.build_charset(False, False, True, False, True)
        finally:
            gp.AMBIGUOUS = original


class GenPasswordTest(unittest.TestCase):
    def test_length_respected(self):
        classes = gp.build_charset(True, True, True, True, False)
        pw = gp.gen_password(16, classes)
        self.assertEqual(len(pw), 16)

    def test_covers_every_required_class(self):
        classes = gp.build_charset(True, True, True, True, False)
        pw = gp.gen_password(24, classes)
        for cls in classes:
            self.assertTrue(any(c in cls for c in pw))

    def test_single_class_still_works(self):
        classes = gp.build_charset(True, False, False, False, False)
        pw = gp.gen_password(10, classes)
        self.assertTrue(all(c in gp.LOWER for c in pw))


class EntropyTest(unittest.TestCase):
    def test_matches_log2_formula(self):
        self.assertAlmostEqual(gp.entropy_bits(10, 26), 10 * math.log2(26))


class PassphraseTest(unittest.TestCase):
    WORDLIST = ["apple", "banana", "cherry", "date"]

    def test_word_count_respected(self):
        phrase, _ = gp.gen_passphrase(5, self.WORDLIST, "-", False, False)
        self.assertEqual(len(phrase.split("-")), 5)

    def test_capitalize(self):
        phrase, _ = gp.gen_passphrase(3, self.WORDLIST, "-", True, False)
        for word in phrase.split("-"):
            self.assertTrue(word[0].isupper())

    def test_add_number_appends_digit_token(self):
        phrase, bits_with = gp.gen_passphrase(3, self.WORDLIST, "-", False, True)
        parts = phrase.split("-")
        self.assertEqual(len(parts), 4)
        self.assertTrue(parts[-1].isdigit())
        _, bits_without = gp.gen_passphrase(3, self.WORDLIST, "-", False, False)
        self.assertGreater(bits_with, bits_without)

    def test_entropy_scales_with_word_count(self):
        # gen_passphrase returns unrounded bits (rounding happens in main()),
        # so this can be exact.
        _, bits3 = gp.gen_passphrase(3, self.WORDLIST, "-", False, False)
        _, bits6 = gp.gen_passphrase(6, self.WORDLIST, "-", False, False)
        self.assertAlmostEqual(bits6, 2 * bits3)


class WordlistFileTest(unittest.TestCase):
    def test_bundled_wordlist_loads_and_has_no_duplicates(self):
        words = gp.load_wordlist(gp.DEFAULT_WORDLIST)
        self.assertEqual(len(words), 7776)
        self.assertEqual(len(set(words)), len(words))


class ClipboardCliTest(unittest.TestCase):
    def test_clipboard_with_count_gt_1_is_rejected(self):
        # --clipboard's happy path writes to the real OS clipboard, which
        # would clobber whatever the developer running this suite has
        # copied -- that side effect is exercised manually, not here.
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--mode", "password", "--count", "3", "--clipboard"],
            capture_output=True,
        )
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
