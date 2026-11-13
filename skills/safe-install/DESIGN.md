# safe-install — design

The contract for `scripts/safe_install.py`. `SKILL.md` and the README describe the
same behaviour from the user's side; if they disagree with this file, this file wins.

## 1. Decision rules

| Result of the scan | What happens |
|---|---|
| Any CRITICAL finding | **block**: report, install nothing, no override |
| Scan incomplete, unsupported or failed | **block**: report the reason |
| At least one HIGH / MEDIUM / LOW finding | **ask**: report, then Yes/No in the Claude Code session |
| No findings | **clean**: report "nothing found", install automatically |

`--scan-only` reports and stops. A target that needs consent is never installed in
a session without AskUserQuestion (e.g. `claude -p`).

## 2. Prerequisites

- Python ≥ 3.9, **standard library only**, one implementation. Run as
  `python -I scripts/safe_install.py …`.
- The native `claude` executable on PATH. On Windows a `.cmd`/`.bat` shim is
  refused: arguments passed through cmd.exe are not quoted safely.

## 3. Layout

```
skills/safe-install/
  SKILL.md                          workflow Claude follows
  README.md                         user docs
  DESIGN.md                         this file
  scripts/safe_install.py           the gate (scan / install / discard)
  scripts/tests/test_safe_install.py
  scripts/tests/fake_claude.py      stand-in for `claude` in tests
  scripts/tests/cli_with_fake_claude.py  the CLI with that stand-in injected (tests only)
  scripts/tests/fixtures/…
  references/reviewer-prompt.md     system prompt of the isolated AI reviewer
  references/review-schema.json     JSON schema the reviewer must answer in
  references/fixed-checks.json      fixed pattern rules (§8)
  tests/fixed-checks/…              positive/negative fixtures for those rules
  evals/…                           `claude plugin eval` cases for SKILL.md
```

## 4. CLI

All output is one JSON document on stdout. Exit codes: `0` the command ran (read
`verdict` / `status`), `2` usage error, `1` internal error. An internal error
during `scan` must still print a report with verdict `block`.

### `scan <target> [--scope user|project|local] [--type skill|plugin] [--marketplace <src>]`

Builds the snapshot (§6), runs every check (§7), writes `report.json` into the
staging folder and prints the same report:

```json
{
  "policy": "2",
  "digest": "<sha256>",
  "created_at": "<ISO-8601 UTC>",
  "target": "<as given>",
  "kind": "skill | plugin",
  "name": "<name>",
  "scope": "user | project | local",
  "source": {"type": "local | github | marketplace", "detail": "<path, repo@commit, or name@marketplace>",
             "commit": "<sha or null>"},
  "destination": "<skill folder, or plugin id>",
  "inventory": {"skills": [], "commands": [], "agents": [], "hooks": [], "mcp_servers": [],
                "lsp_servers": [], "monitors": [], "bin": [], "dependencies": [],
                "unreviewed_files": []},
  "checks": [{"name": "fixed checks | manifest validation | inventory | AI review",
              "status": "ran | not available | not applicable | failed", "detail": "<text>"}],
  "complete": true,
  "verdict": "block | ask | clean",
  "reasons": ["<why blocked or incomplete>"],
  "findings": [{"id": "<FC-###, VAL, AI>", "severity": "CRITICAL | HIGH | MEDIUM | LOW",
                "name": "<short>", "description": "<plain English>",
                "file": "<path or null>", "line": 0, "package": "<name or dependency name>"}],
  "choices": null
}
```

`choices` is set instead of a verdict when the target is a marketplace or a folder
of several skills: a list of names; `SKILL.md` asks which one and runs `scan` again.

### `install <digest> [--approved] [--replace]`

- refuse when the verdict is `block`;
- refuse an `ask` verdict without `--approved` (`SKILL.md` passes it only after the
  user answers Yes);
- refuse a report older than 30 minutes;
- re-hash the staged files and refuse on any mismatch with the digest;
- then install (§9) and print `{"status": "installed | failed", "detail": …}`.

### `discard <digest>`

Deletes that staging folder. `SKILL.md` always calls it at the end.

## 5. Targets

