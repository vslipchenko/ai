# OData `$filter` (v4/v4.01)

Source: [OASIS OData v4.01 Part 2: URL Conventions](https://docs.oasis-open.org/odata/odata/v4.01/odata-v4.01-part2-url-conventions.html),
`$filter` system query option. **This targets OData v4/v4.01 specifically** —
v2 differs (e.g. v2 has no `has`/`in` operators, different function names in
places). If the user needs v2, say so explicitly rather than silently
applying v4 syntax.

## Comparison operators

| Operator | Meaning |
|---|---|
| `eq` | equals |
| `ne` | not equals |
| `gt` | greater than |
| `ge` | greater than or equal |
| `lt` | less than |
| `le` | less than or equal |
| `has` | flag-enum membership test |
| `in` | membership in a comma-separated list/collection |

## Logical operators

`and`, `or`, `not` — all lowercase keywords, combined with parentheses `(...)`
for grouping (the spec doesn't hand you a full precedence table beyond
"parentheses control evaluation order" — **always parenthesize explicitly**
rather than relying on implicit precedence).

## String/date/boolean/null literals

- **Strings**: single-quoted; an embedded single quote is escaped by
  **doubling** it: `'O''Neill'`.
- **Date/DateTime/Boolean**: follow XML Schema (`Edm.Date`/`Edm.DateTimeOffset`/
  `Edm.Boolean`) literal conventions, e.g. `2026-08-12`,
  `2026-08-12T10:00:00Z`, `true`/`false`.
- **null** is a reserved literal keyword (unquoted).

## Built-in filter functions (common ones)

`contains(string,substring)`, `startswith(string,prefix)`,
`endswith(string,suffix)`, `indexof(string,substring)`, `length(string)`,
`substring(string,index[,length])`, `tolower(string)`, `toupper(string)`,
`trim(string)`, `concat(string,string)`, `matchesPattern(string,regex)`.

Examples from the spec:
```
$filter=Name eq 'Milk' and Price lt 2.55
$filter=contains(CompanyName,'Alfreds')
$filter=startswith(CompanyName,'Alfr')
```

## Serialization

The **raw expression** (`$filter=(group eq 'student' and age gt 20) or ...`)
is the default deliverable — it's what an OData client library's
`.filter(...)` call wants, and what most people mean when they ask for "an
OData filter." Don't percent-encode it unless the user is explicitly
composing a URL/query string with it.

When they are: `$filter` contains `$`, a reserved sub-delim character, so
**the key itself** also needs encoding (`%24filter`), same as the value.
Hand the assembled `[["$filter", "<expression>"]]` pair to
`scripts/encode_query.{py,mjs}` (see `references/rfc3986.md`) rather than
hand-encoding.

## Worked example

Scenario: `(group=student AND age>20) OR (group=senior AND age<80)`.

Raw `$filter` expression:
```
$filter=(group eq 'student' and age gt 20) or (group eq 'senior' and age lt 80)
```

Fully percent-encoded query string (via the bundled script):
```
%24filter=%28group%20eq%20%27student%27%20and%20age%20gt%2020%29%20or%20%28group%20eq%20%27senior%27%20and%20age%20lt%2080%29
```
