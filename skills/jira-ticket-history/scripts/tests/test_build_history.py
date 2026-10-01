import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import build_history as bh  # noqa: E402


def fixture():
    with open(os.path.join(HERE, "fixtures", "bundle.json"), encoding="utf-8") as fh:
        return json.load(fh)


def config():
    with open(os.path.join(HERE, "fixtures", "config.json"), encoding="utf-8") as fh:
        return json.load(fh)


def model(**over):
    cfg = config()
    opts = {"tz": "utc", "automation_accounts": cfg["automation_accounts"],
            "exclude_fields": cfg["history"]["exclude_fields"]}
    opts.update(over)
    return bh.build_model(fixture(), **opts)


def by_id(m, cid):
    return next(c for c in m["commits"] if c["id"] == cid)


class Mojibake(unittest.TestCase):
    def test_repairs_utf8_read_as_cp1252(self):
        text, fixed = bh.repair_mojibake("a â€” b â€œqâ€\u009d cafÃ©")
        self.assertEqual(text, "a — b “q” café")
        self.assertEqual([x[1] for x in fixed], ["—", "“", "”", "é"])

    def test_leaves_genuine_text_alone(self):
        for s in ["naïve Â façade", "Ångström", "€5 → 10×", "🎯 done", "Zürich — ok"]:
            self.assertEqual(bh.repair(s), s)


class Diff(unittest.TestCase):
    def test_escape_only_edit_is_markup_only(self):
        d = bh.text_diff("h2. Goal\nText a-b.", "h2. Goal\n\nText a\\-b\\.")
        self.assertTrue(d["markup_only"])
        self.assertEqual((d["add"], d["del"], d["hunks"]), (0, 0, []))

    def test_pairs_changed_lines_and_collapses_context(self):
        a = "\n".join(["one", "two", "three", "four", "five", "six"])
        b = "\n".join(["one", "two", "three", "4", "five", "six"])
        d = bh.text_diff(a, b)
        self.assertEqual([h["k"] for h in d["hunks"]], ["~", "=", "-", "+", "=", "~"])
        self.assertEqual(d["hunks"][3]["w"], [["x", "4"]])
        self.assertEqual(len(d["full"]), 6)

    def test_word_diff(self):
        w = bh.word_diff("retry up to 3 times", "retry up to 5 times")
        self.assertEqual(w["del"], [["=", "retry up to "], ["x", "3"], ["=", " times"]])
        self.assertEqual(w["add"], [["=", "retry up to "], ["x", "5"], ["=", " times"]])

    def test_records_broken_side(self):
        d = bh.text_diff("x — y", "x â€” y")
        self.assertEqual(d["encoding"], {"before": [], "after": ["â€” → —"]})


class Adf(unittest.TestCase):
    def test_converts_to_wiki(self):
        doc = {"type": "doc", "content": [
            {"type": "heading", "attrs": {"level": 3}, "content": [{"type": "text", "text": "Title"}]},
            {"type": "paragraph", "content": [
                {"type": "text", "text": "bold", "marks": [{"type": "strong"}]}, {"type": "text", "text": " and "},
                {"type": "text", "text": "link", "marks": [{"type": "link", "attrs": {"href": "https://x.test"}}]}]},
            {"type": "bulletList", "content": [{"type": "listItem", "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "a"}]},
                {"type": "bulletList", "content": [{"type": "listItem", "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": "b"}]}]}]}]}]},
        ]}
        self.assertEqual(bh.adf_to_wiki(doc), "h3. Title\n\n*bold* and [link|https://x.test]\n\n* a\n\n** b")

    def test_escaped_adf_parses(self):
        raw = '{"type":"doc","content":\\[{"type":"paragraph","content":\\[{"type":"text","text":"a\\-b"}\\]}\\]}'
        self.assertEqual(bh.to_wiki(raw), "a-b")


class Classification(unittest.TestCase):
    def test_types_come_from_field_identity(self):
        cases = [
            ({"field": "status", "fieldId": "status"}, "status"),
            ({"field": "assignee", "fieldId": "assignee"}, "assignee"),
            ({"field": "description", "fieldId": "description"}, "description"),
            ({"field": "summary", "fieldId": "summary"}, "title"),
            ({"field": "Link"}, "links"),
            ({"field": "IssueParentAssociation"}, "links"),
            ({"field": "RemoteWorkItemLink"}, "weblinks"),
            ({"field": "Attachment"}, "attachments"),
            ({"field": "Comment", "fieldId": "comment"}, "comments"),
            ({"field": "WorklogId"}, "worklogs"),
            ({"field": "Story Points", "fieldId": "customfield_10016"}, "fields"),
        ]
        for item, want in cases:
            self.assertEqual(bh.classify(item), want, item)
        self.assertEqual(sorted(set(c[1] for c in cases)), sorted(bh.TYPES))

    def test_missing_to_is_a_removal(self):
        c = bh.to_change({"field": "Comment", "fieldId": "comment", "fromString": "old text"})
        self.assertEqual(c["subject"], "Delete comment")
        self.assertEqual(c["deleted"], "old text")

    def test_readable_subjects(self):
        self.assertEqual(bh.to_change({"field": "labels", "fieldId": "labels", "fromString": "a b", "toString": "b c"})["subject"], "Labels +c −a")
        self.assertEqual(bh.to_change({"field": "Area", "fieldId": "cf1", "toString": "Parent values: A(1)Level 1 values: B(2)"})["to"], "A / B")
        self.assertEqual(bh.to_change({"field": "Team", "fieldId": "cf2", "fromString": "X"})["subject"], "Clear Team")