- **Local folder**, absolute or relative to the current directory.
- **GitHub URL**: `https://github.com/<o>/<r>/tree/<ref>/<path>` or a `blob/` URL to
  a skill folder containing `SKILL.md` or a file inside a skill (use the nearest
  containing skill folder). If no containing skill is found, handle the full
  `blob/` path like a `tree/` path; a folder of skills returns `choices`.
  A `blob/` URL without a path is refused. Refs may contain `/`: use the longest
  prefix the GitHub API resolves to a commit. Pin to that SHA and download
  `https://codeload.github.com/<o>/<r>/zip/<sha>`. Validate only archive entries
  under the target path. Public github.com only, no credentials, redirects only to
  GitHub hosts.
- **`name@marketplace`**: the marketplace must already be registered; find it with
  `claude plugin marketplace list --json` (`installLocation`). Never register or
  refresh a marketplace.
- **`name --marketplace <src>`**: fetch that marketplace (GitHub `owner/repo` or a
  local path) into staging without registering it; installation later uses
  `claude plugin install <name> --marketplace <src>`.
- **Marketplace entry sources**: supported are relative paths (incl. bare names
  under `metadata.pluginRoot`), `github`, and `url` / `git-subdir` on github.com
  (honour `sha`, else resolve `ref` to a commit). `npm`, `archive`, `command` and
  non-GitHub git → block, "unsupported source, not reviewed". The entry's JSON is
  added to the snapshot as `.safe-install/marketplace-entry.json` so the reviewer
  sees entry fields that change behaviour (inline `hooks`, `mcpServers` without a
  plugin.json, `strict`, `headersHelper`).
- **Dependencies** (`dependencies` in plugin.json or the entry): Claude Code installs
  them automatically, so each is resolved and scanned the same way, up to 3 levels,
  each once. One that can't be resolved or reviewed → block. Findings carry
  `package` so the report can group them.
- **Kind**: skill (root `SKILL.md`), plugin (`.claude-plugin/plugin.json`, plugin
  component folders, or any marketplace target), marketplace
  (`.claude-plugin/marketplace.json`) → `choices`. `--type` overrides an ambiguous case.
- **Scope**: skills: `user` → `<config>/skills/<name>`, `project` →
  `<cwd>/.claude/skills/<name>`, `local` is a usage error. Plugins: passed to
  `claude plugin install --scope`. `<config>` is `CLAUDE_CONFIG_DIR` or `~/.claude`.
  Default `user`.

## 6. Snapshot

- Staged in `<config>/safe-install/staged/<digest>/`. Nothing there is executed or
  loaded as a skill. Scanning a target whose digest is already staged (an earlier
  scan that was never discarded) replaces that folder.
- Digest = sha256 over policy version, kind, name and the sorted list of
  (path, executable bit, sha256 of content). The executable bit is preserved on install.
- Refuse symlinks, junctions and special files, also in ancestor folders;
  case-colliding paths; `..`; absolute paths; Windows reserved device names.
- Limits: 2000 files, 50 MiB in total, 2 MiB per text file, 64 MiB per download.
  Over a limit → block (incomplete). Never truncate.
