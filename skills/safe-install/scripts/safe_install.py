#!/usr/bin/env python3
"""Policy 2 installation gate. Python 3.9+, standard library only."""

import argparse
import datetime
import fnmatch
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import zipfile


POLICY = "2"
MAX_FILES = 2000
MAX_TOTAL = 50 * 1024 * 1024
MAX_TEXT = 2 * 1024 * 1024
MAX_DOWNLOAD = 64 * 1024 * 1024
MAX_FIXED_FINDINGS = 10000
REVIEW_BYTES = 600_000
REFERENCES = Path(__file__).resolve().parents[1] / "references"
NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,63}\Z")
PLUGIN_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
SHA = re.compile(r"[0-9a-fA-F]{40}\Z")
SEVERITIES = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
INVENTORY_KEYS = (
    "skills", "commands", "agents", "hooks", "mcp_servers", "lsp_servers",
    "monitors", "bin", "dependencies", "unreviewed_files",
)
# Files Claude Code itself adds to an installed plugin copy (verified on 2.1.322:
# `.in_use/<pid>` markers for sessions using that version). Nothing else is exempt.
HOST_ADDED_PREFIXES = (".in_use/",)
MEDIA = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".bmp", ".avif",
    ".woff", ".woff2", ".ttf", ".otf",
}
ARCHIVES = {".zip", ".gz", ".tgz", ".tar", ".bz2", ".xz", ".7z", ".rar", ".mcpb", ".dxt"}


class GateError(Exception):
    pass


class UsageError(GateError):
    pass


def json_load(data):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise GateError("Duplicate JSON key")
            result[key] = value
        return result

    def invalid_constant(value):
        raise GateError("Non-finite JSON number")

    try:
        return json.loads(data, object_pairs_hook=pairs, parse_constant=invalid_constant)
    except (ValueError, UnicodeError) as exc:
        raise GateError("Invalid JSON: {}".format(exc)) from exc


def canonical(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def read_bounded(stream, limit):
    data = stream.read(limit + 1)
    if len(data) > limit:
        raise GateError("Size limit exceeded; content was not truncated or reviewed")
    return data


def safe_path(value):
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise GateError("Unsafe snapshot path")
    if value.startswith("/") or re.match(r"^[a-zA-Z]:", value):
        raise GateError("Absolute snapshot path")
    for part in value.split("/"):
        if (part in ("", ".", "..") or any(c in '<>:"|?*' or ord(c) < 32 for c in part)
                or part.endswith((".", " "))):
            raise GateError("Unsafe snapshot path component")
        base = part.split(".")[0].upper()
        if base in ("CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$", "CLOCK$") or re.fullmatch(r"(COM|LPT)[0-9\u00b9\u00b2\u00b3]", base):
            raise GateError("Windows reserved device name")
    return value


def no_links(path):
    if ".." in Path(path).parts:
        raise GateError("Parent traversal in a filesystem path is not allowed")
    current = Path(os.path.abspath(str(path)))
    for item in (current,) + tuple(current.parents):
        try:
            info = item.lstat()
        except OSError as exc:
            raise GateError("Cannot inspect path {}: {}".format(item, exc)) from exc
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise GateError("Symlinks and junctions are not allowed: {}".format(item))
        if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
            raise GateError("Special filesystem entry is not allowed: {}".format(item))


def make_directory(path):
    path = Path(path)
    missing = []
    current = path
    while not current.exists() and not current.is_symlink():
        missing.append(current)
        current = current.parent
    no_links(current)
    for item in reversed(missing):
        item.mkdir(mode=0o700)
    no_links(path)


def validate_paths(files):
    seen = set()
    components = {}
    for file in files:
        name = safe_path(file["path"])
        if name.casefold() in seen:
            raise GateError("Duplicate or case-colliding file: {}".format(name))
        seen.add(name.casefold())
        parts = name.split("/")
        for index in range(1, len(parts) + 1):
            part = "/".join(parts[:index])
            previous = components.setdefault(part.casefold(), part)
            if previous != part:
                raise GateError("Case-colliding paths: {} and {}".format(previous, part))
        for parent in PurePosixPath(name).parents:
            if str(parent).casefold() in seen:
                raise GateError("A file is also used as a directory")
    names = {f["path"].casefold() for f in files}
    for file in files:
        if any(str(p).casefold() in names for p in PurePosixPath(file["path"]).parents):
            raise GateError("A file is also used as a directory")


def walk_error(error):
    raise GateError("Cannot traverse filesystem tree: {}".format(error)) from error


def close_http_error(error):
    # An HTTPError without a body (fp is None) raises KeyError from close() on
    # Python 3.9; there is nothing to close then anyway.
    if getattr(error, "fp", None) is not None:
        error.close()


class GithubRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        parsed = urllib.parse.urlsplit(new_url)
        if (parsed.scheme != "https" or parsed.netloc not in
                ("github.com", "api.github.com", "codeload.github.com", "raw.githubusercontent.com")):
            raise GateError("Download redirected outside GitHub")
        return super().redirect_request(request, fp, code, message, headers, new_url)


def http_get(address, limit):
    parsed = urllib.parse.urlsplit(address)
    if parsed.scheme != "https" or parsed.netloc not in ("api.github.com", "codeload.github.com"):
        raise GateError("Unsupported download host")
    opener = urllib.request.build_opener(GithubRedirect())
    request = urllib.request.Request(address, headers={"User-Agent": "safe-install", "Accept": "application/vnd.github+json"})
    with opener.open(request, timeout=60) as response:
        return read_bounded(response, limit)


class Tree:
    def __init__(self, root=None, archive=None, archive_root=None, detail=None, commit=None):
        self.root = Path(root) if root is not None else None
        self.archive = archive
        self.archive_root = archive_root
        self.detail = detail or str(root)
        self.commit = commit
        if self.root is not None:
            no_links(self.root)
            if not self.root.is_dir():
                raise GateError("Target must be a directory")

    def has(self, relative):
        safe_path(relative)
        if self.root is not None:
            return (self.root / relative).exists() or (self.root / relative).is_symlink()
        name = self.archive_root + "/" + relative
        return any(f.filename.rstrip("/") == name or f.filename.startswith(name + "/")
                   for f in self.archive.infolist())

    def read(self, subdir="", exact=False):
        if subdir and subdir != ".":
            safe_path(subdir)
        else:
            subdir = ""
        files = []
        total = 0
        path_cases = {}

        def check_case(name):
            safe_path(name)
            parts = name.split("/")
            for index in range(1, len(parts) + 1):
                component = "/".join(parts[:index])
                previous = path_cases.setdefault(component.casefold(), component)
                if previous != component:
                    raise GateError("Case-colliding snapshot paths")

        def append(name, data, executable):
            nonlocal total
            check_case(name)
            total += len(data)
            if len(files) >= MAX_FILES or total > MAX_TOTAL:
                raise GateError("Snapshot exceeds the file count or total size limit")
            files.append({"path": name, "data": data, "executable": executable})

        if self.root is not None:
            start = self.root / subdir
            no_links(start)
            if exact:
                paths = [start]
            else:
                if not start.is_dir():
                    raise GateError("Target is not a folder")
                paths = []
                for directory, dirs, names in os.walk(str(start), followlinks=False, onerror=walk_error):
                    for child in dirs + names:
                        candidate = Path(directory) / child
                        no_links(candidate)
                        check_case(candidate.relative_to(start).as_posix())
                        if candidate.is_file():
                            paths.append(candidate)
                            if len(paths) > MAX_FILES:
                                raise GateError("Snapshot exceeds the file count limit")
            for candidate in paths:
                info = candidate.stat()
                if info.st_size > MAX_TOTAL:
                    raise GateError("File exceeds the snapshot size limit")
                with candidate.open("rb") as stream:
                    data = read_bounded(stream, MAX_TOTAL)
                name = candidate.name if exact else candidate.relative_to(start).as_posix()
                append(name, data, bool(info.st_mode & 0o111))
        else:
            wanted = self.archive_root + ("/" + subdir if subdir else "")
            prefix = wanted + "/"
            for item in self.archive.infolist():
                selected = item.filename == wanted if exact else item.filename.startswith(prefix)
                if not selected:
                    continue
                relative = item.filename[len(prefix):] if not exact else PurePosixPath(subdir).name
                mode = item.external_attr >> 16
                if stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR):
                    raise GateError("Archive contains a link or special file")
                if item.is_dir():
                    if relative.rstrip("/"):
                        check_case(relative.rstrip("/"))
                    continue
                if not relative:
                    continue
                if item.file_size > MAX_TOTAL:
                    raise GateError("Archive member exceeds the snapshot size limit")
                with self.archive.open(item) as stream:
                    data = read_bounded(stream, MAX_TOTAL)
                append(relative, data, bool(mode & 0o111))
        validate_paths(files)
        if exact and len(files) != 1:
            raise GateError("Required file is missing")
        return sorted(files, key=lambda file: file["path"])

    def json(self, relative):
        files = self.read(relative, exact=True)
        if len(files[0]["data"]) > MAX_TEXT:
            raise GateError("JSON file exceeds the text size limit")
        return json_load(files[0]["data"])