class Model(unittest.TestCase):
    def test_commit_counts_and_order(self):
        m = model()
        b = fixture()
        self.assertEqual(len(m["commits"]), 1 + len(b["changelog"]) - 1 + len(b["comments"]) + len(b["worklogs"]))
        self.assertEqual(m["excluded_fields"], ["Rank"])
        times = [bh.to_epoch_ms(c["ts"]) for c in m["commits"]]
        self.assertEqual(times, sorted(times))

    def test_creation_shows_original_values(self):
        created = model()["commits"][0]
        get = {x["label"]: x for x in created["changes"]}
        self.assertEqual(get["Status"]["to"], "To Do")
        self.assertEqual(get["Title"]["to"], "Add retry")
        self.assertEqual(get["Description"]["initial"][0], "h2. Goal")
        self.assertNotIn("Assignee", get)

    def test_automation(self):
        m = model()
        self.assertTrue(by_id(m, "1001")["bot"])
        self.assertTrue(by_id(m, "1011")["bot"])
        self.assertFalse(by_id(m, "1002")["bot"])
        self.assertFalse(by_id(model(automation_accounts=[]), "1011")["bot"])

    def test_description_history(self):
        m = model()
        self.assertEqual(by_id(m, "1004")["subject"], "Edit description (+3 −2)")
        self.assertEqual(by_id(m, "1005")["subject"], "Reformat description (markup only)")
        self.assertEqual(by_id(m, "1006")["subject"], "Save description with broken characters")
        self.assertEqual(by_id(m, "1007")["subject"], "Fix broken characters in description")
        self.assertTrue(by_id(m, "1008")["changes"][0]["diff"]["adf"])

    def test_comments_and_worklogs(self):
        m = model()
        self.assertEqual(by_id(m, "c3001")["body"]["format"], "html")
        self.assertEqual(by_id(m, "c3002")["parent"], "c3001")
        self.assertEqual(by_id(m, "c3002")["edited"], "2026-03-02T10:45:00+00:00")
        self.assertEqual(by_id(m, "c3003")["visibility"], "Developers")
        self.assertEqual(by_id(m, "w7001")["started"], "2026-03-03T11:00:00+00:00")

    def test_dev_summary_by_schema(self):
        self.assertEqual(model()["dev"]["pull_requests"], 2)
        b = fixture()
        b["issue"]["schema"] = {}
        self.assertIsNone(bh.build_model(b, tz="utc")["dev"])

    def test_short_fetch_is_reported(self):
        b = fixture()
        b["completeness"]["changelog"] = {"got": 18, "total": 40, "pages": 1, "complete": False}
        del b["completeness"]["worklogs"]
        m = bh.build_model(b, tz="utc")
        self.assertFalse(m["fetch"][0]["complete"])
        self.assertTrue(any("fetched 18 of 40" in w for w in m["warnings"]))
        self.assertEqual(model()["warnings"], [])


class Rendering(unittest.TestCase):
    def test_page_embeds_data_safely(self):
        with open(os.path.join(HERE, "..", "..", "assets", "template.html"), encoding="utf-8", newline="") as fh:
            tpl = fh.read()
        html = bh.render_page(tpl, model())
        self.assertIn("<title>DEMO-42 History</title>", html)
        data = html[html.index("const DATA = ") + 13:html.index(";\nconst T = DATA.ticket")]
        self.assertNotIn("<", data)
        self.assertEqual(json.loads(data)["ticket"]["key"], "DEMO-42")
        with self.assertRaises(ValueError):
            bh.render_page("no marker", model())

    def test_timestamps(self):
        self.assertEqual(bh.to_epoch_ms("2026-03-02T10:00:05.000+0200"), bh.to_epoch_ms("2026-03-02T08:00:05Z"))
        self.assertIsNone(bh.to_epoch_ms("yesterday"))
        self.assertEqual(bh.render_ts(bh.to_epoch_ms("2026-03-02T08:00:05Z"), "utc"), "2026-03-02T08:00:05+00:00")

    def test_args(self):
        with self.assertRaises(ValueError):
            bh.parse_args([])
        with self.assertRaises(ValueError):
            bh.parse_args(["--bundle", "b", "--types", "bogus"])


@unittest.skipUnless(shutil.which("node"), "node not available")
class Twin(unittest.TestCase):
    def test_node_twin_writes_identical_page(self):
        d = tempfile.mkdtemp()
        try:
            args = ["--bundle", os.path.join(HERE, "fixtures", "bundle.json"),
                    "--config", os.path.join(HERE, "fixtures", "config.json"), "--tz", "utc"]
            py, js = os.path.join(d, "py.html"), os.path.join(d, "js.html")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(bh.main(args + ["--out", py]), 0)
            r = subprocess.run(["node", os.path.join(HERE, "..", "build_history.mjs")] + args + ["--out", js],
                               capture_output=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            with open(py, "rb") as a, open(js, "rb") as b:
                self.assertEqual(a.read(), b.read())
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