- Binaries: common images and fonts are allowed, listed in
  `inventory.unreviewed_files`, no finding. Any other binary or archive → block
  (incomplete: it can't be reviewed).
- Skill names must match `^[a-z0-9][a-z0-9-]{0,63}$` before they are used as a
  folder name.

## 7. Checks

1. **Fixed checks**: `references/fixed-checks.json` (§8) applied with Python `re` to
   every text file. A malformed rules file → block. Missing file → check status
   "not available". Matches of a rule with `redact: true` are never printed in full.
2. **Manifest validation** (plugins): `claude plugin validate --strict --json <dir>`.
   Collect `errors` and `warnings` from `manifest` and from each `contents[]` item:
   errors → HIGH, warnings → LOW, id `VAL`. Skills have no manifest: status
   "not applicable".
3. **Inventory** (plugins): `claude --plugin-dir <dir> plugin details <name>` (text
   only). Parse the "Component inventory" lines (`Skills (N) …`, `Hooks (N) …`,
   `MCP servers (N)`, …). Skills: inventory comes from the snapshot itself.
4. **Isolated AI review** (required):
   ```
   claude -p --safe-mode --restricted --tools "" --disallowedTools "mcp__*"
     --strict-mcp-config --mcp-config '{"mcpServers":{}}' --setting-sources ""
     --settings '{"disableAllHooks":true}' --no-chrome --no-session-persistence
     --output-format json --json-schema <references/review-schema.json>
     --system-prompt <references/reviewer-prompt.md>
   ```
   Run from an empty temp folder, `CLAUDECODE` removed from the environment, the
   snapshot (files, inventory, fixed-check findings, digest, policy) as JSON on
   stdin, 5-minute timeout. Up to ~600 KB of text per call; larger snapshots are
   split into several calls, each also given the full file list.
   Validation of the answer — any failure blocks: `type: result`, `subtype:
   success`, `is_error: false`; `structured_output` matches the schema with no
   unknown fields or duplicate keys; digest and policy echoed; every file of the
   call listed once in `reviewed_files`; every finding cites one of those files and
   a line within it; `complete: false` → block with the reviewer's summary.
   Reviewer findings are added; a reviewer finding may raise a fixed-check finding's
   severity (same file and line), never lower or remove one.
- Every string the script prints is escaped: control and Unicode format
  characters become `\uXXXX`.

## 8. Fixed-check rules

`references/fixed-checks.json` is a JSON array of:

| Field | Meaning |
|---|---|
| `id` | `FC-###` |
| `severity` | `critical`, `high`, `medium`, `low` |
| `name` | short issue name |
| `description` | one or two plain sentences for a non-technical user |
| `pattern` | Python `re`; characters as `\uXXXX` / `\UXXXXXXXX` escapes, never literal invisible characters |
| `case_insensitive` | boolean |
| `glob`, `exclude_glob` | optional file filters |
| `redact` | true for secrets |
| `source` | where the rule comes from |

Scope: hidden or invisible Unicode; committed credentials (based on Gitleaks'
MIT-licensed rules, each naming its source rule); other fixed patterns only with a
very low false-positive rate. `critical` only where legitimate packages almost
never match. Each rule has a positive and a harmless look-alike negative fixture
under `tests/fixed-checks/`, with `expected.json`; fixtures build secret-like or
invisible content at test time. Every skill and plugin in this repository must
produce zero fixed-check findings.

## 9. Install and verification

- **Skill**: copy the staged bytes to the destination, re-hash, compare with the
  digest. An existing destination is refused unless `--replace`; the old copy is
  first backed up to `<config>/safe-install/backups/<name>-<UTC time>-<digest[:8]>/`
  (outside staging, so `discard` keeps it) and the path is returned in `detail`.
- **Plugin**: `claude plugin install <name>@<marketplace> --scope <scope>` (or
  `--marketplace <src>`). Read `installPath` from `claude plugin list --json` and
  hash it against the snapshot; do the same for each dependency. The only files
  excluded from the comparison are ones Claude Code adds itself: `.in_use/<pid>`
  markers (observed on Claude Code 2.1.322). A mismatch → `claude plugin uninstall
  <id> --scope <scope>` for each plugin this run newly installed, status `failed`.
  Plugins that were installed before the run are not uninstalled; `detail` names
  them and warns that their files may have changed.
- A plugin given as a folder or GitHub URL (no marketplace) can be scanned, but
  `install` refuses it: Claude Code installs plugins only from a marketplace.

## 10. Tests

`unittest`, no network, no paid calls. `fake_claude.py` replaces `claude` through
`Gate(claude_command=[argv…])`, injected like HTTP; the CLI never sets it and reads
no environment override, so outside tests `claude` is always the native executable
from PATH. The CLI test runs `tests/cli_with_fake_claude.py`, which is the same
`main()` with the fake injected. `fake_claude.py` implements `-p` review,
`plugin validate`, `plugin details`, `plugin install`, `plugin list`,
`plugin uninstall`. HTTP is injected. Cover: clean → install without `--approved`;
ask → refused without `--approved`; critical → block; incomplete / binary → block;
links refused; ZIP containment; GitHub ref containing `/`; each supported and each
unsupported marketplace source; dependency scanning; installed-copy mismatch →
uninstall; tampered staging refused; stale report refused; `--replace` backup;
output escaping; reviewer coverage / line / digest validation; this repository's
skills and plugins give zero fixed-check findings.

The fixed-check fixture tests run from a test module in `scripts/tests/` too, so
one command runs everything:

```
python -I -m unittest discover -s skills/safe-install/scripts/tests -t skills/safe-install/scripts -v
```

CI (`.github/workflows/safe-install.yml`) runs exactly that on Ubuntu, Windows and
macOS with Python 3.x, and with Python 3.9 on Windows and macOS (setup-python has no
3.9 build for Ubuntu 26.04; on macOS 3.9 is the Command Line Tools' `python3`).