class Resolver:
    def __init__(self, gate):
        self.gate = gate
        self.archives = {}
        self.markets = {}
        self.packages = {}
        self.file_count = 0
        self.byte_count = 0

    def remember(self, package):
        pattern = NAME if package["kind"] == "skill" else PLUGIN_NAME
        if not isinstance(package["name"], str) or not pattern.fullmatch(package["name"]):
            raise GateError("Invalid package name")
        self.file_count += len(package["files"])
        self.byte_count += sum(len(file["data"]) for file in package["files"])
        if self.file_count > MAX_FILES or self.byte_count > MAX_TOTAL:
            raise GateError("Combined dependency snapshot exceeds resource limits")
        self.packages[package["key"]] = package

    def github(self, repo, ref="HEAD", subdir="", sha=None):
        if not isinstance(repo, str) or not isinstance(ref, str) or not isinstance(subdir, str):
            raise GateError("Malformed GitHub source")
        repo = repo.removesuffix(".git")
        parts = repo.split("/")
        if len(parts) != 2 or not all(re.fullmatch(r"[A-Za-z0-9_.-]+", p) and p not in (".", "..") for p in parts):
            raise GateError("Invalid GitHub owner/repository")
        if sha is not None:
            if not isinstance(sha, str) or not SHA.fullmatch(sha):
                raise GateError("Invalid pinned GitHub SHA")
        else:
            address = "https://api.github.com/repos/{}/commits/{}".format(repo, urllib.parse.quote(ref, safe=""))
            info = json_load(self.gate.http(address, MAX_DOWNLOAD))
            sha = info.get("sha") if isinstance(info, dict) else None
            if not isinstance(sha, str) or not SHA.fullmatch(sha):
                raise GateError("GitHub ref did not resolve to a commit")
        sha = sha.lower()
        key = (repo, sha)
        if key not in self.archives:
            data = self.gate.http("https://codeload.github.com/{}/zip/{}".format(repo, sha), MAX_DOWNLOAD)
            if len(data) > MAX_DOWNLOAD:
                raise GateError("Download exceeds the download size limit")
            try:
                self.archives[key] = zipfile.ZipFile(io.BytesIO(data))
            except zipfile.BadZipFile as exc:
                raise GateError("Invalid GitHub archive") from exc
        tree = Tree(archive=self.archives[key], archive_root=parts[1] + "-" + sha,
                    detail=repo + "@" + sha, commit=sha)
        return tree, subdir

    def github_url(self, target):
        parsed = urllib.parse.urlsplit(target)
        if parsed.scheme != "https" or parsed.netloc != "github.com" or parsed.query or parsed.fragment:
            raise GateError("Only public HTTPS github.com URLs without credentials are supported")
        parts = urllib.parse.unquote(parsed.path).strip("/").split("/")
        if len(parts) < 2:
            raise GateError("GitHub URL needs an owner and repository")
        repo = "/".join(parts[:2]).removesuffix(".git")
        if len(parts) == 2:
            return self.github(repo)
        if len(parts) < 4 or parts[2] not in ("tree", "blob"):
            raise GateError("Use a GitHub tree or blob URL")
        tail = parts[3:]
        for length in range(len(tail), 0, -1):
            try:
                address = "https://api.github.com/repos/{}/commits/{}".format(
                    repo, urllib.parse.quote("/".join(tail[:length]), safe=""))
                info = json_load(self.gate.http(address, MAX_DOWNLOAD))
            except urllib.error.HTTPError as exc:
                close_http_error(exc)
                if exc.code in (404, 422):
                    continue
                raise
            sha = info.get("sha") if isinstance(info, dict) else None
            if not isinstance(sha, str) or not SHA.fullmatch(sha):
                raise GateError("Invalid GitHub commit response")
            remaining = tail[length:]
            if parts[2] == "blob":
                if not remaining:
                    raise GateError("Blob URL has no file path")
                remaining = remaining[:-1]
            tree, subdir = self.github(repo, subdir="/".join(remaining), sha=sha)
            if parts[2] == "blob":
                for count in range(len(remaining), -1, -1):
                    folder = "/".join(remaining[:count])
                    skill_path = "/".join(filter(None, (folder, "SKILL.md")))
                    if tree.has(skill_path):
                        return tree, folder
                raise GateError("Blob URL is not inside a skill")
            return tree, subdir
        raise GateError("No GitHub ref in the URL resolves to a commit")

    def market(self, source, registered=False):
        key = ("registered:" if registered else "source:") + source
        if key in self.markets:
            return self.markets[key]
        if registered:
            result, _ = self.gate.claude(["plugin", "marketplace", "list", "--json"])
            data = json_load(result)
            entries = data.get("marketplaces", data) if isinstance(data, dict) else data
            if isinstance(entries, dict):
                entries = [dict(value, name=name) for name, value in entries.items()]
            if not isinstance(entries, list):
                raise GateError("Invalid marketplace list")
            matches = [m for m in entries if isinstance(m, dict) and m.get("name") == source]
            if len(matches) != 1 or not isinstance(matches[0].get("installLocation"), str):
                raise GateError("Marketplace is not registered with an installLocation")
            location = matches[0]["installLocation"]
            if not Path(location).is_absolute():
                raise GateError("Marketplace installLocation must be absolute")
            tree, subdir = Tree(root=location), ""
        elif (self.gate.cwd / source).exists() or Path(source).is_absolute() or source.startswith("."):
            tree, subdir = Tree(root=self.gate.local(source)), ""
        elif source.startswith("https://"):
            tree, subdir = self.github_url(source)
        else:
            tree, subdir = self.github(source)
        manifest_path = "/".join(filter(None, (subdir, ".claude-plugin/marketplace.json")))
        catalog = tree.json(manifest_path)
        if not isinstance(catalog, dict) or not isinstance(catalog.get("plugins"), list) or not isinstance(catalog.get("name"), str):
            raise GateError("Malformed marketplace catalog")
        market = {"tree": tree, "subdir": subdir, "catalog": catalog,
                  "name": source if registered else catalog["name"],
                  "source": source, "registered": registered}
        self.markets[key] = market
        return market

    def marketplace_plugin(self, name, market, depth=0):
        identity = name + "@" + market["name"]
        if identity in self.packages:
            return self.packages[identity]
        if depth > 3:
            raise GateError("Plugin dependencies exceed three levels")
        entries = [e for e in market["catalog"]["plugins"] if isinstance(e, dict) and e.get("name") == name]
        if len(entries) != 1:
            raise GateError("Dependency or plugin could not be resolved uniquely: " + identity)
        entry = entries[0]
        source = entry.get("source")
        tree = market["tree"]
        if isinstance(source, str) and not source.startswith(("https://", "git@", "/")):
            plugin_root = market["catalog"].get("metadata", {}).get("pluginRoot", "")
            if not isinstance(plugin_root, str):
                raise GateError("Invalid marketplace pluginRoot")
            source_path = source[2:] if source.startswith("./") else "/".join(filter(None, (plugin_root.removeprefix("./"), source)))
            source_path = "" if source_path in ("", ".") else safe_path(source_path)
            subdir = "/".join(filter(None, (market["subdir"], source_path)))
        elif isinstance(source, dict):
            kind = source.get("source")
            if kind == "github":
                tree, subdir = self.github(source.get("repo", ""), source.get("ref", "HEAD"),
                                          source.get("path", ""), source.get("sha"))
            elif kind in ("url", "git-subdir"):
                parsed = urllib.parse.urlsplit(source.get("url", ""))
                if parsed.scheme != "https" or parsed.netloc != "github.com" or parsed.query or parsed.fragment:
                    raise GateError("Unsupported source, not reviewed: non-GitHub git")
                repo = parsed.path.strip("/").removesuffix(".git")
                tree, subdir = self.github(repo, source.get("ref", "HEAD"),
                                          source.get("path", ""), source.get("sha"))
            else:
                raise GateError("Unsupported source, not reviewed: {}".format(kind))
        else:
            raise GateError("Unsupported source, not reviewed")
        files = tree.read(subdir)
        if any(f["path"].split("/")[0] == ".safe-install" for f in files):
            raise GateError("Candidate uses the gate's reserved .safe-install namespace")
        files.append({"path": ".safe-install/marketplace-entry.json", "data": canonical(entry), "executable": False})
        source_info = {"type": "marketplace", "detail": identity, "commit": tree.commit}
        if market["registered"]:
            install_args = [identity]
        else:
            install_args = [name, "--marketplace", market["source"]]
        package = {"name": name, "kind": "plugin", "key": identity, "files": files,
                   "source": source_info, "plugin_id": identity, "install_args": install_args}
        self.remember(package)
        if not isinstance(entry.get("dependencies", []), list):
            raise GateError("Malformed marketplace dependencies")
        dependency_values = list(entry.get("dependencies", []))
        for file in files:
            if file["path"] == ".claude-plugin/plugin.json":
                manifest = json_load(file["data"])
                if not isinstance(manifest, dict):
                    raise GateError("Plugin manifest is not an object")
                if not isinstance(manifest.get("dependencies", []), list):
                    raise GateError("Malformed plugin dependencies")
                dependency_values.extend(manifest.get("dependencies", []))
        for dependency in dependency_values:
            if isinstance(dependency, str):
                dep_name, separator, dep_market = dependency.partition("@")
            elif isinstance(dependency, dict) and isinstance(dependency.get("name"), str):
                dep_name = dependency["name"]
                dep_market = dependency.get("marketplace", "")
                separator = bool(dep_market)
            else:
                raise GateError("Malformed plugin dependency")
            if not isinstance(dep_market, str):
                raise GateError("Malformed dependency marketplace")
            dep_context = self.market(dep_market, registered=True) if separator and dep_market != market["name"] else market
            self.marketplace_plugin(dep_name, dep_context, depth + 1)
        return package

    def target(self, target, forced=None, marketplace=None):
        if marketplace:
            market = self.market(marketplace)
            return self.marketplace_plugin(target, market), None
        if "@" in target and not any(c in target for c in "/\\"):
            name, market_name = target.split("@", 1)
            return self.marketplace_plugin(name, self.market(market_name, registered=True)), None
        if target.startswith("https://"):
            tree, subdir = self.github_url(target)
            source = {"type": "github", "detail": tree.detail + (":" + subdir if subdir else ""), "commit": tree.commit}
        else:
            tree, subdir = Tree(root=self.gate.local(target)), ""
            source = {"type": "local", "detail": str(tree.root), "commit": None}
        catalog_path = "/".join(filter(None, (subdir, ".claude-plugin/marketplace.json")))
        if not forced and tree.has(catalog_path):
            catalog = tree.json(catalog_path)
            if not isinstance(catalog, dict) or not isinstance(catalog.get("plugins"), list):
                raise GateError("Malformed marketplace catalog")
            return None, [e["name"] for e in catalog["plugins"] if isinstance(e, dict) and isinstance(e.get("name"), str)]
        files = tree.read(subdir)
        if any(f["path"].split("/")[0] == ".safe-install" for f in files):
            raise GateError("Candidate uses the gate's reserved .safe-install namespace")
        paths = {f["path"] for f in files}
        has_skill = "SKILL.md" in paths
        has_plugin = ".claude-plugin/plugin.json" in paths or any(
            p.split("/")[0] in ("commands", "agents", "hooks", "skills", "monitors", "bin")
            or p in (".mcp.json", ".lsp.json") for p in paths)
        if has_skill and has_plugin and not forced:
            raise GateError("Ambiguous kind: rescan with --type skill or --type plugin")
        children = sorted({p.split("/")[0] for p in paths if p.count("/") == 1 and p.endswith("/SKILL.md")})
        if not forced and not has_skill and ".claude-plugin/plugin.json" not in paths and children:
            return None, children
        kind = forced or ("skill" if has_skill else "plugin" if has_plugin else None)
        if kind is None or (kind == "skill" and not has_skill) or (kind == "plugin" and not has_plugin):
            raise GateError("Target has no supported skill or plugin layout")
        name = PurePosixPath(subdir).name if subdir else (tree.root.name if tree.root else tree.archive_root.rsplit("-", 1)[0])
        if kind == "plugin" and ".claude-plugin/plugin.json" in paths:
            manifest = json_load(next(f["data"] for f in files if f["path"] == ".claude-plugin/plugin.json"))
            name = manifest.get("name", name)
        package = {"name": name, "kind": kind, "key": name, "files": files,
                   "source": source, "plugin_id": name, "install_args": None}
        self.remember(package)
        if kind == "plugin":
            manifest = json_load(next(f["data"] for f in files if f["path"] == ".claude-plugin/plugin.json")) if ".claude-plugin/plugin.json" in paths else {}
            dependencies = manifest.get("dependencies", [])
            if not isinstance(dependencies, list):
                raise GateError("Malformed plugin dependencies")
            for dependency in dependencies:
                if isinstance(dependency, str) and "@" in dependency:
                    dep_name, dep_market = dependency.split("@", 1)
                elif isinstance(dependency, dict) and isinstance(dependency.get("name"), str) and isinstance(dependency.get("marketplace"), str):
                    dep_name, dep_market = dependency["name"], dependency["marketplace"]
                else:
                    raise GateError("Standalone plugin dependency needs an explicit marketplace")
                self.marketplace_plugin(dep_name, self.market(dep_market, registered=True), 1)
        return package, None


