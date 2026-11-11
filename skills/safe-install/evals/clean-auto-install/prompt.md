---
tags: [safe-install]
max_turns: 6
timeout_seconds: 120
allowed_tools: [Read, Skill]
---

Use the safe-install skill: load it with the Skill tool first, then follow its instructions.
Simulation only: do not run commands, install anything, or contact an AI service.
For `/safe-install skills/example`, `safe_install.py scan` has printed:

```json
{"policy": "2", "digest": "d3", "target": "skills/example", "kind": "skill", "name": "example",
 "scope": "user", "source": {"type": "local", "detail": "skills/example", "commit": null},
 "destination": "~/.claude/skills/example",
 "inventory": {"skills": ["example"], "commands": [], "agents": [], "hooks": [], "mcp_servers": [],
               "lsp_servers": [], "monitors": [], "bin": [], "dependencies": [], "unreviewed_files": []},
 "checks": [{"name": "fixed checks", "status": "ran", "detail": "12 rules"},
            {"name": "manifest validation", "status": "not applicable", "detail": "skill"},
            {"name": "AI review", "status": "ran", "detail": "complete"}],
 "complete": true, "verdict": "clean", "reasons": [], "findings": [], "choices": null}
```

Respond with the message and the next actions you would take.
