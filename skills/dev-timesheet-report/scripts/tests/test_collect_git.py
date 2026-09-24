import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import collect_git as cg  # noqa: E402

US = "\x1f"
RS = "\x1e"


class ParseIsoTest(unittest.TestCase):
    def test_positive_offset_round_trips(self):
        dt = cg.parse_iso("2026-09-22T09:14:03+03:00")
        self.assertEqual(dt.isoformat(), "2026-09-22T09:14:03+03:00")

    def test_negative_offset_keeps_its_sign(self):
        dt = cg.parse_iso("2026-09-22T23:30:00-07:00")
        self.assertEqual(dt.isoformat(), "2026-09-22T23:30:00-07:00")

    def test_bare_z_is_utc(self):
        dt = cg.parse_iso("2026-01-02T03:04:05Z")
        self.assertEqual(dt.isoformat(), "2026-01-02T03:04:05+00:00")

    def test_garbage_raises_rather_than_guessing(self):
        with self.assertRaises(ValueError):
            cg.parse_iso("last tuesday")


class RenderTest(unittest.TestCase):
    def test_commit_tz_renders_the_wall_clock_the_developer_saw(self):
        # 23:30-07:00 is 06:30 UTC the NEXT day; the commit's own day is the 22nd.
        dt = cg.parse_iso("2026-09-22T23:30:00-07:00")
        self.assertEqual(cg.render(dt, "commit"), ("2026-09-22", "23:30"))


class TicketPatternTest(unittest.TestCase):
    def test_prefixes_restrict_matching_to_real_project_keys(self):
        pattern = cg.build_ticket_pattern(["ABC", "OPS"], None)
        self.assertEqual(
            cg.extract_tickets(pattern, "ABC-12 bump to UTF-8 and SHA-256 for OPS-7"),
            ["ABC-12", "OPS-7"],
        )

    def test_generic_pattern_is_the_one_that_mistakes_utf_8_for_a_ticket(self):
        # Documents exactly why configuring project keys matters.
        pattern = cg.build_ticket_pattern([], None)
        self.assertEqual(cg.extract_tickets(pattern, "bump to UTF-8"), ["UTF-8"])

    def test_ids_are_upper_cased_and_deduped_in_first_seen_order(self):
        pattern = cg.build_ticket_pattern(["abc"], None)
        self.assertEqual(
            cg.extract_tickets(pattern, "abc-9 again ABC-9 then Abc-4"), ["ABC-9", "ABC-4"]
        )

    def test_ids_are_collected_across_subject_body_and_branch(self):
        pattern = cg.build_ticket_pattern(["ABC"], None)
        self.assertEqual(
            cg.extract_tickets(pattern, "fix login", "refs ABC-2", "feature/ABC-1-login"),
            ["ABC-2", "ABC-1"],
        )

    def test_explicit_pattern_overrides_the_prefix_list(self):
        pattern = cg.build_ticket_pattern(["ABC"], r"TASK_\d+")
        self.assertEqual(cg.extract_tickets(pattern, "ABC-1 and TASK_99"), ["TASK_99"])


class ShortBranchTest(unittest.TestCase):
    def test_refs_are_stripped_to_a_readable_name(self):
        self.assertEqual(cg.short_branch("refs/heads/feature/ABC-1"), "feature/ABC-1")
        self.assertEqual(cg.short_branch("refs/remotes/origin/main"), "origin/main")

    def test_bare_sha_or_head_is_not_a_branch(self):
        self.assertIsNone(cg.short_branch("9f3c1ab9f3c1ab9f3c1ab9f3c1ab9f3c1ab9f3c1"))
        self.assertIsNone(cg.short_branch("HEAD"))
        self.assertIsNone(cg.short_branch(""))


class ParseLogTest(unittest.TestCase):
    def test_subjects_with_commas_and_quotes_survive(self):
        raw = US.join(
            [
                "sha1",
                "sha1s",
                "2026-09-22T09:14:03+03:00",
                "Dev",
                "d@x.io",
                "refs/heads/main",
                'ABC-1 fix "login", again',
                "body",
            ]
        ) + RS
        self.assertEqual(cg.parse_log(raw)[0][6], 'ABC-1 fix "login", again')

    def test_trailing_blank_record_is_ignored(self):
        one = US.join(list("abcdefgh")) + RS
        self.assertEqual(len(cg.parse_log(one + "\n")), 1)

    def test_short_record_is_padded_rather_than_raising(self):
        record = cg.parse_log(US.join(["a", "b"]) + RS)[0]
        self.assertEqual(len(record), 8)
        self.assertEqual(record[7], "")


class ExpandUserTest(unittest.TestCase):
    def test_a_leading_tilde_expands_in_repo_and_output_paths(self):
        home = os.path.expanduser("~")
        self.assertEqual(cg.expand_user("~"), home)
        self.assertTrue(cg.expand_user("~/work/api").startswith(home))
        self.assertEqual(cg.expand_user("~someone/x"), "~someone/x")
        self.assertEqual(cg.expand_user("/abs/repo"), "/abs/repo")


class PadTest(unittest.TestCase):
    def test_padding_crosses_month_and_year_boundaries(self):
        self.assertEqual(cg.pad("2026-03-01", -7), "2026-02-22")
        self.assertEqual(cg.pad("2026-12-31", 1), "2027-01-01")


class DedupeTest(unittest.TestCase):
    def test_same_repo_twice_collapses_but_a_cherry_pick_elsewhere_stays(self):
        a = {"repo": "web", "ref": "abc1234", "timestamp": "2026-09-22T09:14:03+03:00"}
        b = {"repo": "api", "ref": "abc1234", "timestamp": "2026-09-22T09:14:03+03:00"}
        self.assertEqual(len(cg.dedupe([a, dict(a), b])), 2)


class ParserTest(unittest.TestCase):
    def test_repeatable_flags_accumulate(self):
        opts = cg.build_parser().parse_args(
            [
                "--repo", "a", "--repo", "b",
                "--since", "2026-09-01", "--until", "2026-09-07",
                "--author", "dev@x.io", "--ticket-prefix", "ABC",
            ]
        )
        self.assertEqual(opts.repo, ["a", "b"])
        self.assertEqual(opts.author, ["dev@x.io"])
        self.assertEqual(opts.ticket_prefix, ["ABC"])
        self.assertEqual(opts.tz, "commit")
        self.assertTrue(opts.all_branches)

    def test_local_branches_flag_turns_off_all_refs(self):
        opts = cg.build_parser().parse_args(
            ["--repo", "a", "--since", "2026-09-01", "--until", "2026-09-07", "--local-branches"]
        )
        self.assertFalse(opts.all_branches)


if __name__ == "__main__":
    unittest.main()