def load_rules(path):
    if not path.exists():
        return None
    rules = json_load(path.read_bytes())
    if not isinstance(rules, list):
        raise GateError("Fixed-check rules must be an array")
    seen = set()
    compiled = []
    required = {"id", "severity", "name", "description", "pattern", "case_insensitive", "redact", "source"}
    for rule in rules:
        if not isinstance(rule, dict) or not required <= rule.keys() or rule.keys() - required - {"glob", "exclude_glob"}:
            raise GateError("Malformed fixed-check rule")
        if (not isinstance(rule["id"], str) or not re.fullmatch(r"FC-[0-9]{3}", rule["id"])
                or rule["id"] in seen or rule["severity"] not in ("critical", "high", "medium", "low")):
            raise GateError("Invalid fixed-check identity or severity")
        seen.add(rule["id"])
        if any(not isinstance(rule[k], str) or not rule[k] for k in ("name", "description", "pattern", "source")):
            raise GateError("Invalid fixed-check text fields")
        if any(type(rule[k]) is not bool for k in ("case_insensitive", "redact")):
            raise GateError("Invalid fixed-check flags")
        if any(unicodedata.category(c) in ("Cf", "Cc") for c in rule["pattern"]):
            raise GateError("Rule patterns must escape invisible characters")
        for key in ("glob", "exclude_glob"):
            if key in rule and not (isinstance(rule[key], str) or
                                    isinstance(rule[key], list) and all(isinstance(s, str) for s in rule[key])):
                raise GateError("Invalid fixed-check file filter")
        try:
            rule = dict(rule)
            rule["compiled"] = re.compile(rule["pattern"], re.I if rule["case_insensitive"] else 0)
        except re.error as exc:
            raise GateError("Invalid fixed-check regular expression") from exc
        compiled.append(rule)
    return compiled


