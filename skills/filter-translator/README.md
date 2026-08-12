# filter-translator

*Turn a plain-text filter description into a syntactically correct expression
in the query/filter format you actually need.*

Give it something like *"active users created this year, or admins"* and a
target format, and it produces a correct OData `$filter`, JQL query, MongoDB
filter document, SQL `WHERE` clause, or RQL expression — grounded in that
format's real grammar, not guessed from memory, and always confirmed with
you before it's finalized. For OData/RQL, it can also produce the RFC
3986 percent-encoded URL form on request.

## Install

This is a **standalone skill**, not a plugin — there's no `claude plugin
install` for it. Put the folder where Claude Code looks for skills:

```bash
# personal (available in every project)
cp -r skills/filter-translator ~/.claude/skills/filter-translator

# or project-local (this project only)
cp -r skills/filter-translator /path/to/project/.claude/skills/filter-translator
```

(Symlink instead of `cp -r` if you want it to track updates from this repo.)
Restart Claude Code (or reload skills) afterwards.

## Supported formats

| Format | Notes |
|---|---|
| OData `$filter` | v4/v4.01 |
| JQL | Jira Query Language |
| MongoDB | query filter documents (JSON) |
| SQL | `WHERE` clause (ANSI baseline; flags dialect-sensitive spots) |
| RQL | FIQL-derived; documented as a de facto common subset, not a ratified standard |

This is a fixed, curated set, not an open-ended "any format" converter —
each format has its own reference file under `references/` with real
operators, grouping rules, literal formats, and quoting/escaping rules.
Adding another format later is additive (one more reference file), not a
redesign.

RFC 3986 isn't in this table — it's not a filter grammar (no operators, no
AND/OR), so it's not something you'd pick as a target. It's the
percent-encoding mechanism OData and RQL use internally, only when you ask
for their output embedded in an actual URL rather than the raw expression.

## How it works

1. **You name the target format.** It's never guessed from context — if you
   don't name one, it asks.
2. **It resolves field names and logical grouping**, inferring confidently
   when your description gives a reasonable basis (and asking immediately
   only when it genuinely can't — e.g. no hint at all what a field is
   called, or a real scoping ambiguity).
3. **It always shows you the resolved filter as one plain-text logical
   line** — e.g. `(group=student AND age>20) OR (group=senior AND age<80)`
   — before touching target-format syntax, so you can catch a wrong field
   name or grouping in one glance instead of after the fact.
4. **It serializes** into the target format. For OData/RQL, the raw
   expression is the default output — it's what a client library's
   `.filter(...)` call wants. Only when you ask for it embedded in an
   actual URL does it percent-encode, via a small bundled script
   (`scripts/encode_query.{py,mjs}`) rather than hand-typed — it implements
   RFC 3986 directly (not `application/x-www-form-urlencoded`, which is a
   different, easily-confused spec).

## Example

> **You:** Create a MongoDB filter to select a group of people where
> students older than 20 and seniors younger than 80.
>
> **Claude:** `(group=student AND age>20) OR (group=senior AND age<80)` — is
> that the filter you want? (Using `group` and `age` as the field names —
> let me know if your schema uses different ones.)
>
> **You:** yes
>
> **Claude:**
> ```json
> { "$or": [
>     { "group": "student", "age": { "$gt": 20 } },
>     { "group": "senior",  "age": { "$lt": 80 } }
> ]}
> ```

## Requirements

Python 3 or Node.js, for exact percent-encoding — used only when you ask for
OData or RQL output embedded in an actual URL. If neither is available, a
documented manual fallback (`references/rfc3986.md`) is used instead. No
third-party packages either way. JQL/SQL/MongoDB output, and the raw
OData/RQL expression, need no runtime at all.

## License

MIT (repo default — see the root [README](../../README.md)).
