# SQL `WHERE` clause

There is **no single vendor-neutral executable SQL standard to fetch** (the
ISO/ANSI SQL standard text is paywalled) — this file uses ANSI-standard core
syntax as the baseline and cross-checks concrete behavior against
[PostgreSQL's documentation](https://www.postgresql.org/docs/current/) as a
representative dialect. **Dialect-sensitive spots are flagged explicitly** —
always ask which database engine the user targets if a dialect-sensitive
rule matters for their filter (e.g. identifier quoting).

## Comparison operators

| Operator | Meaning | Dialect notes |
|---|---|---|
| `=` | equals | universal |
| `<>` | not equals | **ANSI-standard form** |
| `!=` | not equals | widely supported alias for `<>` (incl. Postgres, MySQL, SQL Server); not in strict ANSI core |
| `>` / `>=` | greater than / or equal | universal |
| `<` / `<=` | less than / or equal | universal |

## Predicates

- `BETWEEN x AND y` — inclusive range test.
- `IN (...)` — membership in a value list.
- `IS NULL` / `IS NOT NULL` — null tests (ordinary `=`/`<>` against NULL
  yield NULL/"unknown", not true/false — never use `= NULL`).
- `LIKE` — pattern match (`%` = any sequence, `_` = any single character;
  wildcard characters and escape syntax are dialect-sensitive beyond that).

## Logical operators & grouping

`AND`, `OR`, `NOT`, with parentheses for grouping. Caution: `BETWEEN`'s own
`AND` can visually collide with logical `AND` — parenthesize any complex
sub-expression to keep it unambiguous.

## String literal quoting

Single-quoted; an embedded single quote is escaped by **doubling** it:
`'Dianne''s horse'`. This is the ANSI-standard rule and holds across
Postgres/MySQL/SQL Server.

## Identifier quoting — dialect-sensitive

A **reserved word or an identifier with special characters/case-sensitivity
needs** needs quoting, but the quote character differs by dialect:

| Dialect | Quote character | Example |
|---|---|---|
| ANSI standard / PostgreSQL | double quotes `"..."` | `"group" = 'student'` |
| MySQL | backticks `` `...` `` | `` `group` = 'student' `` |
| SQL Server | square brackets `[...]` | `[group] = 'student'` |

Quoting an identifier also makes it **case-sensitive** in Postgres (unquoted
names fold to lowercase). If the target dialect isn't known, default to
ANSI/Postgres double-quote style and note the assumption.

## Serialization

Plain text — no percent-encoding involved unless the caller is embedding it
in a URL themselves (uncommon for SQL; if asked, route through
`scripts/encode_query.{py,mjs}` like any other query-string value).

## Worked example

Scenario: `(group=student AND age>20) OR (group=senior AND age<80)`. Note
that **`group` is an ANSI/Postgres reserved word** (`GROUP BY`) — this
example is a good illustration of why identifier quoting matters, not just a
hypothetical:

```sql
("group" = 'student' AND age > 20) OR ("group" = 'senior' AND age < 80)
```