def fixed_findings(files, rules, package, limit=None):
    if limit is None:
        limit = MAX_FIXED_FINDINGS
    findings = []
    for file in files:
        text = file.get("text")
        if text is None:
            continue
        for rule in rules or []:
            def matches_filter(key):
                filters = rule.get(key, [])
                if isinstance(filters, str):
                    filters = [filters]
                return any(fnmatch.fnmatchcase(file["path"], item) for item in filters)
            if ("glob" in rule and not matches_filter("glob")) or matches_filter("exclude_glob"):
                continue
            line, previous = 1, 0
            for match in rule["compiled"].finditer(text):
                if len(findings) >= limit:
                    raise GateError("Too many fixed-check findings for a complete report")
                line += text.count("\n", previous, match.start())
                previous = match.start()
                findings.append({"id": rule["id"], "severity": rule["severity"].upper(), "name": rule["name"],
                                 "description": rule["description"], "file": file["path"],
                                 "line": line, "package": package})
    return findings


def display(value, rules=()):
    if isinstance(value, str):
        for rule in rules or []:
            if rule["redact"]:
                value = rule["compiled"].sub("[REDACTED]", value)
        return "".join(("\\u{:04x}".format(ord(c)) if ord(c) <= 0xffff else
                        "\\U{:08x}".format(ord(c))) if unicodedata.category(c) in ("Cc", "Cf") else c for c in value)
    if isinstance(value, list):
        return [display(item, rules) for item in value]
    if isinstance(value, dict):
        return {display(k, rules): display(v, rules) for k, v in value.items()}
    return value


def schema_validate(value, schema):
    types = {"object": dict, "array": list, "string": str, "boolean": bool, "integer": int}
    expected = types.get(schema.get("type"))
    if expected is not None and type(value) is not expected:
        raise GateError("AI review field has the wrong type")
    if "enum" in schema and value not in schema["enum"]:
        raise GateError("AI review field has an invalid value")
    if isinstance(value, dict):
        if not set(schema.get("required", [])) <= value.keys():
            raise GateError("AI review is missing required fields")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False and value.keys() - properties.keys():
            raise GateError("AI review contains unknown fields")
        for key, child in value.items():
            if key in properties:
                schema_validate(child, properties[key])
    elif isinstance(value, list):
        if len(value) > schema.get("maxItems", len(value)):
            raise GateError("AI review has too many items")
        for child in value:
            schema_validate(child, schema.get("items", {}))
    elif isinstance(value, str):
        if len(value) > schema.get("maxLength", len(value)):
            raise GateError("AI review string exceeds schema limit")
    elif type(value) is int and value < schema.get("minimum", value):
        raise GateError("AI review integer is outside schema bounds")


def empty_inventory():
    return {key: [] for key in INVENTORY_KEYS}


