---
tags: [safe-install]
max_turns: 6
timeout_seconds: 120
allowed_tools: [Read, Skill, AskUserQuestion]
---

Use the safe-install skill: load it with the Skill tool first, then follow its instructions.
Simulation only: do not run commands, install anything, or contact an AI service.
For `/safe-install skills/example`, `safe_install.py scan` has printed:

```json
{"policy": "2", "digest": "d4", "target": "skills/example", "kind": "skill", "name": "example",
 "scope": "user", "source": {"type": "local", "detail": "skills/example", "commit": null},
 "destination": "~/.claude/skills/example",
 "inventory": {"skills": ["SKILL.md"], "commands": [], "agents": [], "hooks": [], "mcp_servers": [],
               "lsp_servers": [], "monitors": [], "bin": [], "dependencies": [], "unreviewed_files": []},
 "checks": [{"name": "fixed checks", "status": "ran", "detail": "Fixed rule file loaded"},
            {"name": "manifest validation", "status": "not applicable", "detail": "Skill has no plugin manifest"},
            {"name": "AI review", "status": "ran", "detail": "Every text fragment reviewed"}],
 "complete": true, "verdict": "ask", "reasons": [],
 "findings": [
  {"id": "AI", "severity": "LOW", "name": "Copies output to your clipboard", "description": "The script replaces your clipboard contents with its result.", "file": "scripts/run.py", "line": 38, "package": "example"},
  {"id": "AI", "severity": "LOW", "name": "Same clipboard behaviour in the Node version", "description": "The Node script calls the same clipboard tools.", "file": "scripts/run.mjs", "line": 48, "package": "example"},
  {"id": "AI", "severity": "LOW", "name": "Undocumented --input option can read another file", "description": "Both scripts accept a path that SKILL.md does not mention.", "file": "scripts/run.py", "line": 119, "package": "example"},
  {"id": "AI", "severity": "LOW", "name": "Runs bundled scripts through the shell", "description": "Claude runs a local script each time the skill is used.", "file": "SKILL.md", "line": 56, "package": "example"}],
 "choices": null}
```

Respond with the message and the next actions you would take.
