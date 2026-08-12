---
name: filter-translator
description: Convert a plain-text filter description into a syntactically correct expression in a target query/filter format — OData $filter, JQL, MongoDB, SQL WHERE, or RQL. Use when the user asks to turn a description into a filter/query (e.g. "convert this to a MongoDB filter", "give me the JQL for...", "as an OData $filter", "as an RQL query", "make a SQL WHERE clause for these conditions"). For OData/RQL, can also produce the RFC 3986 percent-encoded URL form on request. Always resolves field names, then confirms the resulting logical expression in plain text before producing the final syntax.
---

# Filter Translator

Turn a plain-text description of a filter into a correct expression in one
of the supported target formats, grounded in that format's real grammar
(bundled reference files, not guessed from memory) and confirmed with the
user before final serialization.

## Supported formats (v1)

| Format | Reference file |
|---|---|
| OData `$filter` (v4/v4.01) | `references/odata.md` |
| JQL (Jira Query Language) | `references/jql.md` |
| MongoDB query filter documents | `references/mongodb.md` |
| SQL `WHERE` clause | `references/sql.md` |
| RQL (FIQL-derived) | `references/rql.md` |

This is a fixed, curated set — not an open-ended "any format" converter.
Other formats (GraphQL filter args, Elasticsearch/Lucene, LDAP, SCIM,
JSON:API, Google AIP-160/CEL, Kubernetes label selectors, ...) aren't
supported yet; adding one is a matter of adding another reference file, not
a redesign.

**RFC 3986 (`references/rfc3986.md`) is not a selectable target format** —
it has no filter grammar of its own (no operators, no AND/OR), so there's
nothing to "convert to." It's the percent-encoding mechanism OData and RQL
use internally in Step 7, when their output needs to be embedded in an
actual URL rather than handed over as a raw expression.

`<SKILL_DIR>` below is this skill's own announced base directory (the path
shown when this skill loads, ending in `.../skills/filter-translator`) —
scripts live at `<SKILL_DIR>/scripts/encode_query.{py,mjs}`.

## Step 1 — Resolve the target format

The format must be **explicit** — named by the user, or picked by the user
from the table above if they didn't name one. Never infer it from context
clues (e.g. a mention of "Jira" is not enough to silently assume JQL — ask).

If the user names a format outside the v1 set: say plainly that it isn't
supported yet, list what is, and stop. Don't improvise an unverified
grammar for it.

## Step 2 — Load the matching reference file

Read only `references/<format>.md` for the resolved format — not the
others. Each file documents that format's comparison/logical operators,
grouping syntax, value-literal formats, and quoting/escaping rules, and
ends with the same shared worked example so you can sanity-check your own
output against it.

## Step 3 — Resolve field names and types (hybrid: infer or ask)

Plain-text descriptions rarely name the underlying field/column names
exactly. Handle this with a hybrid rule, not a blanket "always ask":

- **Infer** a field name when the description gives a reasonable basis —
  e.g. "a group of people" plus categorical values like student/senior
  implies a `group`-style field; "older than X"/"younger than Y" implies an
  `age`-style field. Don't ask a separate question about each one; carry the
  inference into Step 5's confirmation instead.
- **Ask immediately**, before inferring anything, only when there's no
  reasonable basis at all — a fully generic description that gives no hint
  what the underlying field is called.
- Where the description already names exact fields, just use them — nothing
  to infer.
- Note type where it affects encoding (date vs number vs string vs
  enum/boolean) — infer from context the same way (e.g. "older than 20"
  implies numeric).

## Step 4 — Parse into conditions and logical grouping

Break the description into `(field, operator, value)` conditions joined by
AND/OR/NOT. Same hybrid rule as Step 3:

- If a **literal** reading of a connective would produce a
  self-contradictory or always-empty condition — e.g. "students ... and
  seniors ..." read as one big AND across two mutually exclusive category
  values — infer the sensible grouping instead (typically: OR across the
  per-category clauses, AND within each). Carry it into Step 5, don't block
  on a question.
- Ask immediately, before inferring, only when multiple groupings are
  genuinely plausible and none is obviously nonsensical — e.g. "active users
  created this year or admins": does "or admins" scope over the whole
  clause or just the date condition? That's a real scoping ambiguity, not
  something to guess through.

## Step 5 — Confirm the resolved expression (always, before serializing)

Render the fully resolved condition tree — resolved field names, comparison
operators, and AND/OR/NOT grouping — as **one compact, format-agnostic
plain-text logical expression** and ask the user to confirm or correct it,
e.g.:

> `(group=student AND age>20) OR (group=senior AND age<80)` — is that the
> filter you want? (Using `group` and `age` as the field names — let me
> know if your schema uses different ones.)

This is the checkpoint that makes Steps 3–4's hybrid inference safe: infer
confidently instead of asking granular per-field questions, but nothing
reaches final output unconfirmed. It's cheap to eyeball one plain-text line,
much cheaper than verifying a verbose target-format expression after the
fact.

Only skip this step if the description was already fully unambiguous **and**
used the exact target field names verbatim (nothing was inferred, nothing
to confirm). If the user corrects the expression, re-render it and
re-confirm before moving on.

## Step 6 — Map the confirmed conditions to the target grammar

Using the loaded reference file: apply the correct operator symbols/
functions, reserved-word quoting, and value literal formats for the
resolved format.

## Step 7 — Serialize

- **JQL, SQL, MongoDB**: write the string/JSON directly per the loaded
  reference file's quoting/escaping rules. No script, no percent-encoding —
  these are never URL components.
- **OData `$filter`, RQL**: build the **raw expression** per the reference
  file first (e.g. `$filter=(group eq 'student' and age gt 20) or (...)`).
  That raw expression is very often the actual deliverable — e.g. for an
  OData client library's `.filter(...)` call, or code that will do its own
  URL encoding — so **don't percent-encode by default**.

  Only percent-encode when the user's ask makes clear they want it embedded
  in an actual URL/query string (they said "URL", "query string", "curl",
  asked for a full request, etc.) — ask if it's not clear which they want.
  When they do want it URL-embedded, hand the assembled `[[key, value]]`
  pair (e.g. `[["$filter", "<raw expression>"]]`) to the bundled script —
  never hand-write percent-encoding:
  1. `python3 "<SKILL_DIR>/scripts/encode_query.py" '<json-array-of-pairs>'`
  2. else `python "<SKILL_DIR>/scripts/encode_query.py" '<json-array-of-pairs>'`
  3. else `py -3 "<SKILL_DIR>/scripts/encode_query.py" '<json-array-of-pairs>'`
  4. else `node "<SKILL_DIR>/scripts/encode_query.mjs" '<json-array-of-pairs>'`
  5. else **manual fallback**: encode by hand using the table in
     `references/rfc3986.md` — never skip encoding silently once it's been
     asked for.

## Step 8 — Present the result

Show: the final filter string (or JSON) — the raw expression by default for
OData/RQL, or the percent-encoded query string if that's what was asked
for — a short breakdown of which plain-text condition mapped to which
clause, and, when encoding was done, whether the script or the manual
fallback produced it.

## Error handling

- Unsupported format requested → list the v1 set, stop; don't improvise.
- Field names/grouping with no reasonable basis to infer → ask immediately
  (Steps 3–4); everything else flows through the Step 5 confirmation instead
  of a blocking question.
- No script runtime available when URL encoding was actually requested →
  use the documented manual RFC 3986 fallback; never silently skip it.
- User corrects the Step 5 expression → re-render and re-confirm before
  serializing; never serialize an unconfirmed expression.
