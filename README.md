# ai

*Standalone plugins and skills for the AI domain.*

Each plugin under `plugins/` is self-contained (its own README, license, skills,
and commands); `skills/` holds standalone skills not bundled into a plugin.

## Repo layout

```
.claude-plugin/marketplace.json   marketplace manifest listing published plugins
plugins/<name>/                   one self-contained plugin per directory
skills/<name>/                    standalone skills, independent of any plugin
```

## Plugins

| Plugin | Description |
|---|---|
| [`estimator`](plugins/estimator) | Estimate Jira tickets from your team's actual history. Pulls resolved tickets via the Atlassian MCP to build a baseline, then suggests effort/story-point estimates by comparing new work to similar past tickets. |

See each plugin's own README for setup, usage, and requirements.

## Skills

Standalone skills (not tied to a specific plugin) live in `skills/`. None yet.

## License

Each plugin/skill carries its own license (see its directory). Unless noted
otherwise, MIT.
