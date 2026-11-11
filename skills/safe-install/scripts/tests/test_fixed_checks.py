import json
from pathlib import Path
import unittest

import safe_install as gate


SKILL = Path(__file__).resolve().parents[2]
REPO = SKILL.parents[1]


def materialize(fixture):
    parts = []
    for part in fixture["parts"]:
        if "text" in part:
            parts.append(part["text"])
        elif "codepoint" in part:
            parts.append(chr(int(part["codepoint"], 16)))
        else:
            parts.append(part["repeat"] * part["count"])
    return "".join(parts)


class FixedChecksTests(unittest.TestCase):
    def test_all_positive_and_negative_fixtures(self):
        rules = gate.load_rules(SKILL / "references" / "fixed-checks.json")
        fixtures = SKILL / "tests" / "fixed-checks"
        self.assertEqual({rule["id"] for rule in rules}, {p.name for p in fixtures.iterdir() if p.is_dir()})
        for rule in rules:
            directory = fixtures / rule["id"]
            expected = json.loads((directory / "expected.json").read_text(encoding="utf-8"))
            for kind in ("positive", "negative"):
                with self.subTest(rule=rule["id"], kind=kind):
                    fixture = json.loads((directory / (kind + ".json")).read_text(encoding="utf-8"))
                    findings = gate.fixed_findings(
                        [{"path": fixture["path"], "text": materialize(fixture)}], [rule], "fixture")
                    actual = [{key: finding[key] for key in ("id", "severity", "line")} for finding in findings]
                    self.assertEqual(expected[kind], actual)
                    if rule["redact"] and findings:
                        self.assertNotIn(materialize(fixture), json.dumps(findings))

    def test_every_repository_skill_and_plugin_has_zero_findings(self):
        rules = gate.load_rules(SKILL / "references" / "fixed-checks.json")
        packages = list((REPO / "skills").rglob("SKILL.md"))
        packages += list((REPO / "plugins").rglob("SKILL.md"))
        packages += list((REPO / "plugins").glob("*/.claude-plugin/plugin.json"))
        self.assertGreater(len(packages), 2)
        for marker in packages:
            root = marker.parent.parent if marker.name == "plugin.json" else marker.parent
            with self.subTest(package=str(root.relative_to(REPO))):
                files = []
                for path in root.rglob("*"):
                    if path.is_file():
                        try:
                            text = path.read_bytes().decode("utf-8")
                        except UnicodeError:
                            continue
                        if "\x00" in text:
                            continue
                        files.append({"path": path.relative_to(root).as_posix(), "text": text})
                self.assertEqual([], gate.fixed_findings(files, rules, root.name))


if __name__ == "__main__":
    unittest.main()