def media_signature(suffix, data):
    headers = {
        ".png": (b"\x89PNG\r\n\x1a\n",), ".jpg": (b"\xff\xd8\xff",), ".jpeg": (b"\xff\xd8\xff",),
        ".gif": (b"GIF87a", b"GIF89a"), ".bmp": (b"BM",), ".ico": (b"\x00\x00\x01\x00",),
        ".woff": (b"wOFF",), ".woff2": (b"wOF2",), ".ttf": (b"\x00\x01\x00\x00", b"true", b"typ1"),
        ".otf": (b"OTTO",),
    }
    if suffix == ".webp":
        return data.startswith(b"RIFF") and data[8:12] == b"WEBP"
    if suffix == ".avif":
        return data[4:8] == b"ftyp" and any(data[i:i + 4] in (b"avif", b"avis") for i in range(8, min(len(data), 64), 4))
    return any(data.startswith(header) for header in headers.get(suffix, ()))


def file_inventory(package):
    result = empty_inventory()
    for file in package["files"]:
        p = file["path"]
        if p == "SKILL.md" or p.endswith("/SKILL.md"):
            result["skills"].append(p)
        for directory in ("commands", "agents", "hooks", "monitors", "bin"):
            if p.startswith(directory + "/"):
                result[directory].append(p)
        if p == ".mcp.json":
            result["mcp_servers"].append(p)
        if p == ".lsp.json":
            result["lsp_servers"].append(p)
        if file.get("unreviewed"):
            result["unreviewed_files"].append(p)
    return result


def parse_inventory(text):
    result = empty_inventory()
    aliases = {"skills": "skills", "commands": "commands", "agents": "agents", "hooks": "hooks",
               "mcp servers": "mcp_servers", "lsp servers": "lsp_servers", "monitors": "monitors",
               "bin": "bin", "executables": "bin", "dependencies": "dependencies"}
    section = False
    found = False
    for line in text.splitlines():
        if "Component inventory" in line:
            section = True
            continue
        if not section:
            continue
        match = re.match(r"\s*(?:[-*]\s*)?([A-Za-z ]+)\s*\((\d+)\)\s*:?\s*(.*)", line)
        if not match:
            continue
        key = aliases.get(match.group(1).strip().lower())
        if key is None:
            continue
        found = True
        count = int(match.group(2))
        if count > MAX_FILES:
            raise GateError("Component inventory exceeds resource limits")
        # Drop trailing notes such as "(harness-only — no model context cost)".
        names = re.sub(r"\s{2,}\(.*\)\s*$", "", match.group(3))
        values = [s.strip() for s in names.split(",") if s.strip()]
        result[key] = values if len(values) == count else ["{} #{}".format(key, i + 1) for i in range(count)]
    if not section or not found:
        raise GateError("Claude Code did not return a component inventory")
    return result


