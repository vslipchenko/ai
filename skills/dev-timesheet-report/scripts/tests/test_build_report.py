import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import build_report as br  # noqa: E402


def noop(_message):
    pass


class Collector(object):
    """A warn() that records what it was told, so tests can assert on it."""

    def __init__(self):
        self.seen = []

    def __call__(self, message):
        self.seen.append(message)


def commit(**over):
    event = {
        "date": "2026-09-22",
        "time": "09:14",
        "source": "local-git",
        "type": "commit",
        "repo": "web",
        "ticket_ids": ["ABC-1"],
        "subject": "ABC-1 add login",
        "url": "",
    }
    event.update(over)
    return event


RULES = [
    {"label": "Code Review", "when": {"type": ["pr_review", "pr_comment"]}},
    {"label": "Bug Fixing", "when": {"type": "commit", "subject_matches": r"^(fix|hotfix)\b"}},
    {"label": "Coding", "when": {"type": "commit"}},
]

DEFAULT_COLUMNS = ["date", "day", "item_type", "id", "title", "activity"]

# Layout tests drop the Type column so the expected boxes stay readable.
LAYOUT_COLUMNS = ["date", "day", "id", "title", "activity"]

TWO_DAYS = [
    {"date": "2026-09-22", "id": "ABC-1", "title": "Add login", "activity": "Coding"},
    {"date": "2026-09-23", "id": "ABC-2", "title": "Review", "activity": "Code Review"},
]


class ExpandUserTest(unittest.TestCase):
    def test_a_leading_tilde_expands_to_the_home_directory(self):
        # Matters for paths that never pass through a shell: output.csv_path in
        # the config file, and repo paths typed into setup.
        home = os.path.expanduser("~")
        self.assertEqual(br.expand_user("~"), home)
        expanded = br.expand_user("~/reports/sept.csv")
        self.assertTrue(expanded.startswith(home))
        self.assertNotIn("~", expanded)
        self.assertTrue(expanded.endswith("sept.csv"))

    def test_tilde_other_user_is_left_alone_so_both_twins_agree(self):
        # os.path.expanduser would resolve this; Node cannot, so neither do we.
        self.assertEqual(br.expand_user("~someone/x"), "~someone/x")

    def test_ordinary_paths_and_empty_values_pass_through(self):
        self.assertEqual(br.expand_user("reports/sept.csv"), "reports/sept.csv")
        self.assertEqual(br.expand_user("/abs/path.csv"), "/abs/path.csv")
        self.assertEqual(br.expand_user("a~b.csv"), "a~b.csv")
        self.assertEqual(br.expand_user(""), "")
        self.assertIsNone(br.expand_user(None))


class WeekdayTest(unittest.TestCase):
    def test_names_every_day_of_one_known_week(self):
        # 2026-09-21 is a Monday.
        week = [
            "2026-09-21", "2026-09-22", "2026-09-23", "2026-09-24",
            "2026-09-25", "2026-09-26", "2026-09-27",
        ]
        self.assertEqual(
            [br.weekday(d) for d in week],
            ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        )

    def test_is_unaffected_by_the_machine_timezone(self):
        self.assertEqual(br.weekday("2026-01-01"), "Thu")
        self.assertEqual(br.weekday("2026-12-31"), "Thu")

    def test_non_dates_return_empty_rather_than_a_wrong_day(self):
        self.assertEqual(br.weekday(""), "")
        self.assertEqual(br.weekday("(no ticket)"), "")
        self.assertEqual(br.weekday(None), "")
        self.assertEqual(br.weekday("2026-02-31"), "")


class EarliestTest(unittest.TestCase):
    def test_empty_times_are_unknown_not_midnight(self):
        self.assertEqual(br.earliest("", "09:14"), "09:14")
        self.assertEqual(br.earliest("11:00", "09:14"), "09:14")
        self.assertEqual(br.earliest("", ""), "")


