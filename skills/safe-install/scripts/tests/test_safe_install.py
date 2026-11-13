import contextlib
import datetime
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import urllib.error
import urllib.parse
import zipfile

import safe_install as si


HERE = Path(__file__).resolve().parent
FAKE_CLAUDE = [sys.executable, "-I", str(HERE / "fake_claude.py")]
# Same CLI as safe_install.py, with the fake injected (the real CLI has no hook).
CLI = HERE / "cli_with_fake_claude.py"


class GateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="safe-install-tests-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.cwd = self.base / "working"
        self.cwd.mkdir()
        self.config = self.base / "config"
        self.fake_config = self.base / "fake.json"
        self.log = self.base / "calls.jsonl"
        self.settings = {}
        self.save_settings()
        self.environment = mock.patch.dict(os.environ, {
            "CLAUDE_CONFIG_DIR": str(self.config),
            "FAKE_CLAUDE_CONFIG": str(self.fake_config), "FAKE_CLAUDE_LOG": str(self.log),
            "FAKE_CLAUDE_REGISTRY": str(self.base / "installed.json"),
            "FAKE_CLAUDE_INSTALL_ROOT": str(self.base / "installed"), "CLAUDECODE": "parent-session",
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)
        network = mock.patch.object(si.urllib.request.OpenerDirector, "open",
                                    side_effect=AssertionError("Offline tests must not use the network"))
        network.start()
        self.addCleanup(network.stop)
        self.clock = datetime.datetime(2026, 11, 11, 12, 0, tzinfo=datetime.timezone.utc)
        self.http_calls = []
        self.http_responses = {}
        self.gate = si.Gate(config=self.config, cwd=self.cwd, http=self.http, now=lambda: self.clock,
                            claude_command=FAKE_CLAUDE)

    def save_settings(self):
        self.fake_config.write_text(json.dumps(self.settings), encoding="utf-8")

    def http(self, url, limit):
        self.http_calls.append(url)
        if url not in self.http_responses:
            raise urllib.error.HTTPError(url, 404, "Offline fixture not found", {}, None)
        value = self.http_responses[url]
        if len(value) > limit:
            raise si.GateError("Download exceeds resource limit")
        return value

    def skill(self, name="example", files=None, parent=None):
        root = (parent or self.base / "sources") / name
        root.mkdir(parents=True)
        shutil.copyfile(str(HERE / "fixtures" / "skill" / "SKILL.md"), str(root / "SKILL.md"))
        for path, data in (files or {}).items():
            destination = root / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)
        return root

    def plugin(self, name="example", parent=None, manifest=None, files=None):
        root = (parent or self.base / "sources") / name
        (root / ".claude-plugin").mkdir(parents=True)
        value = json.loads((HERE / "fixtures" / "plugin" / "plugin.json").read_text(encoding="utf-8"))
        value.update(name=name)
        value.update(manifest or {})
        (root / ".claude-plugin" / "plugin.json").write_text(json.dumps(value), encoding="utf-8")
        for path, data in (files or {}).items():
            destination = root / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)
        return root

    def market(self, entries, name="demo", metadata=None):
        root = self.base / ("market-" + name)
        (root / ".claude-plugin").mkdir(parents=True)
        catalog = {"name": name, "plugins": entries}
        if metadata:
            catalog["metadata"] = metadata
        (root / ".claude-plugin" / "marketplace.json").write_text(json.dumps(catalog), encoding="utf-8")
        self.settings.setdefault("marketplaces", []).append({"name": name, "installLocation": str(root)})
        self.save_settings()
        return root

    def scan(self, target, **kwargs):
        report, code = self.gate.scan(str(target), **kwargs)
        self.assertEqual(0, code)
        return report

    def calls(self):
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()] if self.log.exists() else []

    def stage(self, report):
        return self.config / "safe-install" / "staged" / report["digest"]

    def make_zip(self, repo, sha, files):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            for path, content in files.items():
                info = zipfile.ZipInfo(repo + "-" + sha + "/" + path)
                info.create_system = 3
                info.external_attr = (stat.S_IFREG | 0o644) << 16
                archive.writestr(info, content)
        return stream.getvalue()

    def remote(self, repo, files, ref="HEAD", sha=None):
        sha = sha or "a" * 40
        owner, name = repo.split("/")
        self.http_responses["https://api.github.com/repos/{}/commits/{}".format(
            repo, urllib.parse.quote(ref, safe=""))] = json.dumps({"sha": sha}).encode()
        self.http_responses["https://codeload.github.com/{}/zip/{}".format(repo, sha)] = self.make_zip(name, sha, files)
        return sha

    def test_clean_installs_without_approval_and_discard(self):
        source = self.skill(files={"scripts/helper.py": "print('inert fixture')"})
        report = self.scan(source)
        self.assertEqual("clean", report["verdict"])
        self.assertTrue(report["complete"])
        self.assertEqual(si.POLICY, report["policy"])
        self.assertEqual(report, json.loads((self.stage(report) / "report.json").read_bytes()))
        destination = Path(report["destination"])
        self.assertFalse(destination.exists())
        (source / "SKILL.md").write_text("Changed original after review", encoding="utf-8")
        result = self.gate.install(report["digest"])
        self.assertEqual("installed", result["status"])
        self.assertIn("Summarize", (destination / "SKILL.md").read_text(encoding="utf-8"))
        self.assertEqual("discarded", self.gate.discard(report["digest"])["status"])
        self.assertFalse(self.stage(report).exists())

    def test_ask_requires_approval(self):
        self.settings["review_severity"] = "HIGH"
        self.save_settings()
        report = self.scan(self.skill())
        self.assertEqual("ask", report["verdict"])
        self.assertEqual("failed", self.gate.install(report["digest"])["status"])
        self.assertFalse(Path(report["destination"]).exists())
        self.assertEqual("installed", self.gate.install(report["digest"], approved=True)["status"])

    def test_critical_has_no_override(self):
        self.settings["review_severity"] = "CRITICAL"
        self.save_settings()
        report = self.scan(self.skill())
        self.assertEqual("block", report["verdict"])
        self.assertEqual("failed", self.gate.install(report["digest"], approved=True, replace=True)["status"])
        self.assertFalse(Path(report["destination"]).exists())

    def test_incomplete_review_and_unreviewable_binary_block(self):
        self.settings["review_mode"] = "incomplete"
        self.save_settings()
        report = self.scan(self.skill())
        self.assertEqual("block", report["verdict"])
        self.assertIn("External content", " ".join(report["reasons"]))
        self.settings["review_mode"] = "clean"
        self.save_settings()
        report = self.scan(self.skill("binary", {"program.exe": b"MZ\x00binary"}))
        self.assertFalse(report["complete"])
        self.assertEqual("block", report["verdict"])
        report = self.scan(self.skill("archive", {"bundle.zip": b"PK\x00fixture"}))
        self.assertEqual("block", report["verdict"])

    def test_images_and_fonts_are_unreviewed_without_findings(self):
        report = self.scan(self.skill(files={"icon.png": b"\x89PNG\r\n\x1a\n\x00", "font.woff2": b"wOF2\x00"}))
        self.assertEqual("clean", report["verdict"])
        self.assertEqual([], report["findings"])
        self.assertEqual({"icon.png", "font.woff2"}, set(report["inventory"]["unreviewed_files"]))
        review = next(call["input"] for call in self.calls() if "-p" in call["args"])
        self.assertEqual(["SKILL.md"], [f["path"] for f in review["files"]])
        self.assertEqual(3, len(review["full_file_list"]))
        disguised = self.scan(self.skill("disguised", {"icon.png": b"MZ\x00not an image"}))
        self.assertEqual("block", disguised["verdict"])

    def test_scopes_and_invalid_names(self):
        report = self.scan(self.skill(), scope="project")
        self.assertEqual(str(self.cwd / ".claude" / "skills" / "example"), report["destination"])
        with self.assertRaises(si.UsageError):
            self.gate.scan(str(self.skill("local-test")), scope="local")
        report = self.scan(self.skill("UPPER"))
        self.assertEqual("block", report["verdict"])
        report = self.scan(self.skill("x" * 65))
        self.assertEqual("block", report["verdict"])

    def test_links_and_ancestor_links_are_refused(self):
        source = self.skill()
        link = self.base / "linked"
        try:
            link.symlink_to(source, target_is_directory=True)
        except OSError:
            self.skipTest("Creating symlinks requires platform privileges")
        self.assertEqual("block", self.scan(link)["verdict"])
        self.assertEqual("block", self.scan(link / "scripts")["verdict"])
        (source / "link.txt").symlink_to(source / "SKILL.md")
        self.assertEqual("block", self.scan(source)["verdict"])

    def test_paths_and_case_collisions_are_refused(self):
        for path in ("../escape", "/absolute", "C:/file", "CON.txt", "a/../b", "a\\b", "NUL", "a.",
                     "CONIN$", "CONOUT$", "has?wildcard", "a\nb"):
            with self.subTest(path=path), self.assertRaises(si.GateError):
                si.safe_path(path)
        with self.assertRaises(si.GateError):
            si.validate_paths([{"path": "A/x"}, {"path": "a/y"}])
        with self.assertRaises(si.GateError):
            si.validate_paths([{"path": "file"}, {"path": "file/child"}])

    def test_zip_checks_only_selected_tree_and_refuses_escapes(self):
        sha = "a" * 40
        data = self.make_zip("repo", sha, {
            "skills/example/SKILL.md": "text", "unrelated/bad:name": "ignored",
            "unrelated/../../escape": "ignored",
        })
        tree = si.Tree(archive=zipfile.ZipFile(io.BytesIO(data)), archive_root="repo-" + sha)
        self.assertEqual(["SKILL.md"], [f["path"] for f in tree.read("skills/example")])
        data = self.make_zip("repo", sha, {"skills/example/../escape": "bad"})
        tree = si.Tree(archive=zipfile.ZipFile(io.BytesIO(data)), archive_root="repo-" + sha)
        with self.assertRaises(si.GateError):
            tree.read("skills/example")
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            info = zipfile.ZipInfo("repo-" + sha + "/skills/example/link")
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, "outside")
        tree = si.Tree(archive=zipfile.ZipFile(io.BytesIO(stream.getvalue())), archive_root="repo-" + sha)
        with self.assertRaises(si.GateError):
            tree.read("skills/example")

    def test_github_slash_ref_and_blob_url(self):
        self.remote("owner/repo", {"skills/example/SKILL.md": "Text",
                                  "skills/example/scripts/helper.py": "pass"}, ref="feature/fix")
        report = self.scan("https://github.com/owner/repo/tree/feature/fix/skills/example")
        self.assertEqual("clean", report["verdict"])
        self.assertEqual("a" * 40, report["source"]["commit"])
        self.assertIn("feature%2Ffix", " ".join(self.http_calls))
        digest = report["digest"]
        self.gate.discard(report["digest"])
        report = self.scan("https://github.com/owner/repo/blob/feature/fix/skills/example")
        self.assertEqual("clean", report["verdict"])
        self.assertEqual("example", report["name"])
        self.assertEqual(digest, report["digest"])
        self.gate.discard(report["digest"])
        report = self.scan("https://github.com/owner/repo/blob/feature/fix/skills/example/SKILL.md")
        self.assertEqual("clean", report["verdict"])
        self.assertEqual(digest, report["digest"])
        self.gate.discard(report["digest"])
        report = self.scan("https://github.com/owner/repo/blob/feature/fix/skills/example/scripts/helper.py")
        self.assertEqual("clean", report["verdict"])
        self.assertEqual("example", report["name"])
        self.assertEqual(digest, report["digest"])
        self.gate.discard(report["digest"])
        report = self.scan("https://github.com/owner/repo/blob/feature/fix")
        self.assertEqual("block", report["verdict"])
        self.assertIn("Blob URL has no path", report["reasons"])
        self.assertTrue(all("github.com" in url for url in self.http_calls))

    def test_github_blob_folder_of_skills_returns_choices(self):
        self.remote("owner/repo", {"skills/first/SKILL.md": "First skill",
                                  "skills/second/SKILL.md": "Second skill"}, ref="main")
        for kind in ("tree", "blob"):
            with self.subTest(kind=kind):
                report = self.scan("https://github.com/owner/repo/{}/main/skills".format(kind))
                self.assertEqual(["first", "second"], report["choices"])
                self.assertIsNone(report["verdict"])
        self.assertFalse(self.calls())

    def test_marketplace_choices_and_folder_choices(self):
        market = self.market([{"name": "one", "source": "./one"}, {"name": "two", "source": "./two"}])
        report = self.scan(market)
        self.assertEqual(["one", "two"], report["choices"])
        self.assertIsNone(report["verdict"])
        folder = self.base / "many"
        self.skill("first", parent=folder)
        self.skill("second", parent=folder)
        self.assertEqual(["first", "second"], self.scan(folder)["choices"])
        self.assertFalse(self.calls())

    def test_relative_and_plugin_root_marketplace_sources(self):
        for index, source in enumerate(("./plugins/example", "example")):
            name = "demo" + str(index)
            market = self.market([{"name": "example", "source": source, "strict": True,
                                   "hooks": {"SessionStart": []}}],
                                 name=name, metadata={"pluginRoot": "./plugins"})
            self.plugin(parent=market / "plugins", files={"hooks/hooks.json": '{"hooks": {}}'})
            report = self.scan("example@" + name)
            self.assertEqual("clean", report["verdict"])
            payload = self.stage(report) / "files" / ".safe-install" / "marketplace-entry.json"
            self.assertEqual(source, json.loads(payload.read_bytes())["source"])
            self.assertTrue(any(f["path"].endswith("marketplace-entry.json")
                                for call in self.calls() if "input" in call for f in call["input"]["files"]))
            self.assertFalse(any("add" in call["args"] or "update" in call["args"] for call in self.calls()))

    def test_supported_remote_marketplace_sources(self):
        for index, kind in enumerate(("github", "url", "git-subdir")):
            source = {"source": kind, "sha": (str(index + 1) * 40)}
            subdir = "plugins/example" if kind == "git-subdir" else ""
            if kind == "github":
                source["repo"] = "owner/remote"
            else:
                source["url"] = "https://github.com/owner/remote.git"
            if subdir:
                source["path"] = subdir
            path = (subdir + "/" if subdir else "") + ".claude-plugin/plugin.json"
            self.remote("owner/remote", {path: '{"name":"example"}'}, sha=source["sha"])
            name = "remote" + str(index)
            self.market([{"name": "example", "source": source}], name=name)
            report = self.scan("example@" + name)
            self.assertEqual("clean", report["verdict"], report["reasons"])
            self.assertEqual(source["sha"], report["source"]["commit"])
            self.assertFalse(any("/commits/" in url for url in self.http_calls))

    def test_unsupported_marketplace_sources_block(self):
        for index, source in enumerate((
                {"source": "npm", "package": "example"},
                {"source": "archive", "url": "https://github.com/a/b/archive.zip"},
                {"source": "command", "command": "must not run"},
                {"source": "url", "url": "https://elsewhere.test/repo.git"},
                {"source": "git-subdir", "url": "git@github.com:a/b.git", "path": "x"},
                "../escape")):
            name = "unsupported" + str(index)
            self.market([{"name": "example", "source": source}], name=name)
            report = self.scan("example@" + name)
            self.assertEqual("block", report["verdict"])
            self.assertFalse(report["complete"])
        self.assertFalse(any("-p" in call["args"] or "install" in call["args"] for call in self.calls()))

    def test_unregistered_local_marketplace_install_and_verification(self):
        market = self.market([{"name": "example", "source": "./example"}])
        source = self.plugin(parent=market)
        self.settings["install_sources"] = {"example@demo": str(source)}
        self.save_settings()
        report = self.scan("example", marketplace=str(market), scope="project")
        self.assertEqual("clean", report["verdict"])
        self.assertEqual("installed", self.gate.install(report["digest"])["status"])
        command = next(c["args"] for c in self.calls() if c["args"][:2] == ["plugin", "install"])
        self.assertEqual(["plugin", "install", "example", "--marketplace", str(market), "--scope", "project"], command)
        self.assertFalse(any("marketplace" in c["args"] and "add" in c["args"] for c in self.calls()))

    def test_unregistered_remote_marketplace_is_fetched_but_not_registered(self):
        catalog = {"name": "remote-market", "plugins": [{"name": "example", "source": "./plugins/example"}]}
        self.remote("owner/catalog", {
            ".claude-plugin/marketplace.json": json.dumps(catalog),
            "plugins/example/.claude-plugin/plugin.json": '{"name":"example"}',
        })
        report = self.scan("example", marketplace="owner/catalog")
        self.assertEqual("clean", report["verdict"])
        self.assertTrue(self.http_calls)
        self.assertFalse(any(c["args"][:3] == ["plugin", "marketplace", "add"] for c in self.calls()))

    def test_dependency_scanning_deduplication_and_cycle(self):
        market = self.market([{"name": "example", "source": "./example", "dependencies": ["dep", "dep"]},
                              {"name": "dep", "source": "./dep"}])
        root = self.plugin(parent=market, manifest={"dependencies": ["dep"]})
        dep = self.plugin("dep", parent=market, manifest={"dependencies": ["example"]})
        self.settings["install_sources"] = {"example@demo": str(root), "dep@demo": str(dep)}
        self.save_settings()
        report = self.scan("example@demo")
        self.assertEqual("clean", report["verdict"])
        self.assertEqual(["dep@demo"], report["inventory"]["dependencies"])
        validation = [c for c in self.calls() if c["args"][:2] == ["plugin", "validate"]]
        self.assertEqual(2, len(validation))
        self.assertEqual("installed", self.gate.install(report["digest"])["status"])

    def test_dependency_depth_and_unresolved_dependency_block(self):
        entries = [{"name": "p" + str(i), "source": "./p" + str(i)} for i in range(5)]
        market = self.market(entries)
        for index in range(5):
            dependencies = ["p" + str(index + 1)] if index < 4 else []
            self.plugin("p" + str(index), parent=market, manifest={"dependencies": dependencies})
        report = self.scan("p0@demo")
        self.assertEqual("block", report["verdict"])
        self.assertIn("three levels", " ".join(report["reasons"]))
        report = self.scan("missing@demo")
        self.assertEqual("block", report["verdict"])

    def test_manifest_errors_and_warnings_are_findings_not_critical(self):
        source = self.plugin()
        self.settings.update(validation={
            "manifest": {"errors": ["Bad field"], "warnings": ["Unusual metadata"]},
            "contents": [{"path": "hooks/hooks.json", "errors": [{"message": "Bad hook", "line": 4}], "warnings": []}],
        }, validation_exit=1)
        self.save_settings()
        report = self.scan(source)
        self.assertEqual("ask", report["verdict"])
        self.assertEqual(["HIGH", "LOW", "HIGH"], [f["severity"] for f in report["findings"]])
        self.assertTrue(all(f["id"] == "VAL" for f in report["findings"]))
        self.assertEqual(2, len(report["inventory"]["hooks"]))
        self.assertEqual(1, len(report["inventory"]["mcp_servers"]))

    def test_installed_copy_mismatch_uninstalls(self):
        market = self.market([{"name": "example", "source": "./example"}])
        source = self.plugin(parent=market)
        self.settings.update(install_sources={"example@demo": str(source)}, mismatch=True)
        self.save_settings()
        report = self.scan("example@demo")
        result = self.gate.install(report["digest"])
        self.assertEqual("failed", result["status"])
        self.assertIn("verification failed", result["detail"])
        self.assertTrue(any(c["args"] == ["plugin", "uninstall", "example@demo", "--scope", "user"] for c in self.calls()))

    def test_tampered_staging_and_executable_bit_refused(self):
        report = self.scan(self.skill())
        (self.stage(report) / "files" / "SKILL.md").write_text("Changed", encoding="utf-8")
        self.assertEqual("failed", self.gate.install(report["digest"])["status"])
        self.assertFalse(Path(report["destination"]).exists())
        self.gate.discard(report["digest"])
        report = self.scan(self.base / "sources" / "example")
        (self.stage(report) / "files" / "extra.txt").write_text("Added", encoding="utf-8")
        self.assertEqual("failed", self.gate.install(report["digest"])["status"])

    def test_stale_report_and_digest_traversal_refused(self):
        report = self.scan(self.skill())
        self.clock += datetime.timedelta(minutes=30)
        self.assertEqual("installed", self.gate.install(report["digest"])["status"])
        self.clock += datetime.timedelta(seconds=1)
        self.assertEqual("failed", self.gate.install(report["digest"])["status"])
        with self.assertRaises(si.UsageError):
            self.gate.discard("../outside")
        with self.assertRaises(si.UsageError):
            self.gate.install("../outside")

    def test_replacement_retains_backup(self):
        report = self.scan(self.skill())
        destination = Path(report["destination"])
        destination.mkdir(parents=True)
        (destination / "old.txt").write_text("Old content", encoding="utf-8")
        self.assertEqual("failed", self.gate.install(report["digest"])["status"])
        result = self.gate.install(report["digest"], replace=True)
        self.assertEqual("installed", result["status"])
        backups = list((self.config / "safe-install" / "backups").iterdir())
        self.assertEqual(1, len(backups))
        self.assertIn(str(backups[0]), result["detail"])
        self.assertEqual("Old content", (backups[0] / "old.txt").read_text(encoding="utf-8"))
        self.assertFalse((destination / "old.txt").exists())
        # The backup lives outside staging, so the workflow's final discard keeps it.
        self.gate.discard(report["digest"])
        self.assertTrue((backups[0] / "old.txt").exists())

    def test_http_errors_without_a_body_are_closed_safely(self):
        # Python 3.9 raises KeyError from close() on an HTTPError whose fp is None.
        no_body = mock.Mock(fp=None)
        si.close_http_error(no_body)
        no_body.close.assert_not_called()
        with_body = mock.Mock(fp=io.BytesIO(b""))
        si.close_http_error(with_body)
        with_body.close.assert_called_once()

    def test_rescan_of_an_undiscarded_snapshot_replaces_it(self):
        source = self.skill()
        first = self.scan(source)
        second = self.scan(source)
        self.assertEqual(first["digest"], second["digest"])
        self.assertEqual("clean", second["verdict"])
        self.assertEqual("installed", self.gate.install(second["digest"])["status"])

    def test_relative_target_with_parent_segments(self):
        self.skill(parent=self.base / "elsewhere")
        report = self.scan("../elsewhere/example")
        self.assertEqual("clean", report["verdict"])
        self.assertEqual(str(self.base / "elsewhere" / "example"), report["source"]["detail"])

    def test_host_added_in_use_markers_do_not_fail_verification(self):
        market = self.market([{"name": "example", "source": "./example"}])
        source = self.plugin(parent=market)
        self.settings.update(install_sources={"example@demo": str(source)})
        self.save_settings()
        report = self.scan("example@demo")
        self.assertEqual("installed", self.gate.install(report["digest"], approved=True)["status"])

    def test_failed_verification_keeps_previously_installed_plugins(self):
        market = self.market([{"name": "example", "source": "./example", "dependencies": ["helper"]},
                              {"name": "helper", "source": "./helper"}])
        source = self.plugin(parent=market)
        helper = self.plugin("helper", parent=market)
        (self.base / "installed.json").write_text(json.dumps(
            [{"id": "helper@demo", "scope": "user", "installPath": str(helper)}]), encoding="utf-8")
        self.settings.update(install_sources={"example@demo": str(source), "helper@demo": str(helper)},
                             mismatch="example@demo")
        self.save_settings()
        report = self.scan("example@demo")
        result = self.gate.install(report["digest"], approved=True)
        self.assertEqual("failed", result["status"])
        self.assertIn("already installed before this run", result["detail"])
        uninstalled = [c["args"][2] for c in self.calls() if c["args"][:2] == ["plugin", "uninstall"]]
        self.assertEqual(["example@demo"], uninstalled)

    def test_plugin_folder_scans_but_explains_why_it_cannot_install(self):
        report = self.scan(self.plugin())
        self.assertIn(report["verdict"], ("ask", "clean"))
        result = self.gate.install(report["digest"], approved=True)
        self.assertEqual("failed", result["status"])
        self.assertIn("name@marketplace", result["detail"])

    @unittest.skipIf(os.name == "nt", "Windows does not represent POSIX executable permission bits")
    def test_executable_bit_is_preserved_and_hashed(self):
        source = self.skill(files={"scripts/run.sh": "#!/bin/sh\nexit 0\n"})
        (source / "scripts" / "run.sh").chmod(0o755)
        report = self.scan(source)
        self.assertEqual("installed", self.gate.install(report["digest"])["status"])
        self.assertTrue((Path(report["destination"]) / "scripts" / "run.sh").stat().st_mode & 0o111)
        self.gate.discard(report["digest"])
        report = self.scan(source)
        (self.stage(report) / "files" / "scripts" / "run.sh").chmod(0o644)
        self.assertEqual("failed", self.gate.install(report["digest"], replace=True)["status"])

    def test_reviewer_protocol_failures_block(self):
        source = self.skill()
        for mode in ("incomplete", "coverage", "duplicate_file", "digest", "policy", "line", "unknown_file",
                     "boolean_line", "severity", "unknown_field", "missing", "error", "subtype",
                     "invalid_json", "duplicate_key", "fail"):
            with self.subTest(mode=mode):
                self.settings["review_mode"] = mode
                self.save_settings()
                report = self.scan(source)
                self.assertEqual("block", report["verdict"], report)
                self.assertFalse(report["complete"])
                self.gate.discard(report["digest"])
        for call in self.calls():
            if "-p" in call["args"]:
                self.assertFalse(call["nested"])
                self.assertEqual("", call["args"][call["args"].index("--tools") + 1])

    def test_fixed_findings_cannot_be_removed_and_can_be_raised(self):
        source = self.skill(files={"note.txt": chr(0x202e) + "Text"})
        report = self.scan(source)
        self.assertEqual("ask", report["verdict"])
        self.assertEqual("HIGH", report["findings"][0]["severity"])
        self.gate.discard(report["digest"])
        self.settings["review_severity"] = "CRITICAL"
        self.save_settings()
        # The first sorted file is SKILL.md, so place a control in that file.
        (source / "SKILL.md").write_text(chr(0x202e) + "Instructions", encoding="utf-8")
        report = self.scan(source)
        self.assertEqual("block", report["verdict"])
        fixed = [f for f in report["findings"] if f["file"] == "SKILL.md" and f["id"].startswith("FC-")]
        self.assertEqual("CRITICAL", fixed[0]["severity"])

    def test_output_escaping_and_secret_redaction(self):
        value = "ghp_" + "A1b2" * 9
        source = self.skill(files={"note.txt": value})
        self.settings.update(review_severity="LOW", review_description=value + chr(0x202e) + "\ntext")
        self.save_settings()
        report = self.scan(source)
        serialized = json.dumps(report)
        self.assertNotIn(value, serialized)
        self.assertIn("[REDACTED]", serialized)
        self.assertNotIn(chr(0x202e), serialized)
        self.assertIn("\\u202e", report["findings"][-1]["description"])
        self.assertEqual("\\u000a\\u001b\\u202e", si.display("\n\x1b" + chr(0x202e)))

    def test_missing_and_malformed_rules(self):
        references = self.base / "references"
        references.mkdir()
        for name in ("reviewer-prompt.md", "review-schema.json"):
            shutil.copyfile(str(si.REFERENCES / name), str(references / name))
        self.gate.references = references
        source = self.skill()
        report = self.scan(source)
        self.assertEqual("clean", report["verdict"])
        self.assertEqual("not available", report["checks"][0]["status"])
        self.gate.discard(report["digest"])
        (references / "fixed-checks.json").write_text('{"not":"an array"}', encoding="utf-8")
        report = self.scan(source)
        self.assertEqual("block", report["verdict"])
        self.assertEqual("failed", report["checks"][0]["status"])

    def test_cli_json_version_usage_scan_install_discard(self):
        source = self.skill()
        def run(*args):
            result = subprocess.run([sys.executable, "-I", str(CLI)] + list(args), capture_output=True,
                                    cwd=str(self.cwd), timeout=30)
            self.assertEqual(b"", result.stderr)
            return json.loads(result.stdout), result.returncode
        self.assertEqual(({"version": "2"}, 0), run("--version"))
        self.assertEqual(2, run("invalid")[1])
        self.assertEqual(2, run("scan", str(source), "--scope", "invalid")[1])
        self.assertEqual(2, run("install", "../outside")[1])
        self.assertEqual(2, run("discard", "../outside")[1])
        report, code = run("scan", str(source))
        self.assertEqual(0, code)
        self.assertEqual("clean", report["verdict"])
        # CLI clock is real; install through the same CLI.
        result, code = run("install", report["digest"])
        self.assertEqual((0, "installed"), (code, result["status"]))
        self.assertEqual("discarded", run("discard", report["digest"])[0]["status"])

    def test_internal_scan_error_still_prints_block_report(self):
        output = io.StringIO()
        with mock.patch.object(si.Gate, "scan", side_effect=RuntimeError("Fixture failure")), contextlib.redirect_stdout(output):
            code = si.main(["scan", "example"])
        self.assertEqual(1, code)
        self.assertEqual("block", json.loads(output.getvalue())["verdict"])

    def test_native_windows_shims_are_refused(self):
        native = si.Gate(config=self.config, cwd=self.cwd)
        with mock.patch.object(si.shutil, "which", return_value="C:\\tools\\claude.cmd"):
            with self.assertRaises(si.GateError):
                native.claude(["-p"])

    def test_environment_cannot_replace_the_claude_executable(self):
        # The old SAFE_INSTALL_CLAUDE hook is gone: only the native lookup is used.
        native = si.Gate(config=self.config, cwd=self.cwd)
        with mock.patch.dict(os.environ, {"SAFE_INSTALL_CLAUDE": json.dumps(FAKE_CLAUDE)}), \
                mock.patch.object(si.shutil, "which", return_value=None):
            with self.assertRaisesRegex(si.GateError, "Native Claude Code executable is not available"):
                native.claude(["plugin", "list", "--json"])
        self.assertFalse(self.calls())
        for value in ([], "claude", [42]):
            with self.subTest(value=value), self.assertRaises(si.GateError):
                si.Gate(config=self.config, cwd=self.cwd, claude_command=value)

    def test_exact_snapshot_limits_and_over_limit_block(self):
        source = self.skill(files={"extra.txt": "12"})
        with mock.patch.object(si, "MAX_FILES", 2):
            report = self.scan(source)
            self.assertEqual("clean", report["verdict"])
            self.gate.discard(report["digest"])
        with mock.patch.object(si, "MAX_FILES", 1):
            self.assertEqual("block", self.scan(source)["verdict"])
        total = sum(path.stat().st_size for path in source.iterdir())
        with mock.patch.object(si, "MAX_TOTAL", total):
            report = self.scan(source)
            self.assertEqual("clean", report["verdict"])
            self.gate.discard(report["digest"])
        with mock.patch.object(si, "MAX_TOTAL", total - 1):
            self.assertEqual("block", self.scan(source)["verdict"])
        (source / "extra.txt").write_bytes(b"a" * si.MAX_TEXT)
        report = self.scan(source)
        self.assertEqual("clean", report["verdict"])
        self.gate.discard(report["digest"])
        with (source / "extra.txt").open("ab") as stream:
            stream.write(b"a")
        report = self.scan(source)
        self.assertEqual("block", report["verdict"])
        self.assertFalse(report["complete"])

    def test_download_limit_and_redirect_host_restriction(self):
        self.remote("owner/repo", {"SKILL.md": "Text"})
        with mock.patch.object(si, "MAX_DOWNLOAD", 20):
            self.assertEqual("block", self.scan("https://github.com/owner/repo")["verdict"])
        with self.assertRaises(si.GateError):
            si.read_bounded(io.BytesIO(b"123"), 2)
        redirect = si.GithubRedirect()
        request = si.urllib.request.Request("https://api.github.com/old")
        for address in ("http://github.com/new", "https://not-github.test/new", "https://github.com.evil.test/new"):
            with self.subTest(address=address), self.assertRaises(si.GateError):
                redirect.redirect_request(request, None, 302, "", {}, address)
        for address in ("https://user:secret@github.com/o/r", "https://github.com/o/r?token=redacted"):
            self.assertEqual("block", self.scan(address)["verdict"])

    def test_large_files_are_chunked_without_lost_bytes_or_lines(self):
        content = "first" + chr(0x85) + "line\n" + chr(0x03a9) * (si.REVIEW_BYTES // 2 + 17)
        self.settings.update(review_severity="LOW", review_file="big.txt")
        self.save_settings()
        report = self.scan(self.skill(files={"big.txt": content}))
        self.assertEqual("ask", report["verdict"])
        calls = [c["input"] for c in self.calls() if "-p" in c["args"]]
        self.assertGreater(len(calls), 1)
        fragments = [f for call in calls for f in call["files"] if f["path"] == "big.txt"]
        self.assertEqual(content, "".join(f["content"] for f in fragments))
        for call in calls:
            self.assertLessEqual(sum(len(f["content"].encode("utf-8")) for f in call["files"]), si.REVIEW_BYTES)
            self.assertEqual(["SKILL.md", "big.txt"], call["full_file_list"])
        lines = [f["line"] for f in report["findings"] if f["file"] == "big.txt"]
        self.assertEqual([1, 2, 2], lines)

    def test_low_and_medium_are_ask_not_block(self):
        source = self.skill()
        for severity in ("LOW", "MEDIUM"):
            self.settings["review_severity"] = severity
            self.save_settings()
            report = self.scan(source)
            self.assertEqual("ask", report["verdict"])
            self.gate.discard(report["digest"])

    def test_fixed_critical_remains_blocked_after_clean_ai_answer(self):
        references = self.base / "references"
        shutil.copytree(str(si.REFERENCES), str(references))
        rules = json.loads((references / "fixed-checks.json").read_bytes())
        rules[0]["severity"] = "critical"
        (references / "fixed-checks.json").write_text(json.dumps(rules), encoding="utf-8")
        self.gate.references = references
        report = self.scan(self.skill(files={"note.md": chr(0x202e) + "Text"}))
        self.assertEqual("block", report["verdict"])
        self.assertEqual("failed", self.gate.install(report["digest"], approved=True)["status"])

    def test_junctions_and_special_files_are_refused_without_platform_privileges(self):
        for attributes, mode in ((0x400, stat.S_IFDIR | 0o755), (0, stat.S_IFIFO | 0o600), (0, stat.S_IFLNK | 0o777)):
            info = mock.Mock(st_mode=mode, st_file_attributes=attributes)
            with mock.patch.object(Path, "lstat", return_value=info), self.assertRaises(si.GateError):
                si.no_links(self.base)

    def test_zip_directory_entries_and_empty_directory_case_collisions(self):
        sha = "a" * 40
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr("repo-" + sha + "/skills/example/", "")
            archive.writestr("repo-" + sha + "/skills/example/SKILL.md", "Text")
        tree = si.Tree(archive=zipfile.ZipFile(io.BytesIO(stream.getvalue())), archive_root="repo-" + sha)
        self.assertEqual(["SKILL.md"], [f["path"] for f in tree.read("skills/example")])
        with zipfile.ZipFile(stream, "a") as archive:
            archive.writestr("repo-" + sha + "/skills/example/Case/", "")
            archive.writestr("repo-" + sha + "/skills/example/case/", "")
        tree = si.Tree(archive=zipfile.ZipFile(io.BytesIO(stream.getvalue())), archive_root="repo-" + sha)
        with self.assertRaises(si.GateError):
            tree.read("skills/example")

    def test_unreadable_directory_does_not_silently_disappear(self):
        source = self.skill()
        def walk(*args, **kwargs):
            kwargs["onerror"](PermissionError("Fixture unreadable directory"))
            return iter(())
        with mock.patch.object(si.os, "walk", side_effect=walk):
            self.assertEqual("block", self.scan(source)["verdict"])

    def test_reserved_snapshot_namespace_and_invalid_forced_layout_block(self):
        report = self.scan(self.skill(files={".safe-install/marketplace-entry.json": "{}"}))
        self.assertEqual("block", report["verdict"])
        empty = self.base / "empty"
        empty.mkdir()
        self.assertEqual("block", self.scan(empty, forced="plugin")["verdict"])
        source = self.skill("ambiguous", {"commands/example.md": "Command instructions"})
        self.assertEqual("block", self.scan(source)["verdict"])
        report = self.scan(source, forced="skill")
        self.assertEqual("clean", report["verdict"])

    def test_relative_paths_use_gate_working_directory(self):
        self.skill(parent=self.cwd)
        report = self.scan("example")
        self.assertEqual("clean", report["verdict"])
        self.assertEqual(str(self.cwd / "example"), report["source"]["detail"])

    def test_standalone_plugin_dependencies_are_reviewed(self):
        market = self.market([{"name": "dep", "source": "./dep"}])
        self.plugin("dep", parent=market)
        source = self.plugin(manifest={"dependencies": ["dep@demo"]})
        report = self.scan(source)
        self.assertEqual("clean", report["verdict"])
        self.assertEqual(["dep@demo"], report["inventory"]["dependencies"])
        self.assertEqual(2, sum(c["args"][:2] == ["plugin", "validate"] for c in self.calls()))
        self.assertIn("marketplace", self.gate.install(report["digest"])["detail"])

    def test_malformed_and_unresolved_dependencies_block(self):
        for index, dependencies in enumerate(("dep", ["missing"], [42], [{"name": "dep", "marketplace": 42}])):
            market = self.market([{"name": "example", "source": "./example", "dependencies": dependencies}],
                                 name="bad" + str(index))
            self.plugin(parent=market)
            report = self.scan("example@bad" + str(index))
            self.assertEqual("block", report["verdict"])

    def test_dependency_mismatch_also_uninstalls_with_original_scope(self):
        market = self.market([{"name": "example", "source": "./example", "dependencies": ["dep"]},
                              {"name": "dep", "source": "./dep"}])
        root = self.plugin(parent=market)
        dep = self.plugin("dep", parent=market)
        self.settings.update(install_sources={"example@demo": str(root), "dep@demo": str(dep)}, mismatch="dep@demo")
        self.save_settings()
        report = self.scan("example@demo", scope="local")
        self.assertEqual("failed", self.gate.install(report["digest"])["status"])
        self.assertTrue(any(c["args"] == ["plugin", "uninstall", "dep@demo", "--scope", "local"] for c in self.calls()))

    def test_plugin_rollback_failure_is_reported(self):
        market = self.market([{"name": "example", "source": "./example"}])
        root = self.plugin(parent=market)
        self.settings.update(install_sources={"example@demo": str(root)}, mismatch=True,
                             fail_command=["plugin", "uninstall"])
        self.save_settings()
        report = self.scan("example@demo")
        result = self.gate.install(report["digest"])
        self.assertEqual("failed", result["status"])
        self.assertIn("rollback failed", result["detail"])

    def test_replace_verification_failure_restores_old_copy(self):
        report = self.scan(self.skill())
        destination = Path(report["destination"])
        destination.mkdir(parents=True)
        (destination / "old.txt").write_text("Original", encoding="utf-8")
        with mock.patch.object(self.gate, "verify_copy", side_effect=si.GateError("Fixture verification failure")):
            result = self.gate.install(report["digest"], replace=True)
        self.assertEqual("failed", result["status"])
        self.assertEqual(["old.txt"], [p.name for p in destination.iterdir()])
        self.assertEqual("Original", (destination / "old.txt").read_text(encoding="utf-8"))

    def test_failed_stage_creation_does_not_leave_partial_snapshot(self):
        source = self.skill()
        with mock.patch.object(Path, "chmod", side_effect=PermissionError("Fixture staging failure")):
            with self.assertRaises(OSError):
                self.gate.scan(str(source))
        self.assertEqual([], list((self.config / "safe-install" / "staged").iterdir()))

    def test_discard_does_not_apply_payload_limits_to_backups_and_reports(self):
        report = self.scan(self.skill())
        with mock.patch.object(si, "MAX_FILES", 1), mock.patch.object(si, "MAX_TOTAL", 1):
            self.assertEqual("discarded", self.gate.discard(report["digest"])["status"])

    def test_native_inventory_and_validation_failures_block(self):
        source = self.plugin()
        for setting in ({"inventory": "No component inventory available"},
                        {"validation": {"manifest": None}},
                        {"validation": {"manifest": {}, "contents": []}, "validation_exit": 7}):
            self.settings = setting
            self.save_settings()
            report = self.scan(source)
            self.assertEqual("block", report["verdict"])
            self.assertFalse(report["complete"])
            self.gate.discard(report["digest"])

    def test_reviewer_timeout_blocks(self):
        source = self.skill()
        with mock.patch.object(si.subprocess, "run", side_effect=subprocess.TimeoutExpired("fake", 300)):
            report = self.scan(source)
        self.assertEqual("block", report["verdict"])
        self.assertIn("timed out", " ".join(report["reasons"]))

    def test_rule_validation_filters_and_nonfinite_duplicate_json(self):
        original = json.loads((si.REFERENCES / "fixed-checks.json").read_bytes())[0]
        path = self.base / "rules.json"
        variants = ({"id": "FC-x"}, {"pattern": "["}, {"redact": "yes"},
                    {"pattern": chr(0x202e)}, {"unknown": True}, {"glob": 123})
        for update in variants:
            value = dict(original, **update)
            path.write_text(json.dumps([value]), encoding="utf-8")
            with self.subTest(update=update), self.assertRaises(si.GateError):
                si.load_rules(path)
        value = dict(original, glob="*.md", exclude_glob="ignored.*", case_insensitive=True)
        path.write_text(json.dumps([value]), encoding="utf-8")
        rules = si.load_rules(path)
        files = [{"path": name, "text": chr(0x202e)} for name in ("yes.md", "no.txt", "ignored.md")]
        self.assertEqual(["yes.md"], [f["file"] for f in si.fixed_findings(files, rules, "test")])
        for text in ('{"key":1,"key":2}', '{"value":NaN}'):
            with self.assertRaises(si.GateError):
                si.json_load(text)

    def test_digest_is_order_independent_and_binds_mode_kind_and_name(self):
        root = {"kind": "skill", "name": "example"}
        files = [{"path": "b", "data": b"b", "executable": False}, {"path": "a", "data": b"a", "executable": False}]
        package = {"files": files, "prefix": ""}
        digest = self.gate.snapshot_digest([package], root)
        files.reverse()
        self.assertEqual(digest, self.gate.snapshot_digest([package], root))
        files[0]["executable"] = True
        self.assertNotEqual(digest, self.gate.snapshot_digest([package], root))
        files[0]["executable"] = False
        self.assertNotEqual(digest, self.gate.snapshot_digest([package], dict(root, name="other")))
        self.assertNotEqual(digest, self.gate.snapshot_digest([package], dict(root, kind="plugin")))

    def test_registered_alias_retains_requested_plugin_identity(self):
        market = self.market([{"name": "example", "source": "./example"}])
        source = self.plugin(parent=market)
        self.settings["marketplaces"][0]["name"] = "alias"
        self.settings["install_sources"] = {"example@alias": str(source)}
        self.save_settings()
        report = self.scan("example@alias")
        self.assertEqual("example@alias", report["destination"])
        self.assertEqual("installed", self.gate.install(report["digest"])["status"])
        self.assertTrue(any(c["args"][:3] == ["plugin", "install", "example@alias"] for c in self.calls()))

    def test_invalid_source_report_still_redacts_matching_text(self):
        token = "ghp_" + "A1b2" * 9
        report = self.scan(self.base / token)
        self.assertEqual("block", report["verdict"])
        self.assertNotIn(token, json.dumps(report))
        self.assertIn("[REDACTED]", report["target"])

    def test_network_failure_is_an_incomplete_scan_not_a_success(self):
        report = self.scan("https://github.com/owner/missing")
        self.assertEqual("block", report["verdict"])
        self.assertFalse(report["complete"])
        self.assertIsNone(report["digest"])

    def test_plugin_install_uses_original_project_after_working_directory_changes(self):
        market = self.market([{"name": "example", "source": "./example"}])
        source = self.plugin(parent=market)
        self.settings["install_sources"] = {"example@demo": str(source)}
        self.save_settings()
        report = self.scan("example@demo", scope="project")
        other = self.base / "other-project"
        other.mkdir()
        fresh_gate = si.Gate(config=self.config, cwd=other, http=self.http, now=lambda: self.clock,
                             claude_command=FAKE_CLAUDE)
        self.assertEqual("installed", fresh_gate.install(report["digest"])["status"])
        install = next(c for c in self.calls() if c["args"][:2] == ["plugin", "install"])
        self.assertEqual(str(self.cwd), install["cwd"])

    def test_fixed_finding_budget_is_shared_across_dependencies(self):
        market = self.market([{"name": "example", "source": "./example", "dependencies": ["dep"]},
                              {"name": "dep", "source": "./dep"}])
        self.plugin(parent=market, files={"note.md": chr(0x202e)})
        self.plugin("dep", parent=market, files={"note.md": chr(0x202e)})
        with mock.patch.object(si, "MAX_FIXED_FINDINGS", 1):
            report = self.scan("example@demo")
        self.assertEqual("block", report["verdict"])
        self.assertFalse(report["complete"])
        self.assertIn("Too many fixed-check findings", " ".join(report["reasons"]))


if __name__ == "__main__":
    unittest.main()
