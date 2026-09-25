import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
SECRET = SCRIPTS / "secret.py"
BOARD = SCRIPTS / "leaderboard.py"
LISTS = SCRIPTS.parent / "references" / "secrets"


class HomeTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def run_script(self, script, *args):
        env = {**os.environ, "AKINATOR_HOME": str(self.home)}
        out = subprocess.run(
            [sys.executable, str(script), *args],
            capture_output=True, text=True, encoding="utf-8", env=env, check=True,
        )
        return json.loads(out.stdout)

    def record(self, **extra):
        base = {"mode": "claude-guesses", "limit": "25", "secret": "x", "domain": "animal", "date": "2026-09-25"}
        flags = [part for k, v in {**base, **extra}.items() for part in (f"--{k}", str(v))]
        return self.run_script(BOARD, "record", *flags)


class SecretTest(HomeTestCase):
    def test_commit_prints_hash_but_not_secret(self):
        out = self.run_script(SECRET, "commit", "--domain", "animal")
        state = json.loads((self.home / "secret.json").read_text(encoding="utf-8"))
        self.assertEqual(out["hash"], state["hash"])
        self.assertNotIn(state["secret"], json.dumps(out))
        animals = (LISTS / "animals.txt").read_text(encoding="utf-8").splitlines()
        self.assertIn(state["secret"], animals)

    def test_reveal_verifies_commitment_and_clears_state(self):
        committed = self.run_script(SECRET, "commit", "--domain", "character")
        out = self.run_script(SECRET, "reveal")
        self.assertEqual(out["hash"], committed["hash"])
        self.assertTrue(out["verified"])
        self.assertEqual(hashlib.sha256(out["preimage"].encode("utf-8")).hexdigest(), committed["hash"])
        self.assertEqual(out["preimage"], f"{out['salt']}:{out['secret']}")
        self.assertFalse((self.home / "secret.json").exists())
        recent = json.loads((self.home / "recent.json").read_text(encoding="utf-8"))
        self.assertEqual(recent["character"], [out["secret"]])

    def test_commitments_are_salted(self):
        hashes = {self.run_script(SECRET, "commit", "--domain", "object")["hash"] for _ in range(5)}
        self.assertEqual(len(hashes), 5)

    def test_recent_secrets_not_repeated(self):
        seen = []
        for _ in range(10):
            self.run_script(SECRET, "commit", "--domain", "animal")
            seen.append(self.run_script(SECRET, "reveal")["secret"])
        self.assertEqual(len(set(seen)), 10)

    def test_extension_list_merged_deduplicated(self):
        bundled = [w for w in (LISTS / "animals.txt").read_text(encoding="utf-8").splitlines() if w]
        (self.home / "secrets").mkdir()
        (self.home / "secrets" / "animals.txt").write_text("# my animals\ntest-only-creature\n\nDOG\ntest-only-creature\n", encoding="utf-8")
        out = self.run_script(SECRET, "commit", "--domain", "animal")
        self.assertEqual(out["custom_entries"], 1)
        self.assertEqual(out["pool_size"], len(bundled) + 1)

    def test_extension_entries_can_be_picked(self):
        bundled = [w for w in (LISTS / "animals.txt").read_text(encoding="utf-8").splitlines() if w]
        (self.home / "secrets").mkdir()
        (self.home / "secrets" / "animals.txt").write_text("test-only-creature\n", encoding="utf-8")
        (self.home / "recent.json").write_text(json.dumps({"animal": bundled}), encoding="utf-8")
        self.run_script(SECRET, "commit", "--domain", "animal")
        self.assertEqual(self.run_script(SECRET, "reveal")["secret"], "test-only-creature")

    def test_errors(self):
        with self.assertRaises(subprocess.CalledProcessError):
            self.run_script(SECRET, "reveal")
        with self.assertRaises(subprocess.CalledProcessError):
            self.run_script(SECRET, "commit", "--domain", "planet")


class LeaderboardTest(HomeTestCase):
    def test_first_run_is_best_and_worst(self):
        out = self.record(questions=12, outcome="guessed")
        self.assertEqual(out["board"], "claude-guesses/25")
        self.assertTrue(out["new_best"])
        self.assertTrue(out["new_worst"])

    def test_claude_guesses_ranking(self):
        self.record(questions=12, outcome="guessed")
        self.assertTrue(self.record(questions=20, outcome="guessed")["new_best"])
        self.assertTrue(self.record(questions=5, outcome="guessed")["new_worst"])
        out = self.record(questions=8, outcome="not-guessed")
        self.assertTrue(out["new_best"])
        self.assertEqual(out["best"]["outcome"], "not-guessed")
        self.assertEqual(out["worst"]["questions"], 5)

    def test_user_guesses_ranking(self):
        mode = "user-guesses"
        self.record(mode=mode, questions=15, outcome="guessed")
        self.assertTrue(self.record(mode=mode, questions=9, outcome="guessed")["new_best"])
        self.assertTrue(self.record(mode=mode, questions=3, outcome="not-guessed")["new_worst"])
        out = self.record(mode=mode, questions=10, outcome="not-guessed")
        self.assertFalse(out["new_worst"])
        self.assertEqual(out["best"]["questions"], 9)
        self.assertEqual(out["worst"]["questions"], 3)

    def test_ties_keep_earlier_run(self):
        self.record(secret="first", questions=10, outcome="guessed")
        out = self.record(secret="second", questions=10, outcome="guessed")
        self.assertFalse(out["new_best"])
        self.assertFalse(out["new_worst"])
        self.assertEqual(out["best"]["secret"], "first")

    def test_boards_separate_and_show_filters(self):
        self.record(limit="20", questions=10, outcome="guessed")
        self.record(limit="none", questions=40, outcome="guessed", note="2 answers didn't fit")
        self.record(mode="user-guesses", questions=7, outcome="guessed")
        self.assertEqual(sorted(self.run_script(BOARD, "show")),
                         ["claude-guesses/20", "claude-guesses/none", "user-guesses/25"])
        none = self.run_script(BOARD, "show", "--limit", "none")
        self.assertEqual(none["claude-guesses/none"]["best"]["note"], "2 answers didn't fit")
        self.assertEqual(list(self.run_script(BOARD, "show", "--mode", "user-guesses")), ["user-guesses/25"])

    def test_rejects_invalid_counts(self):
        for extra in ({"limit": "20", "questions": 21}, {"questions": 0}):
            with self.assertRaises(subprocess.CalledProcessError):
                self.record(outcome="guessed", **extra)
        with self.assertRaises(subprocess.CalledProcessError):
            self.record(questions=5, outcome="won")


if __name__ == "__main__":
    unittest.main()