class MatchRuleTest(unittest.TestCase):
    def test_a_condition_matches_any_value_in_its_list(self):
        self.assertTrue(
            br.match_rule(commit(type="pr_review"), {"type": ["pr_review", "pr_comment"]}, noop)
        )

    def test_conditions_and_together(self):
        when = {"type": "commit", "repo": "api"}
        self.assertFalse(br.match_rule(commit(), when, noop))
        self.assertTrue(br.match_rule(commit(repo="api"), when, noop))

    def test_subject_matches_is_a_case_insensitive_regex(self):
        self.assertTrue(br.match_rule(commit(subject="FIX login"), {"subject_matches": "^fix"}, noop))

    def test_a_list_field_matches_if_any_element_matches(self):
        event = commit(ticket_ids=["ABC-1", "OPS-9"])
        self.assertTrue(br.match_rule(event, {"ticket_ids": "ops-9"}, noop))

    def test_unrecognized_condition_warns_instead_of_matching_everything(self):
        warn = Collector()
        self.assertFalse(br.match_rule(commit(), {"titel": "x"}, warn))
        self.assertIn("not a recognized field", warn.seen[0])


class LabelForTest(unittest.TestCase):
    def test_first_matching_rule_wins(self):
        # Bug Fixing must be ordered before the generic commit rule to be reachable.
        self.assertEqual(br.label_for(commit(subject="fix login loop"), RULES, "Other", noop), "Bug Fixing")
        self.assertEqual(br.label_for(commit(), RULES, "Other", noop), "Coding")

    def test_explicit_activity_beats_every_rule(self):
        self.assertEqual(
            br.label_for(commit(activity="Investigation"), RULES, "Other", noop), "Investigation"
        )

    def test_no_matching_rule_falls_back_to_the_default(self):
        self.assertEqual(br.label_for(commit(type="deploy"), RULES, "Other", noop), "Other")


DROP_RULES = [
    {"drop": True, "when": {"type": ["jira_assigned", "jira_worklog"]}},
    {"drop": True, "when": {"type": "jira_transition", "status_to": ["Done", "Closed"]}},
    {"label": "Coding", "when": {"type": ["commit", "jira_transition"]}},
]


# The two rule sets setup generates, differing only in how QA statuses are
# handled. Ordering is what makes them work, so both are pinned here.
NO_QA_TEAM = [
    {"drop": True, "when": {"type": "jira_transition", "status_to": ["Done", "Closed"]}},
    {"label": "Testing", "when": {"type": "jira_transition", "status_to": ["In Testing", "QA"]}},
    {"label": "Coding", "when": {"type": ["commit", "jira_transition"]}},
]

DEDICATED_QA_TEAM = [
    {"drop": True, "when": {"type": "jira_transition", "status_to": ["Done", "Closed"]}},
    {"drop": True, "when": {"type": "jira_transition", "status_to": ["In Testing", "QA"]}},
    {"label": "Coding", "when": {"type": ["commit", "jira_transition"]}},
]


def to_qa():
    return commit(type="jira_transition", status_to="In Testing")


