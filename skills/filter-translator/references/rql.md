# RQL (Resource Query Language)

**No ratified spec exists.** RQL descends from the expired IETF draft
[`draft-nottingham-atompub-fiql-00`](https://datatracker.ietf.org/doc/html/draft-nottingham-atompub-fiql-00)
(FIQL) and is documented here as the **de facto common subset** used by
real-world implementations (cross-checked against
[persvr/rql](https://github.com/persvr/rql), one of the most widely
referenced), not as a standard. If the user's actual target system has its
own RQL dialect that differs, defer to their system's docs over this file.

## Two equivalent surface syntaxes

RQL is "a compatible superset of standard HTML form URL encoding" and also
supersets FIQL — the same query can be written as **named functions** or as
**FIQL-style infix shorthand**. This skill defaults to the **function-call
form** (matches the spec's naming) since it's more explicit and readable;
mention the FIQL-shorthand equivalent as an alternative when useful.

### Function-call form (default)

| Operator | Meaning |
|---|---|
| `eq(property,value)` | equals |
| `ne(property,value)` | not equals |
| `lt(property,value)` / `le(property,value)` | less than / or equal |
| `gt(property,value)` / `ge(property,value)` | greater than / or equal |
| `in(property,array)` / `out(property,array)` | membership / non-membership |
| `contains(property,value)` / `excludes(property,value)` | array-field membership |
| `and(query,query,...)` | all must match |
| `or(query,query,...)` | at least one must match |

### FIQL-style infix shorthand (equivalent, from the underlying draft)

| Operator | Meaning |
|---|---|
| `==` | equals |
| `!=` | not equals |
| `=lt=` / `=le=` | less than / or equal |
| `=gt=` / `=ge=` | greater than or equal |
| `;` | AND (higher precedence) |
| `,` | OR (lower precedence) |

`price=lt=10` (shorthand) ≡ `lt(price,10)` (function form). Parentheses
override default precedence in both forms.

## Value encoding

The **raw expression** (function-call or FIQL-shorthand form) is the default
deliverable — don't percent-encode it unless the user is explicitly
composing a URL/query string with it.

When they are: values are drawn from `unreserved / pct-encoded` characters
(per RFC 3986) plus a small FIQL delimiter set (`!`, `$`, `'`, `*`, `+`). A
value containing `(`, `)`, `,`, `;`, `=`, or a literal space must be
percent-encoded so it isn't mistaken for RQL syntax — hand it to
`scripts/encode_query.{py,mjs}` (`references/rfc3986.md`) rather than
hand-encoding. RQL is emitted directly as (or as part of) a URL query string
more often than JQL/SQL/Mongo are, so this comes up more frequently here —
but it's still only done on request, not by default.

## Worked example

Scenario: `(group=student AND age>20) OR (group=senior AND age<80)`.

Function-call form:
```
or(and(eq(group,student),gt(age,20)),and(eq(group,senior),lt(age,80)))
```

FIQL-shorthand equivalent:
```
(group==student;age=gt=20),(group==senior;age=lt=80)
```

Both are safe to leave unencoded structurally here (no spaces/reserved
characters inside the values `student`/`senior`/`20`/`80`); if a value did
contain one of those characters, only that value's characters would need
percent-encoding, not the whole expression's structural characters.