class Gate:
    def __init__(self, config=None, cwd=None, http=None, now=None, references=None):
        self.cwd = Path(cwd or os.getcwd()).absolute()
        self.config = Path(config or os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude").absolute()
        self.http = http or http_get
        self.now = now or (lambda: datetime.datetime.now(datetime.timezone.utc))
        self.references = Path(references or REFERENCES)
        self.rules = None

    def local(self, target):
        # Normalise `..` in a user-given path; links are still refused by Tree.
        return Path(os.path.abspath(str(self.cwd / target)))

    def installed_entries(self, cwd):
        output, _ = self.claude(["plugin", "list", "--json"], cwd=cwd)
        listing = json_load(output)
        entries = listing.get("plugins", listing) if isinstance(listing, dict) else listing
        if isinstance(entries, dict):
            entries = [dict(item, id=key) for key, values in entries.items()
                       for item in (values if isinstance(values, list) else [values])]
        if not isinstance(entries, list):
            raise GateError("Invalid installed plugin list")
        return [e for e in entries if isinstance(e, dict)]

    def claude(self, args, stdin=None, review=False, allow_failure=False, cwd=None):
        hook = os.environ.get("SAFE_INSTALL_CLAUDE")
        if hook is not None:
            command = json_load(hook)
            if not isinstance(command, list) or not command or not all(isinstance(x, str) for x in command):
                raise GateError("SAFE_INSTALL_CLAUDE must be a JSON argv list")
        else:
            executable = shutil.which("claude")
            if not executable:
                raise GateError("Native Claude Code executable is not available")
            if Path(executable).suffix.lower() in (".cmd", ".bat"):
                raise GateError("Claude Code .cmd/.bat shims are refused; use its native executable")
            command = [str(Path(executable).absolute())]
        env = {k: v for k, v in os.environ.items() if k.upper() != "CLAUDECODE"}
        env["CLAUDE_CONFIG_DIR"] = str(self.config)
        env["NO_COLOR"] = "1"
        working_directory = Path(cwd or self.cwd)
        if not review:
            no_links(working_directory)
        with tempfile.TemporaryDirectory(prefix="safe-install-call-") as directory:
            try:
                # Files, rather than PIPE buffers, bound memory even for noisy hosts.
                with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
                    result = subprocess.run(command + list(args), input=stdin, stdout=output, stderr=errors,
                                            cwd=directory if review else str(working_directory), env=env,
                                            timeout=300 if review else 90, shell=False)
                    output.seek(0)
                    data = read_bounded(output, MAX_DOWNLOAD)
                    errors.seek(0)
                    read_bounded(errors, MAX_DOWNLOAD)
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise GateError("Claude Code call failed: {}".format(exc)) from exc
        if result.returncode and not allow_failure:
            raise GateError("Claude Code call failed with exit code {}".format(result.returncode))
        return data, result.returncode

    def base_report(self, target, scope):
        return {"policy": POLICY, "digest": None, "created_at": self.now().isoformat(),
                "target": target, "kind": None, "name": None, "scope": scope,
                "source": {"type": "local", "detail": target, "commit": None},
                "destination": None, "inventory": empty_inventory(), "checks": [],
                "complete": False, "verdict": "block", "reasons": [], "findings": [], "choices": None}

    def classify(self, package, report):
        for file in package["files"]:
            data = file["data"]
            suffix = PurePosixPath(file["path"]).suffix.lower()
            try:
                text = data.decode("utf-8")
                if "\x00" in text:
                    raise UnicodeError("NUL in content")
            except UnicodeError:
                text = None
            if suffix in ARCHIVES or (text is None and not (suffix in MEDIA and media_signature(suffix, data))):
                report["complete"] = False
                report["reasons"].append("Unreviewable binary or archive: {} ({})".format(file["path"], package["name"]))
            elif text is None:
                file["unreviewed"] = True
            elif len(data) > MAX_TEXT:
                report["complete"] = False
                report["reasons"].append("Text file exceeds 2 MiB: {}".format(file["path"]))
            file["text"] = text if suffix not in ARCHIVES else None

    def snapshot_digest(self, packages, root):
        entries = []
        for package in packages:
            for file in package["files"]:
                entries.append([package.get("prefix", "") + file["path"], bool(file["executable"]), sha256(file["data"])])
        return sha256(canonical([POLICY, root["kind"], root["name"], sorted(entries)]))

    def stage(self, packages, root, digest):
        base = self.config / "safe-install" / "staged"
        make_directory(base)
        stage = base / digest
        if stage.exists() or stage.is_symlink():
            # Same digest = same files: an earlier scan that was never discarded.
            # Replace it so a rescan doesn't block on leftovers.
            self.discard(digest)
        temporary = Path(tempfile.mkdtemp(prefix=".snapshot-", dir=str(base)))
        try:
            for package in packages:
                for file in package["files"]:
                    target = temporary / "files" / (package["prefix"] + file["path"])
                    make_directory(target.parent)
                    with target.open("xb") as stream:
                        stream.write(file["data"])
                    target.chmod(0o755 if file["executable"] else 0o644)
            temporary.rename(stage)
        finally:
            if temporary.exists():
                shutil.rmtree(str(temporary))
        return stage

    def validate_manifest(self, package, directory, report):
        output, code = self.claude(["plugin", "validate", "--strict", "--json", str(directory)], allow_failure=True)
        data = json_load(output)
        if not isinstance(data, dict) or not isinstance(data.get("manifest"), dict) or not isinstance(data.get("contents", []), list):
            raise GateError("Malformed plugin validation result")
        sections = [data["manifest"]] + data.get("contents", [])
        count = 0
        for section in sections:
            if not isinstance(section, dict):
                raise GateError("Malformed plugin validation section")
            for key, severity in (("errors", "HIGH"), ("warnings", "LOW")):
                values = section.get(key, [])
                if not isinstance(values, list):
                    raise GateError("Malformed validation diagnostics")
                for item in values:
                    if isinstance(item, str):
                        description, file, line = item, section.get("path"), 0
                    elif isinstance(item, dict) and isinstance(item.get("message"), str):
                        description = item["message"]
                        file = item.get("file", item.get("path", section.get("path")))
                        line = item.get("line", 0)
                    else:
                        raise GateError("Malformed validation diagnostic")
                    if file is not None and not isinstance(file, str) or type(line) is not int or line < 0:
                        raise GateError("Malformed validation diagnostic location")
                    report["findings"].append({"id": "VAL", "severity": severity, "name": "Manifest " + key[:-1],
                                               "description": description, "file": file, "line": line, "package": package["name"]})
                    count += 1
        if code and not count:
            raise GateError("Manifest validator failed without diagnostics")

    def review_batches(self, packages):
        fragments = []
        for package in packages:
            for file in package["files"]:
                if file.get("text") is None:
                    continue
                data = file["text"].encode("utf-8")
                position, offset = 0, 0
                while position < len(data) or not data and position == 0:
                    end = min(position + REVIEW_BYTES, len(data))
                    while end < len(data) and data[end] & 0xC0 == 0x80:
                        end -= 1
                    # Prefer whole LF-delimited lines, but also handle large single
                    # lines without truncating them or splitting UTF-8 characters.
                    newline = data.rfind(b"\n", position, end)
                    if end < len(data) and newline >= position:
                        end = newline + 1
                    text = data[position:end].decode("utf-8")
                    fragments.append((package, file, text, offset))
                    offset += text.count("\n")
                    position = end
                    if not data:
                        break
        batches, current, size = [], [], 0
        keys = set()
        for fragment in fragments:
            package, file, text, offset = fragment
            key = package["prefix"] + file["path"]
            length = len(text.encode("utf-8"))
            if current and (size + length > REVIEW_BYTES or key in keys):
                batches.append(current)
                current, size, keys = [], 0, set()
            current.append(fragment)
            keys.add(key)
            size += length
        if current:
            batches.append(current)
        return batches

    def ai_review(self, packages, report):
        schema = json_load((self.references / "review-schema.json").read_bytes())
        prompt = (self.references / "reviewer-prompt.md").read_text(encoding="utf-8")
        full_list = [p["prefix"] + f["path"] for p in packages for f in p["files"]]
        batches = self.review_batches(packages)
        if not batches:
            raise GateError("No reviewable text files")
        for batch in batches:
            mapping = {p["prefix"] + f["path"]: (p, f, text, offset) for p, f, text, offset in batch}
            payload = {"policy": POLICY, "digest": report["digest"], "inventory": report["inventory"],
                       "fixed_check_findings": [f for f in report["findings"] if f["id"].startswith("FC-")],
                       "full_file_list": full_list,
                       "files": [{"path": key, "content": value[2], "start_line": value[3] + 1}
                                 for key, value in mapping.items()]}
            args = ["-p", "--safe-mode", "--restricted", "--tools", "", "--disallowedTools", "mcp__*",
                    "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}', "--setting-sources", "",
                    "--settings", '{"disableAllHooks":true}', "--no-chrome", "--no-session-persistence",
                    "--output-format", "json", "--json-schema", canonical(schema).decode("ascii"),
                    "--system-prompt", prompt]
            output, _ = self.claude(args, canonical(payload), review=True)
            envelope = json_load(output)
            if (not isinstance(envelope, dict) or envelope.get("type") != "result" or
                    envelope.get("subtype") != "success" or envelope.get("is_error") is not False):
                raise GateError("AI review did not return a successful result")
            answer = envelope.get("structured_output")
            schema_validate(answer, schema)
            if answer["policy"] != POLICY or answer["digest"] != report["digest"]:
                raise GateError("AI review digest or policy mismatch")
            reviewed = answer["reviewed_files"]
            if len(reviewed) != len(mapping) or set(reviewed) != set(mapping):
                raise GateError("AI review did not cover exactly every file in this call")
            for finding in answer["findings"]:
                key = finding["file"]
                if key not in mapping:
                    raise GateError("AI finding cites a file outside this review")
                package, file, text, offset = mapping[key]
                if finding["line"] > len(text.split("\n")):
                    raise GateError("AI finding cites a line outside this file")
                finding = dict(finding, id="AI", package=package["name"], file=file["path"],
                               line=finding["line"] + offset)
                for fixed in report["findings"]:
                    if (fixed["id"].startswith("FC-") and fixed["package"] == finding["package"] and
                            fixed["file"] == finding["file"] and fixed["line"] == finding["line"] and
                            SEVERITIES.index(finding["severity"]) > SEVERITIES.index(fixed["severity"])):
                        fixed["severity"] = finding["severity"]
                report["findings"].append(finding)
            if not answer["complete"]:
                report["complete"] = False
                report["reasons"].append("AI review incomplete: " + answer["summary"])

    def scan(self, target, scope="user", forced=None, marketplace=None):
        report = self.base_report(target, scope)
        stage = None
        try:
            try:
                self.rules = load_rules(self.references / "fixed-checks.json")
            except GateError as exc:
                self.failed_check(report, "fixed checks", exc)
                return display(report), 0
            resolver = Resolver(self)
            root, choices = resolver.target(target, forced, marketplace)
            if choices is not None:
                report["choices"] = choices
                report["verdict"] = None
                return display(report), 0
            if root["kind"] == "skill" and scope == "local":
                raise UsageError("The local scope is only supported for plugins")
            packages = [root] + sorted((p for p in resolver.packages.values() if p is not root), key=lambda p: p["key"])
            for package in packages:
                package["prefix"] = "" if package is root else ".safe-install/dependencies/" + sha256(package["key"].encode())[:24] + "/"
                validate_paths(package["files"])
            report.update(name=root["name"], kind=root["kind"], source=root["source"], complete=True)
            destination = (self.config / "skills" if scope == "user" else self.cwd / ".claude" / "skills") / root["name"]
            report["destination"] = str(destination) if root["kind"] == "skill" else root["plugin_id"]
            report["digest"] = self.snapshot_digest(packages, root)
            stage = self.stage(packages, root, report["digest"])
            for package in packages:
                self.classify(package, report)
            try:
                report["checks"].append({"name": "fixed checks", "status": "ran" if self.rules is not None else "not available",
                                         "detail": "Fixed rule file loaded" if self.rules is not None else "Rules file is missing"})
                for package in packages:
                    remaining = MAX_FIXED_FINDINGS - len(report["findings"])
                    report["findings"].extend(fixed_findings(package["files"], self.rules, package["name"], remaining))
            except GateError as exc:
                self.failed_check(report, "fixed checks", exc)
            for package in packages:
                directory = stage / "files" / package["prefix"]
                inventory = file_inventory(package)
                if package["kind"] == "plugin":
                    try:
                        self.validate_manifest(package, directory, report)
                        report["checks"].append({"name": "manifest validation", "status": "ran", "detail": package["name"]})
                    except GateError as exc:
                        self.failed_check(report, "manifest validation", exc)
                    try:
                        output, _ = self.claude(["--plugin-dir", str(directory), "plugin", "details", package["name"]])
                        native = parse_inventory(output.decode("utf-8"))
                        native["unreviewed_files"] = inventory["unreviewed_files"]
                        inventory = native
                        report["checks"].append({"name": "inventory", "status": "ran", "detail": package["name"]})
                    except (GateError, UnicodeError) as exc:
                        self.failed_check(report, "inventory", exc)
                else:
                    report["checks"].append({"name": "manifest validation", "status": "not applicable", "detail": "Skill has no plugin manifest"})
                    report["checks"].append({"name": "inventory", "status": "ran", "detail": "Built from snapshot"})
                for key in INVENTORY_KEYS:
                    report["inventory"][key].extend(inventory[key] if package is root else
                                                    [package["name"] + ": " + item for item in inventory[key]])
            report["inventory"]["dependencies"] = [p["key"] for p in packages if p is not root]
            try:
                self.ai_review(packages, report)
                report["checks"].append({"name": "AI review", "status": "ran", "detail": "Every text fragment reviewed"})
            except (GateError, OSError) as exc:
                self.failed_check(report, "AI review", exc)
            self.verdict(report)
            state = {"policy": POLICY, "kind": root["kind"], "name": root["name"], "cwd": str(self.cwd),
                     "destination": report["destination"], "packages": []}
            for package in packages:
                saved = {k: v for k, v in package.items() if k != "files"}
                saved["files"] = [{k: f[k] for k in ("path", "executable")} for f in package["files"]]
                state["packages"].append(saved)
            (stage / "state.json").write_bytes(canonical(state))
            safe_report = display(report, self.rules)
            (stage / "report.json").write_bytes(canonical(safe_report))
            return safe_report, 0
        except UsageError:
            raise
        except (GateError, urllib.error.URLError) as exc:
            if isinstance(exc, urllib.error.HTTPError):
                close_http_error(exc)
            report["complete"] = False
            report["verdict"] = "block"
            report["reasons"].append(str(exc))
            if stage is None:
                report["digest"] = None
            safe_report = display(report, self.rules)
            if stage is not None:
                (stage / "report.json").write_bytes(canonical(safe_report))
            return safe_report, 0

    @staticmethod
    def failed_check(report, name, error):
        report["complete"] = False
        report["reasons"].append("{}: {}".format(name, error))
        report["checks"].append({"name": name, "status": "failed", "detail": str(error)})

    @staticmethod
    def verdict(report):
        if not report["complete"] or any(f["severity"] == "CRITICAL" for f in report["findings"]):
            report["verdict"] = "block"
        else:
            report["verdict"] = "ask" if report["findings"] else "clean"

    def staged(self, digest):
        if not isinstance(digest, str) or not DIGEST.fullmatch(digest):
            raise UsageError("Digest must be 64 lowercase hexadecimal characters")
        stage = self.config / "safe-install" / "staged" / digest
        no_links(stage)
        return stage

    def load_staged(self, digest):
        stage = self.staged(digest)
        no_links(stage / "report.json")
        no_links(stage / "state.json")
        report = json_load((stage / "report.json").read_bytes())
        state = json_load((stage / "state.json").read_bytes())
        if report.get("policy") != POLICY or state.get("policy") != POLICY or report.get("digest") != digest:
            raise GateError("Staged report identity mismatch")
        if report.get("verdict") not in ("block", "ask", "clean") or type(report.get("complete")) is not bool:
            raise GateError("Invalid staged report")
        saved_verdict = report["verdict"]
        self.verdict(report)
        if report["verdict"] != saved_verdict:
            raise GateError("Staged verdict does not match findings")
        try:
            created = datetime.datetime.fromisoformat(report["created_at"].replace("Z", "+00:00"))
            age = (self.now() - created).total_seconds()
        except (ValueError, KeyError, TypeError) as exc:
            raise GateError("Invalid report timestamp") from exc
        if age < 0 or age > 30 * 60:
            raise GateError("Report is stale or has a future timestamp; scan again")
        packages = state["packages"]
        expected = set()
        for package in packages:
            for file in package["files"]:
                global_path = safe_path(package["prefix"] + file["path"])
                expected.add(global_path)
                path = stage / "files" / global_path
                no_links(path)
                with path.open("rb") as stream:
                    file["data"] = read_bounded(stream, MAX_TOTAL)
                if os.name != "nt" and bool(path.stat().st_mode & 0o111) != file["executable"]:
                    raise GateError("Staged executable bit changed")
        actual = {f["path"] for f in Tree(root=stage / "files").read()}
        if actual != expected or self.snapshot_digest(packages, state) != digest:
            raise GateError("Staged snapshot digest mismatch")
        return stage, report, state

    def verify_copy(self, destination, package):
        actual = Tree(root=destination).read()
        actual = [f for f in actual if not f["path"].startswith(HOST_ADDED_PREFIXES)]
        expected = [f for f in package["files"] if f["path"] != ".safe-install/marketplace-entry.json"]
        if {f["path"] for f in actual} != {f["path"] for f in expected}:
            raise GateError("Installed file list differs from reviewed snapshot")
        by_name = {f["path"]: f for f in actual}
        for file in expected:
            installed = by_name[file["path"]]
            if sha256(installed["data"]) != sha256(file["data"]):
                raise GateError("Installed bytes differ from reviewed snapshot")
            # Windows does not represent POSIX executable permission bits.
            if os.name != "nt" and installed["executable"] != file["executable"]:
                raise GateError("Installed executable bit differs from reviewed snapshot")

    def install(self, digest, approved=False, replace=False):
        try:
            stage, report, state = self.load_staged(digest)
            if report["verdict"] == "block":
                raise GateError("Blocked snapshots cannot be installed")
            if report["verdict"] == "ask" and not approved:
                raise GateError("This report requires the user's explicit approval")
            root = state["packages"][0]
            if state["kind"] == "skill":
                destination = Path(state["destination"])
                make_directory(destination.parent)
                # Outside the staging folder, so the final `discard` keeps it.
                stamp = self.now().strftime("%Y%m%dT%H%M%SZ")
                backup = self.config / "safe-install" / "backups" / "{}-{}-{}".format(state["name"], stamp, digest[:8])
                replacing = False
                if destination.exists() or destination.is_symlink():
                    no_links(destination)
                    if not replace:
                        raise GateError("Destination already exists; replacement requires --replace")
                    if backup.exists():
                        raise GateError("A replacement backup already exists; it will not be overwritten")
                    # Check the whole old tree before recursive removal or backup.
                    Tree(root=destination).read()
                    make_directory(backup.parent)
                    shutil.copytree(str(destination), str(backup), symlinks=False)
                    no_links(destination)
                    replacing = True
                try:
                    if replacing:
                        shutil.rmtree(str(destination))
                    destination.mkdir(mode=0o700)
                    for file in root["files"]:
                        target = destination / safe_path(file["path"])
                        make_directory(target.parent)
                        with target.open("xb") as stream:
                            stream.write(file["data"])
                        target.chmod(0o755 if file["executable"] else 0o644)
                    self.verify_copy(destination, root)
                except Exception as exc:
                    try:
                        if destination.exists():
                            no_links(destination)
                            shutil.rmtree(str(destination))
                        if replacing:
                            shutil.copytree(str(backup), str(destination))
                    except (OSError, GateError) as rollback_error:
                        raise GateError("Skill installation failed: {}; rollback failed: {}".format(exc, rollback_error)) from exc
                    raise
                detail = str(destination)
                if replacing:
                    detail += "; previous version backed up to " + str(backup)
                return {"status": "installed", "detail": detail}
            if not root.get("install_args"):
                raise GateError("A plugin folder or URL can be scanned but not installed: Claude Code installs "
                                "plugins from a marketplace. Use name@marketplace or --marketplace <source>.")
            scope = report["scope"]
            working_directory = state["cwd"]
            # Remember what was installed before, so a failed verification only
            # removes what this run added — never a plugin the user already had.
            before = {(e.get("id", e.get("pluginId")), e.get("scope", scope))
                      for e in self.installed_entries(working_directory)}
            self.claude(["plugin", "install"] + root["install_args"] + ["--scope", scope], cwd=working_directory)
            try:
                entries = self.installed_entries(working_directory)
                for package in state["packages"]:
                    matches = [e for e in entries if isinstance(e, dict) and
                               e.get("id", e.get("pluginId")) == package["plugin_id"] and e.get("scope", scope) == scope]
                    if len(matches) != 1 or not isinstance(matches[0].get("installPath"), str):
                        raise GateError("Installed plugin or dependency was not found uniquely")
                    location = Path(matches[0]["installPath"])
                    if not location.is_absolute():
                        raise GateError("Installed plugin path must be absolute")
                    self.verify_copy(location, package)
            except Exception as exc:
                failures, kept = [], []
                for package in reversed(state["packages"]):
                    if (package["plugin_id"], scope) in before:
                        kept.append(package["plugin_id"])
                        continue
                    try:
                        self.claude(["plugin", "uninstall", package["plugin_id"], "--scope", scope], cwd=working_directory)
                    except GateError as uninstall_error:
                        failures.append(str(uninstall_error))
                detail = "Installed-copy verification failed: {}".format(exc)
                if kept:
                    detail += ("; not uninstalled because they were already installed before this run, but their "
                               "files may now differ from what was reviewed — check or uninstall them: " + ", ".join(kept))
                if failures:
                    detail += "; rollback failed: " + "; ".join(failures)
                raise GateError(detail) from exc
            return {"status": "installed", "detail": "{} ({})".format(root["plugin_id"], scope)}
        except UsageError:
            raise
        except (GateError, OSError) as exc:
            return {"status": "failed", "detail": str(exc)}

    def discard(self, digest):
        stage = self.staged(digest)
        # Refuse links anywhere in the staging tree, including backups.
        for directory, dirs, names in os.walk(str(stage), followlinks=False, onerror=walk_error):
            for name in dirs + names:
                no_links(Path(directory) / name)
        shutil.rmtree(str(stage))
        return {"status": "discarded", "detail": digest}


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise UsageError(message)


def main(argv=None):
    if sys.version_info < (3, 9):
        print(json.dumps({"status": "failed", "detail": "Python 3.9 or later is required"}))
        return 2
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["--version"]:
        print(json.dumps({"version": POLICY}))
        return 0
    gate = Gate()
    try:
        try:
            gate.rules = load_rules(gate.references / "fixed-checks.json")
        except GateError:
            # `scan` reloads the rules and blocks on a broken file; `install` and
            # `discard` must still work so leftovers can be cleaned up.
            gate.rules = None
        parser = Parser(add_help=False)
        commands = parser.add_subparsers(dest="command", required=True, parser_class=Parser)
        scan = commands.add_parser("scan", add_help=False)
        scan.add_argument("target")
        scan.add_argument("--scope", choices=("user", "project", "local"), default="user")
        scan.add_argument("--type", choices=("skill", "plugin"))
        scan.add_argument("--marketplace")
        install = commands.add_parser("install", add_help=False)
        install.add_argument("digest")
        install.add_argument("--approved", action="store_true")
        install.add_argument("--replace", action="store_true")
        discard = commands.add_parser("discard", add_help=False)
        discard.add_argument("digest")
        parsed = parser.parse_args(args)
        if parsed.command == "scan":
            output, code = gate.scan(parsed.target, parsed.scope, parsed.type, parsed.marketplace)
        elif parsed.command == "install":
            output, code = gate.install(parsed.digest, parsed.approved, parsed.replace), 0
        else:
            output, code = gate.discard(parsed.digest), 0
    except UsageError as exc:
        output, code = {"status": "failed", "detail": str(exc)}, 2
    except Exception as exc:
        if args and args[0] == "scan":
            output = gate.base_report(args[1] if len(args) > 1 else "", "user")
            output["reasons"] = ["Internal scan error: {}".format(exc)]
        else:
            output = {"status": "failed", "detail": "Internal error: {}".format(exc)}
        code = 1
    print(json.dumps(display(output, gate.rules), ensure_ascii=True, allow_nan=False))
    return code


if __name__ == "__main__":
    sys.exit(main())