class DropRuleTest(unittest.TestCase):
    def test_a_drop_rule_suppresses_instead_of_labelling(self):
        self.assertIsNone(br.label_for(commit(type="jira_assigned"), DROP_RULES, "Other", noop))

    def test_drop_is_decided_by_first_match_like_any_other_rule(self):
        # -> Done is dropped; -> In Progress falls through to the Coding rule.
        done = commit(type="jira_transition", status_to="Done")
        wip = commit(type="jira_transition", status_to="In Progress")
        self.assertIsNone(br.label_for(done, DROP_RULES, "Other", noop))
        self.assertEqual(br.label_for(wip, DROP_RULES, "Other", noop), "Coding")

    def test_an_explicit_activity_beats_a_drop_rule(self):
        event = commit(type="jira_assigned", activity="Planning")
        self.assertEqual(br.label_for(event, DROP_RULES, "Other", noop), "Planning")

    def test_dropped_events_produce_no_rows(self):
        events = [commit(type="jira_assigned"), commit(type="jira_worklog"), commit()]
        rows = br.expand(events, {"activity_rules": DROP_RULES}, noop)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["activity"], "Coding")

    def test_a_bookkeeping_only_day_yields_an_empty_report(self):
        events = [commit(type="jira_assigned"), commit(type="jira_worklog")]
        rows = br.group(br.expand(events, {"activity_rules": DROP_RULES}, noop), False, {}, "-")
        self.assertEqual(rows, [])

    def test_without_dedicated_qa_a_move_to_qa_is_the_devs_own_testing(self):
        self.assertEqual(br.label_for(to_qa(), NO_QA_TEAM, "Other", noop), "Testing")

    def test_with_dedicated_qa_a_move_to_qa_is_a_handoff_and_is_dropped(self):
        self.assertIsNone(br.label_for(to_qa(), DEDICATED_QA_TEAM, "Other", noop))

    def test_deleting_the_testing_rule_instead_of_converting_mislabels_it(self):
        # Guards the one silent failure of the dedicated-QA setup path: with the
        # rule merely removed, QA statuses fall through to the Coding catch-all.
        deleted = [r for r in NO_QA_TEAM if r.get("label") != "Testing"]
        self.assertEqual(br.label_for(to_qa(), deleted, "Other", noop), "Coding")
        self.assertIsNone(br.label_for(to_qa(), DEDICATED_QA_TEAM, "Other", noop))

    def test_either_qa_setup_still_labels_working_transitions_as_coding(self):
        wip = commit(type="jira_transition", status_to="In Progress")
        self.assertEqual(br.label_for(wip, NO_QA_TEAM, "Other", noop), "Coding")
        self.assertEqual(br.label_for(wip, DEDICATED_QA_TEAM, "Other", noop), "Coding")

    def test_a_rule_with_neither_label_nor_drop_warns(self):
        warn = Collector()
        self.assertEqual(
            br.label_for(commit(), [{"when": {"type": "commit"}}], "Other", warn), "Other"
        )
        self.assertIn("neither a label nor drop", warn.seen[0])


class ExpandTest(unittest.TestCase):
    def test_an_event_with_no_date_is_dropped_and_reported(self):
        warn = Collector()
        events = [commit(date=None), commit(date=""), commit()]
        rows = br.expand(events, {"activity_rules": RULES}, warn)
        self.assertEqual(len(rows), 1)
        self.assertIn("dropped 2 event(s) with a missing or malformed date", warn.seen[0])

    def test_a_malformed_date_is_dropped_since_dates_sort_as_strings(self):
        # "22/09/2026" would sort before every ISO date and reorder the report.
        warn = Collector()
        rows = br.expand([commit(date="22/09/2026"), commit()], {"activity_rules": RULES}, warn)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["date"], "2026-09-22")
        self.assertIn("malformed date", warn.seen[0])

    def test_a_date_that_looks_real_but_is_not_gets_dropped(self):
        warn = Collector()
        rows = br.expand([commit(date="2026-02-31")], {"activity_rules": RULES}, warn)
        self.assertEqual(rows, [])

    def test_valid_dates_produce_no_warning(self):
        warn = Collector()
        br.expand([commit(), commit(date="2026-12-31")], {"activity_rules": RULES}, warn)
        self.assertEqual(warn.seen, [])

    def test_an_event_touching_two_tickets_becomes_two_rows(self):
        rows = br.expand([commit(ticket_ids=["ABC-1", "ABC-2"])], {"activity_rules": RULES}, noop)
        self.assertEqual([r["id"] for r in rows], ["ABC-1", "ABC-2"])

    def test_untracked_include_keeps_ticketless_work_under_a_placeholder(self):
        rows = br.expand([commit(ticket_ids=[])], {"activity_rules": RULES}, noop)
        self.assertEqual(rows[0]["id"], "(no ticket)")

    def test_untracked_omit_drops_ticketless_work(self):
        config = {"activity_rules": RULES, "output": {"untracked": "omit"}}
        self.assertEqual(br.expand([commit(ticket_ids=[])], config, noop), [])

    def test_untracked_group_collapses_strays_per_date_and_activity(self):
        config = {"activity_rules": RULES, "output": {"untracked": "group"}}
        events = [
            commit(ticket_ids=[], time="11:00"),
            commit(ticket_ids=[], time="09:14"),
            commit(ticket_ids=[], date="2026-09-23"),
        ]
        rows = br.expand(events, config, noop)
        self.assertEqual(len(rows), 2)
        first = [r for r in rows if r["date"] == "2026-09-22"][0]
        self.assertEqual(first["time"], "09:14")

    def test_invalid_untracked_mode_warns_and_falls_back_to_include(self):
        warn = Collector()
        rows = br.expand([commit(ticket_ids=[])], {"output": {"untracked": "maybe"}}, warn)
        self.assertEqual(len(rows), 1)
        self.assertIn("include/omit/group", warn.seen[0])


