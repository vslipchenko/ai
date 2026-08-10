# estimator — Design Notes

Developer-facing record of the **durable design decisions** behind the plugin and
*why* they're that way. (Usage docs live in `README.md`; this is the "why" for
anyone extending the plugin.) Each entry is a decision + its rationale.

## Architecture

- **Plugin = skills + commands + shared scripts.** Skills: `sync`, `estimate`,
  `add`, `find`, `edit`, `export`, `import`. Commands: `prune`, `reset`.
- **Division of labour:** the model does the interactive + Jira work (fetching,
  analysis, prompting); small **deterministic bundled scripts** own all CSV
  assembly/parsing. The model never hand-rolls CSV logic when a script exists.
- **Skills vs commands:** discrete user-triggered maintenance actions that take no
  free-form reasoning are commands (`prune`, `reset`); everything conversational
  is a skill.

## Data model

- **Data dir: `~/.estimator`** — a plain per-user home dotfolder (like `~/.aws`),
  global per user (not per project). Holds `history.csv` + `config.json`.
  - *Why a plain home folder:* the managed `$CLAUDE_PLUGIN_DATA` dir is **empty in
    the shells a skill spawns** (see Path resolution), so we can't rely on it.
    Uninstalling the plugin does **not** remove the data; `/estimator:reset` clears
    it deliberately.
- **`history.csv` — 13 columns, `;`-delimited, RFC 4180 quoting.** Multi-value
  cells (components, labels) joined with `, `; comments joined with `\n\n`.
  Headers end with the canonical field token in parentheses, e.g.
  `Title (summary)` — token-based mapping lets readers tolerate reordered/legacy
  columns.
- **`estimate_basis` (13th column) ∈ {`actual`, `final`, `suggested`}** —
  provenance of each row's points. `sync` and resolved `add` → `actual`;
  team-agreed value → `final`; the skill's own guess → `suggested`.
  - *Why:* estimation **trusts `actual` > `final` > `suggested`**, so the tool's
    own guesses can't be mistaken for ground truth and drive drift. When an
    estimated ticket later resolves, re-running `sync` overwrites its row (by key)
    with the real `actual` outcome.
- **`config.json` sidecar** holds: `jql`, `project_keys`, `cloud_id`,
  `story_point_field_id`, `min_fetch_story_points`, `updated_watermark`,
  `schema_version`, `row_count`, `estimation_prefs`, `last_exported`. **Every
  writer preserves keys it doesn't own** (config is shared across skills).

## Shared scripts & cross-runtime parity

