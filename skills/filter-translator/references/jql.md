# JQL (Jira Query Language)

Source: [Atlassian JQL operators reference](https://support.atlassian.com/jira-software-cloud/docs/jql-operators/).

## Comparison operators

| Operator | Meaning | Notes |
|---|---|---|
| `=` | equals | not usable on free-text fields |
| `!=` | not equals | does **not** match empty fields — pair with `OR field is empty` if you need to include nulls |
| `>` / `>=` | greater than / or equal | only on orderable fields (dates, numeric-like fields, versions) |
| `<` / `<=` | less than / or equal | same restriction |
| `~` | contains (text match) | the text-field equivalent of `=` |
| `!~` | does not match (text) | the text-field equivalent of `!=` |
| `IN` / `NOT IN` | membership in a value list | `status IN (Open, "In Progress")` |
| `IS` / `IS NOT` | null / reserved-value comparison | e.g. `assignee IS EMPTY` |
| `IS EMPTY` / `IS NOT EMPTY` | field-presence check | |
| `WAS` | historical value check | |
| `CHANGED` | field was modified (optionally with `BY`/`FROM`/`TO`/`ON`/`DURING`/`AFTER`/`BEFORE`) | |

## Logical operators & grouping

`AND`, `OR`, `NOT` (uppercase keywords). Parentheses group sub-expressions
and control precedence: `(condition1 AND condition2) OR condition3`. As with
OData, don't lean on implicit precedence for anything non-trivial —
parenthesize explicitly.

## Quoting rules

Field names and values containing **spaces, reserved words, or special
characters** need quotes (double or single). Simple unquoted alphanumeric
tokens are fine without them. When unsure whether a value needs quoting
(e.g. it's a reserved JQL word, or contains a space), quote it — quoting an
already-safe token is harmless.

## Serialization

JQL is normally typed directly into Jira's search UI or passed as the `jql`
parameter to a Jira REST API call. In the UI, no percent-encoding is
needed — present it as plain text. If it's being placed into a URL
(`?jql=...`), treat it like any other query-string value and route it
through `scripts/encode_query.{py,mjs}` (`references/rfc3986.md`) rather
than hand-encoding.

## Worked example

Scenario: `(group=student AND age>20) OR (group=senior AND age<80)`.

```
(group = "student" AND age > 20) OR (group = "senior" AND age < 80)
```