def page(**over):
    event = {
        "date": "2026-09-22",
        "time": "13:20",
        "source": "confluence",
        "type": "confluence_updated",
        "item_type": "confluence",
        "ticket_ids": ["393217"],
        "subject": "RFC: auth redesign",
        "url": "https://acme.atlassian.net/wiki/spaces/ENG/pages/393217",
    }
    event.update(over)
    return event


class ItemTypeTest(unittest.TestCase):
    def test_events_default_to_jira_so_existing_sources_are_unaffected(self):
        rows = br.expand([commit()], {"activity_rules": RULES}, noop)
        self.assertEqual(rows[0]["item_type"], "Jira")

    def test_a_commit_is_jira_because_its_id_is_a_jira_key(self):
        # The Type column describes what the Id refers to, not where the
        # evidence came from -- `source` carries that.
        rows = br.group(br.expand([commit()], {"activity_rules": RULES}, noop), False, {}, "-")
        self.assertEqual(rows[0]["item_type"], "Jira")
        self.assertEqual(rows[0]["source"], "local-git")

    def test_a_confluence_event_carries_its_type_page_id_and_url(self):
        rows = br.group(
            br.expand([page()], {"activity_rules": [{"label": "Documentation", "when": {}}]}, noop),
            False,
            {"393217": "RFC: auth redesign"},
            "-",
        )
        self.assertEqual(rows[0]["item_type"], "Confluence")
        self.assertEqual(rows[0]["id"], "393217")
        self.assertEqual(rows[0]["title"], "RFC: auth redesign")
        self.assertEqual(rows[0]["url"], "https://acme.atlassian.net/wiki/spaces/ENG/pages/393217")

    def test_an_untracked_row_has_no_item_type(self):
        rows = br.expand([commit(ticket_ids=[])], {"activity_rules": RULES}, noop)
        self.assertEqual(rows[0]["item_type"], "")

    def test_an_unknown_item_type_is_capitalized_rather_than_dropped(self):
        rows = br.expand([commit(item_type="linear")], {"activity_rules": RULES}, noop)
        self.assertEqual(rows[0]["item_type"], "Linear")

    def test_jira_rows_sort_before_confluence_rows_within_a_day(self):
        # Without a type rank, numeric page ids sort before ABC-123 keys purely
        # because digits precede letters.
        rows = br.group(
            br.expand([page(), commit()], {"activity_rules": [{"label": "Doc", "when": {}}]}, noop),
            False,
            {},
            "-",
        )
        self.assertEqual(
            ["%s %s" % (r["item_type"], r["id"]) for r in rows],
            ["Jira ABC-1", "Confluence 393217"],
        )

    def test_a_jira_key_and_a_page_id_that_look_alike_never_merge(self):
        events = [commit(ticket_ids=["123"]), page(ticket_ids=["123"])]
        rows = br.group(
            br.expand(events, {"activity_rules": [{"label": "X", "when": {}}]}, noop), False, {}, "-"
        )
        self.assertEqual(len(rows), 2)