- **`scripts/build_csv.{py,mjs}`** — the CSV core (assembly, read-existing with
  legacy padding, append-dedup-by-key, RFC 4180 writer). **`scripts/dump_records.{py,mjs}`**
  — reads `history.csv` → JSON array of records (for `estimate`'s analysis).
  Per-skill scripts: `skills/find/scripts/find_records`, `skills/edit/scripts/edit_records`,
  `skills/import/scripts/import_records`, `commands/scripts/prune_records`.
- **Python and Node implementations MUST produce byte-identical output**, verified
  by parity tests. Convention: Python `json.dumps(obj, ensure_ascii=False,
  separators=(",", ":"))` written to `sys.stdout.buffer` with a bare `\n` (NOT
  `print()`, which emits `\r\n` on Windows); Node `console.log(JSON.stringify(obj))`.
  - *Why both runtimes:* users may have only one of Python/Node; the ladder falls
    through (below). Byte-identical output means either runtime is interchangeable
    and parity is testable.
- **Append dedups by key, new wins** — so re-fetching or re-estimating a ticket
  cleanly replaces its row.

## Runtime ladder & path resolution

- **Runtime ladder: `python3 → python → py -3 → node → tool fallback`** (Read/Write
  tool). *Why this order / why `py -3`:* on Windows, bare `python`/`python3` are
  often Microsoft Store **stubs** that exit 49 ("Python not found"); the `py -3`
  launcher and `node` work. `python3`/`python` lead for macOS/Linux. The final
  fallback is the model doing the work with the Read/Write tool.
- **`$CLAUDE_PLUGIN_ROOT` / `$CLAUDE_PLUGIN_DATA` are empty in skill-spawned
  shells** (they're only substituted in command bodies, hooks, and MCP configs).
  Consequences:
  - **Skills resolve `<PLUGIN_ROOT>` as two levels above the skill's announced
    base directory** (`…/skills/<name>` → parent's parent = plugin root).
  - **Data dir is the plain `~/.estimator`**, not a managed dir.
  - **Commands** *may* use `$CLAUDE_PLUGIN_ROOT` directly (it is substituted for
    command bodies).
- **Inspecting saved MCP payloads:** large MCP responses are auto-saved to files.
  Read them with the Read tool or a small script (same runtime ladder) — **don't
  hand-write a fragile inline `node -e`/`python -c` one-liner** over shell-quoted
  data, and don't reach for `jq` (often absent).

## `sync` (build/refresh the dataset)

- **Fetches only completed, estimated tickets** — `statusCategory = Done` plus the
  story-points filter (`cf[<id>] is not EMPTY`, or `cf[<id>] >= N`). *Why:* a
  ticket closed without an estimate carries no learnable signal.
- **Story-Points field detection is population-first.** A site has several
  story-points-like custom fields; only one is used. Collect candidates by name
  match, then **pick the one populated in the most of ~25 sampled issues**. The
  greenhopper `schema.custom` type is only a **tiebreaker** *(the MCP payload
  commonly omits `schema.custom`)*; if still tied, ask the user. Cache the id.
- **`min_fetch_story_points`** — first-run cached preference (`0` = keep all
  estimated incl. 0-point; `N>0` drops tickets below `N`).
- **Ordering, time window, and append watermark all use `updated`, never
  `resolutiondate`.** *Why:* `updated` always exists and is monotonic;
  `resolutiondate` is null for many Done-category statuses, which would make
  "latest N" unreliable and silently drop tickets from append. `resolution_date`
  is still stored as a **data column**. Append uses `updated >= updated_watermark`
  (`>=`, so a boundary-timestamp tie is never skipped — dedup-merge absorbs the
  re-fetch).
- **One bulk search, assembled in place.** A single paginated
  `searchJiraIssuesUsingJql` returns every matching issue with all needed fields;
  assemble records from that one (possibly file-saved) result. **Never loop
  `getJiraIssue` per ticket** — a per-issue fetch is only a fallback for a field
  the search genuinely omits.
- **`design_link` is description-first in bulk sync** (first Figma/Confluence URL
  in the description) — *why:* per-ticket `getJiraIssueRemoteIssueLinks` adds one
  MCP call (and permission prompt) per ticket. `estimate` (single ticket) keeps
  the authoritative remote-link call — cheap for one.
- **`refresh` overwrites; `append` merges and never deletes.** Append is the
  quality-preserving periodic mode (keeps prior `actual`/`final`/`suggested` rows);
  refresh is a deliberate clean rebuild of the current scope.

## `estimate` (suggest points)

- **Method:** load history via `dump_records`, narrow by `issue_type` /
  overlapping `components`/`labels`, rank by semantic similarity, **weight by
  `estimate_basis`** (`actual` > `final` > discount `suggested`/blank).
- **`estimation_prefs`** — first-run cached object: `point_scale`
  (Fibonacci / modified Fibonacci / linear / powers-of-two / custom / skip→infer),
  `point_scale_note`, optional `min_story_points` / `max_story_points`.
  - **Snap to scale, then clamp to limits** → nearest in-scale value within
    `[min,max]`. Applies to the **suggestion only**; a value the **team enters is
    recorded as-is** (ground truth, never clamped).
- **Output is plain text** (renders in a terminal — no HTML entities/markup).

## Migrations

- **Anchor on `schema_version`** (monotonic integer, the data's *format* version),
  **not the plugin release version.** *Why:* the plugin version bumps for
  unrelated reasons (prose fixes, new skills) and the installed plugin version
  doesn't tell you what format the on-disk data is in (data can lag the plugin).
- **Migrate-on-read, not at plugin-update time** — a file-based plugin can't run
  code against `~/.estimator` on update; when the format changes, bump
  `schema_version` and have the skills migrate old data when they next load it.
- `last_exported` (timestamp, written by `export`) is provenance only, not a
  migration signal.

## Safety

- **Read-only Jira.** Jira-touching skills (`sync`, `estimate`, `add`) may use
  *only* read operations (`atlassianUserInfo`, `getAccessibleAtlassianResources`,
  project/field metadata, `searchJiraIssuesUsingJql`, `getJiraIssue`,
  `getJiraIssueRemoteIssueLinks`). They MUST NOT create/edit/transition/comment/
  link/assign/delete/log-work, or write Confluence. Each such skill states this
  explicitly.
- **Destructive actions require explicit confirmation:** `reset` (delete data),
  `prune` (delete rows), `export`/`import` overwrite/replace, and overwriting an
  existing row in `estimate`/`add`. Never silent-overwrite; never claim success on
  a failed write.

## Testing

- Every deterministic script has matching Python **and** Node test suites over
  shared fixtures (same inputs → same asserted outputs); byte-identical
  cross-runtime output is spot-checked by diffing both CLIs when a script changes.
- Windows notes: bare `python`/`python3` may be Store stubs (use the real
  interpreter or `py -3`); `node --test <dir>` is unreliable — pass an explicit
  test file path.
- `claude plugin validate .` must pass.
