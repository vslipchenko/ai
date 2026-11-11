"""Inert Claude CLI stand-in. Only tests invoke this file."""

import json
import os
from pathlib import Path
import shutil
import sys


def emit(value):
    print(json.dumps(value))


def main():
    config = json.loads(Path(os.environ["FAKE_CLAUDE_CONFIG"]).read_text(encoding="utf-8"))
    args = sys.argv[1:]
    log = Path(os.environ["FAKE_CLAUDE_LOG"])
    record = {"args": args, "cwd": os.getcwd(), "nested": "CLAUDECODE" in os.environ}
    if "-p" in args:
        payload = json.load(sys.stdin)
        record["input"] = payload
        assert not list(Path.cwd().iterdir()), "Reviewer must start in an empty folder"
        assert "CLAUDECODE" not in os.environ
        for flag in ("--safe-mode", "--restricted", "--no-chrome", "--no-session-persistence", "--strict-mcp-config"):
            assert flag in args
        assert args[args.index("--tools") + 1] == ""
        assert args[args.index("--disallowedTools") + 1] == "mcp__*"
        assert args[args.index("--setting-sources") + 1] == ""
        assert args[args.index("--output-format") + 1] == "json"
        assert json.loads(args[args.index("--mcp-config") + 1]) == {"mcpServers": {}}
        assert json.loads(args[args.index("--settings") + 1]) == {"disableAllHooks": True}
        paths = [file["path"] for file in payload["files"]]
        mode = config.get("review_mode", "clean")
        findings = []
        selected = config.get("review_file", paths[0])
        if config.get("review_severity") and selected in paths:
            findings = [{"severity": config["review_severity"], "name": "Fixture concern",
                         "description": config.get("review_description", "A test concern."),
                         "file": selected, "line": config.get("review_line", 1)}]
        answer = {"policy": payload["policy"], "digest": payload["digest"], "complete": True,
                  "reviewed_files": paths, "summary": "All supplied fragments reviewed.", "findings": findings}
        if mode == "incomplete":
            answer["complete"] = False
            answer["summary"] = "External content is needed."
        elif mode == "coverage":
            answer["reviewed_files"] = []
        elif mode == "duplicate_file":
            answer["reviewed_files"] = paths + paths[:1]
        elif mode == "digest":
            answer["digest"] = "wrong"
        elif mode == "policy":
            answer["policy"] = "wrong"
        elif mode in ("line", "unknown_file", "boolean_line", "severity"):
            answer["findings"] = [{"severity": "HIGH", "name": "Invalid finding", "description": "Fixture",
                                   "file": paths[0], "line": 999999}]
            if mode == "unknown_file":
                answer["findings"][0].update(file="not-in-this-call", line=1)
            elif mode == "boolean_line":
                answer["findings"][0]["line"] = True
            elif mode == "severity":
                answer["findings"][0].update(severity="SAFE", line=1)
        elif mode == "unknown_field":
            answer["approved"] = True
        elif mode == "missing":
            del answer["summary"]
        envelope = {"type": "result", "subtype": "success", "is_error": False, "structured_output": answer}
        if mode == "error":
            envelope["is_error"] = True
        elif mode == "subtype":
            envelope["subtype"] = "error_max_turns"
        with log.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record) + "\n")
        if mode == "invalid_json":
            print("Not JSON")
        elif mode == "duplicate_key":
            print(json.dumps(envelope).replace('"complete": true', '"complete": false, "complete": true'))
        elif mode == "fail":
            print("Simulated CLI failure", file=sys.stderr)
            return 1
        else:
            emit(envelope)
        return 0
    with log.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record) + "\n")
    prefix = config.get("fail_command")
    if prefix and args[:len(prefix)] == prefix:
        print("Simulated native failure", file=sys.stderr)
        return 9
    if args[:4] == ["plugin", "marketplace", "list", "--json"]:
        emit(config.get("marketplaces", []))
    elif args[:2] == ["plugin", "validate"]:
        emit(config.get("validation", {"manifest": {"errors": [], "warnings": []}, "contents": []}))
        return config.get("validation_exit", 0)
    elif "details" in args:
        fixture = Path(__file__).parent / "fixtures" / "inventory.txt"
        print(config.get("inventory", fixture.read_text(encoding="utf-8")))
    elif args[:2] == ["plugin", "install"]:
        registry = []
        scope = args[args.index("--scope") + 1]
        install_root = Path(os.environ["FAKE_CLAUDE_INSTALL_ROOT"])
        install_root.mkdir(exist_ok=True)
        for index, (identity, source) in enumerate(config.get("install_sources", {}).items()):
            destination = install_root / str(index)
            if destination.exists():
                shutil.rmtree(str(destination))
            shutil.copytree(source, str(destination))
            # Real Claude Code adds `.in_use/<pid>` markers to installed copies.
            (destination / ".in_use").mkdir()
            (destination / ".in_use" / str(os.getpid())).write_text("", encoding="utf-8")
            if config.get("mismatch") is True or config.get("mismatch") == identity:
                (destination / "unexpected.txt").write_text("Not reviewed", encoding="utf-8")
            registry.append({"id": identity, "scope": scope, "installPath": str(destination)})
        Path(os.environ["FAKE_CLAUDE_REGISTRY"]).write_text(json.dumps(registry), encoding="utf-8")
        emit({"status": "installed"})
    elif args[:3] == ["plugin", "list", "--json"]:
        path = Path(os.environ["FAKE_CLAUDE_REGISTRY"])
        emit(json.loads(path.read_text(encoding="utf-8")) if path.exists() else [])
    elif args[:2] == ["plugin", "uninstall"]:
        emit({"status": "uninstalled"})
    else:
        print("Unsupported fake command", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