class GroupTest(unittest.TestCase):
    def test_without_include_time_a_days_commits_collapse_to_one_line(self):
        rows = br.group(
            br.expand([commit(time="09:14"), commit(time="16:02")], {"activity_rules": RULES}, noop),
            False,
            {"ABC-1": "Add login"},
            "(title unavailable)",
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["evidence"], 2)
        self.assertEqual(rows[0]["time"], "09:14")

    def test_with_include_time_each_event_stays_separate(self):
        rows = br.group(
            br.expand([commit(time="09:14"), commit(time="16:02")], {"activity_rules": RULES}, noop),
            True,
            {},
            "(title unavailable)",
        )
        self.assertEqual(len(rows), 2)

    def test_different_activities_on_one_ticket_stay_separate(self):
        events = [commit(), commit(type="pr_review", subject="review ABC-1")]
        rows = br.group(br.expand(events, {"activity_rules": RULES}, noop), False, {}, "-")
        self.assertEqual([r["activity"] for r in rows], ["Code Review", "Coding"])

    def test_every_row_carries_its_day_name(self):
        rows = br.group(br.expand([commit()], {"activity_rules": RULES}, noop), False, {}, "-")
        self.assertEqual(rows[0]["day"], "Tue")

    def test_missing_title_gets_the_placeholder(self):
        rows = br.group(br.expand([commit()], {"activity_rules": RULES}, noop), False, {}, "(title unavailable)")
        self.assertEqual(rows[0]["title"], "(title unavailable)")

    def test_ticketless_row_falls_back_to_the_commit_subject(self):
        events = [commit(ticket_ids=[], subject="chore: bump deps")]
        rows = br.group(br.expand(events, {"activity_rules": RULES}, noop), False, {}, "(title unavailable)")
        self.assertEqual(rows[0]["id"], "(no ticket)")
        self.assertEqual(rows[0]["title"], "chore: bump deps")

    def test_a_known_title_beats_the_subject_fallback(self):
        rows = br.group(
            br.expand([commit()], {"activity_rules": RULES}, noop),
            False,
            {"ABC-1": "Add login"},
            "(title unavailable)",
        )
        self.assertEqual(rows[0]["title"], "Add login")

    def test_ticket_type_comes_through_and_is_empty_when_absent(self):
        with_type = br.expand([commit(ticket_type="Bug")], {"activity_rules": RULES}, noop)
        without = br.expand([commit()], {"activity_rules": RULES}, noop)
        self.assertEqual(with_type[0]["ticket_type"], "Bug")
        self.assertEqual(without[0]["ticket_type"], "")

    def test_a_merged_row_takes_the_issue_type_from_whichever_event_knew_it(self):
        # Only board events carry an issue type; commits on the same ticket do not.
        events = [
            commit(subject="ABC-1 fix it"),
            commit(type="jira_transition", source="jira", ticket_type="Bug"),
        ]
        rows = br.group(
            br.expand(events, {"activity_rules": [{"label": "Coding", "when": {}}]}, noop),
            False,
            {},
            "-",
        )
        self.assertEqual(len(rows), 1, "the untyped commit must not split the ticket-day")
        self.assertEqual(rows[0]["ticket_type"], "Bug")
        self.assertEqual(rows[0]["evidence"], 2)

    def test_issue_type_is_not_part_of_the_grouping_key(self):
        events = [commit(), commit(ticket_type="Story"), commit(ticket_type="")]
        rows = br.group(
            br.expand(events, {"activity_rules": [{"label": "Coding", "when": {}}]}, noop),
            False,
            {},
            "-",
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["ticket_type"], "Story")

    def test_confluence_rows_carry_page_as_their_type(self):
        rows = br.group(
            br.expand(
                [page(ticket_type="Page")], {"activity_rules": [{"label": "Doc", "when": {}}]}, noop
            ),
            False,
            {},
            "-",
        )
        self.assertEqual(rows[0]["item_type"], "Confluence")
        self.assertEqual(rows[0]["ticket_type"], "Page")

    def test_merged_rows_list_every_contributing_source_and_repo(self):
        events = [commit(), commit(source="github", repo="api", type="pr_review")]
        config = {"activity_rules": [{"label": "Coding", "when": {}}]}
        rows = br.group(br.expand(events, config, noop), False, {}, "-")
        self.assertEqual(rows[0]["source"], "local-git, github")
        self.assertEqual(rows[0]["repo"], "web, api")

    def test_rows_sort_by_date_then_ticket(self):
        events = [
            commit(date="2026-09-23", ticket_ids=["ABC-9"]),
            commit(date="2026-09-22", ticket_ids=["ABC-4"]),
            commit(date="2026-09-22", ticket_ids=["ABC-2"]),
        ]
        rows = br.group(br.expand(events, {"activity_rules": RULES}, noop), False, {}, "-")
        self.assertEqual(
            ["%s %s" % (r["date"], r["id"]) for r in rows],
            ["2026-09-22 ABC-2", "2026-09-22 ABC-4", "2026-09-23 ABC-9"],
        )


