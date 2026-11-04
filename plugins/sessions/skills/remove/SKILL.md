---
name: remove
description: Alias of the `clear` skill — delete the saved set of Claude Code sessions (only the saved list, never the conversations). Invoked as /sessions:remove.
disable-model-invocation: true
---

# Sessions — Remove (alias of Clear)

This is the same action as the `clear` skill, under another name. Read the
`clear` skill's instructions and follow them exactly:

`${CLAUDE_PLUGIN_ROOT}/skills/clear/SKILL.md`

When you read that file, its `${CLAUDE_PLUGIN_ROOT}` and `${CLAUDE_PLUGIN_DATA}`
placeholders will not have been filled in. Use these values instead:

- plugin root: `${CLAUDE_PLUGIN_ROOT}`
- data dir (`-DataDir`): `${CLAUDE_PLUGIN_DATA}`

If either value above still reads as a `${...}` placeholder, use the folder two
levels above this skill's base directory as the plugin root, and pass the data
dir placeholder through unchanged (the script handles it).