class CsvTest(unittest.TestCase):
    def test_quoting_follows_rfc_4180(self):
        self.assertEqual(br.csv_cell("plain"), "plain")
        self.assertEqual(br.csv_cell("a,b"), '"a,b"')
        self.assertEqual(br.csv_cell('say "hi"'), '"say ""hi"""')
        self.assertEqual(br.csv_cell("two\nlines"), '"two\nlines"')

    def test_a_title_with_a_comma_survives_the_round_trip(self):
        rows = [
            {
                "date": "2026-09-22",
                "id": "ABC-1",
                "title": "Fix login, again",
                "activity": "Coding",
            }
        ]
        csv = br.render_csv(rows, ["date", "id", "title", "activity"])
        self.assertEqual(csv.split("\n")[0], "Date,Id,Title,Activity")
        self.assertEqual(csv.split("\n")[1], '2026-09-22,ABC-1,"Fix login, again",Coding')


class TerminalTest(unittest.TestCase):
    def test_titles_truncate_with_an_ascii_ellipsis(self):
        self.assertEqual(br.truncate("abcdefghij", 8), "abcde...")
        self.assertEqual(br.truncate("short", 60), "short")
        self.assertEqual(br.truncate("abcdef", 0), "abcdef")

    def test_grid_draws_a_boxed_table_per_day_closed_top_and_bottom(self):
        text = br.render_terminal(TWO_DAYS[:1], LAYOUT_COLUMNS, 60, None, False, True, True, "grid")
        self.assertEqual(
            text.rstrip("\n").split("\n"),
            [
                "2026-09-22 (Tue)",
                "+-------+-----------+----------+",
                "| Id    | Title     | Activity |",
                "+-------+-----------+----------+",
                "| ABC-1 | Add login | Coding   |",
                "+-------+-----------+----------+",
            ],
        )

    def test_grid_repeats_the_header_under_every_date_group(self):
        text = br.render_terminal(TWO_DAYS, LAYOUT_COLUMNS, 60, None, False, True, True, "grid")
        self.assertEqual(text.count("| Id"), 2)
        self.assertIn("2026-09-22 (Tue)", text)
        self.assertIn("2026-09-23 (Wed)", text)

    def test_grid_column_widths_are_shared_across_days(self):
        rows = [
            {"date": "2026-09-22", "id": "ABC-1", "title": "short", "activity": "Coding"},
            {
                "date": "2026-09-23",
                "id": "ABC-2",
                "title": "a much longer title here",
                "activity": "Coding",
            },
        ]
        text = br.render_terminal(rows, LAYOUT_COLUMNS, 60, None, False, True, True, "grid")
        borders = [l for l in text.split("\n") if l.startswith("+")]
        self.assertEqual(len(set(borders)), 1)

    def test_grid_without_a_header_still_boxes_the_rows(self):
        text = br.render_terminal(TWO_DAYS[:1], LAYOUT_COLUMNS, 60, None, False, True, False, "grid")
        self.assertEqual(
            text.rstrip("\n").split("\n"),
            [
                "2026-09-22 (Tue)",
                "+-------+-----------+----------+",
                "| ABC-1 | Add login | Coding   |",
                "+-------+-----------+----------+",
            ],
        )

    def test_plain_groups_by_date_without_repeating_it(self):
        text = br.render_terminal(TWO_DAYS, LAYOUT_COLUMNS, 60, None, False, False, False, "plain")
        lines = text.rstrip("\n").split("\n")
        self.assertEqual(lines[0], "2026-09-22")
        # Columns pad to the widest of header and values ("Id" is 2 wide, so ABC-1 sets it).
        self.assertEqual(lines[1], "  ABC-1  Add login  Coding")
        self.assertEqual(lines[2], "")
        self.assertEqual(lines[3], "2026-09-23")
        self.assertEqual(lines[4], "  ABC-2  Review     Code Review")

    def test_the_date_heading_carries_the_day_name(self):
        text = br.render_terminal(TWO_DAYS[:1], LAYOUT_COLUMNS, 60, None, False, True, False, "plain")
        self.assertEqual(text.rstrip("\n").split("\n")[0], "2026-09-22 (Tue)")

    def test_the_day_name_can_be_turned_off(self):
        text = br.render_terminal(TWO_DAYS[:1], LAYOUT_COLUMNS, 60, None, False, False, False, "plain")
        self.assertEqual(text.rstrip("\n").split("\n")[0], "2026-09-22")

    def test_plain_puts_one_header_row_above_the_first_date_group(self):
        text = br.render_terminal(TWO_DAYS[:1], LAYOUT_COLUMNS, 60, None, False, True, True, "plain")
        lines = text.rstrip("\n").split("\n")
        self.assertEqual(lines[0], "  Id     Title      Activity")
        self.assertEqual(lines[1], "  -----  ---------  --------")
        self.assertEqual(lines[2], "")
        self.assertEqual(lines[3], "2026-09-22 (Tue)")
        self.assertEqual(lines[4], "  ABC-1  Add login  Coding")

    def test_plain_prints_the_header_once_not_per_date_group(self):
        text = br.render_terminal(TWO_DAYS, LAYOUT_COLUMNS, 60, None, False, True, True, "plain")
        self.assertEqual(text.count("Id "), 1)

    def test_date_and_day_are_never_repeated_as_line_columns(self):
        rows = [
            {"date": "2026-09-22", "day": "Tue", "id": "ABC-1", "title": "a", "activity": "Coding"}
        ]
        for style in ("grid", "plain"):
            text = br.render_terminal(rows, LAYOUT_COLUMNS, 60, None, False, True, True, style)
            self.assertEqual(text.count("2026-09-22"), 1, style)
            self.assertEqual(text.count("Tue"), 1, style)

    def test_only_heading_columns_degrades_to_bare_date_headings(self):
        rows = [
            {"date": "2026-09-22", "id": "ABC-1", "title": "a", "activity": "Coding"},
            {"date": "2026-09-23", "id": "ABC-2", "title": "b", "activity": "Coding"},
        ]
        text = br.render_terminal(rows, ["date", "day"], 60, None, False, True, True, "grid")
        self.assertEqual(text, "2026-09-22 (Tue)\n2026-09-23 (Wed)\n")

    def test_an_empty_report_says_so(self):
        self.assertEqual(
            br.render_terminal([], LAYOUT_COLUMNS, 60, "2026-09-01 to 2026-09-07", True),
            "No activity found for 2026-09-01 to 2026-09-07.\n",
        )

    def test_summary_tallies_lines_per_activity(self):
        rows = [
            {"date": "2026-09-22", "id": "ABC-1", "title": "a", "activity": "Coding"},
            {"date": "2026-09-22", "id": "ABC-2", "title": "b", "activity": "Coding"},
            {"date": "2026-09-22", "id": "ABC-3", "title": "c", "activity": "Code Review"},
        ]
        text = br.render_terminal(rows, LAYOUT_COLUMNS, 60, None, True)
        self.assertIn("Coding               2 entries", text)
        self.assertIn("Code Review          1 entry", text)
        self.assertIn("total lines          3", text)


class ColumnsTest(unittest.TestCase):
    def test_include_time_injects_time_after_date_and_day(self):
        self.assertEqual(
            br.resolve_columns(None, True, noop),
            ["date", "day", "time", "item_type", "id", "title", "activity"],
        )

    def test_include_time_slots_time_first_without_a_leading_date(self):
        self.assertEqual(
            br.resolve_columns(["id", "activity"], True, noop),
            ["time", "id", "activity"],
        )

    def test_no_include_time_strips_a_configured_time_column(self):
        self.assertEqual(br.resolve_columns(["date", "time", "activity"], False, noop), ["date", "activity"])

    def test_unknown_column_warns_and_is_dropped(self):
        warn = Collector()
        self.assertEqual(br.resolve_columns(["date", "tickt_id"], False, warn), ["date"])
        self.assertIn("unknown column", warn.seen[0])

    def test_the_old_ticket_id_column_name_still_resolves_to_id(self):
        self.assertEqual(
            br.resolve_columns(["date", "ticket_id", "activity"], False, noop),
            ["date", "id", "activity"],
        )

    def test_type_means_issue_type_and_system_means_the_jira_confluence_column(self):
        self.assertEqual(
            br.resolve_columns(["type", "system", "id"], False, noop),
            ["ticket_type", "item_type", "id"],
        )
        self.assertEqual(br.resolve_columns(["issue_type"], False, noop), ["ticket_type"])

    def test_the_system_type_and_id_headers_render_with_those_names(self):
        rows = [
            {
                "date": "2026-09-22",
                "item_type": "Confluence",
                "ticket_type": "Page",
                "id": "393217",
                "title": "RFC",
                "activity": "Documentation",
            }
        ]
        columns = ["date", "day", "item_type", "ticket_type", "id", "title", "activity"]
        text = br.render_terminal(rows, columns, 60, None, False, False, True, "grid")
        self.assertIn("| System     | Type | Id     | Title | Activity      |", text)
        self.assertIn("| Confluence | Page | 393217 | RFC   | Documentation |", text)

    def test_the_issue_type_column_is_opt_in_not_in_the_defaults(self):
        self.assertNotIn("ticket_type", DEFAULT_COLUMNS)
        self.assertIn("ticket_type", br.ALL_COLUMNS)

    def test_dropping_every_column_falls_back_to_the_defaults(self):
        self.assertEqual(br.resolve_columns(["nope"], False, noop), DEFAULT_COLUMNS)


class ParserTest(unittest.TestCase):
    def test_include_time_stays_tri_state_so_config_can_win(self):
        parser = br.build_parser()
        self.assertIsNone(parser.parse_args(["--events", "e.json"]).include_time)
        self.assertTrue(parser.parse_args(["--events", "e.json", "--include-time"]).include_time)
        self.assertFalse(parser.parse_args(["--events", "e.json", "--no-include-time"]).include_time)

    def test_weekday_and_header_stay_tri_state_so_config_can_win(self):
        parser = br.build_parser()
        self.assertIsNone(parser.parse_args(["--events", "e.json"]).weekday)
        self.assertIsNone(parser.parse_args(["--events", "e.json"]).header)
        self.assertFalse(parser.parse_args(["--events", "e.json", "--no-weekday"]).weekday)
        self.assertFalse(parser.parse_args(["--events", "e.json", "--no-header"]).header)

    def test_table_style_defaults_to_none_so_config_can_win(self):
        parser = br.build_parser()
        self.assertIsNone(parser.parse_args(["--events", "e.json"]).table_style)
        self.assertEqual(
            parser.parse_args(["--events", "e.json", "--table-style", "plain"]).table_style, "plain"
        )


if __name__ == "__main__":
    unittest.main()
