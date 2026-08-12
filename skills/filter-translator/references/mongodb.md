# MongoDB query filter documents

Source: [MongoDB manual — query operators](https://www.mongodb.com/docs/manual/reference/operator/query/).

## Comparison operators

| Operator | Meaning |
|---|---|
| `$eq` | equals |
| `$ne` | not equals |
| `$gt` | greater than |
| `$gte` | greater than or equal |
| `$lt` | less than |
| `$lte` | less than or equal |
| `$in` | value is any of the given array |
| `$nin` | value is none of the given array |

## Logical operators

| Operator | Meaning |
|---|---|
| `$and` | array of clauses, all must match |
| `$or` | array of clauses, at least one must match |
| `$not` | inverts a single operator expression |
| `$nor` | array of clauses, none may match |

## Element operators

`$exists` (field presence), `$type` (field's BSON type).

## Implicit AND vs explicit `$and`

Multiple fields in one query document are implicitly AND-ed — **prefer
this** when the conditions are on different fields, it's simpler and more
idiomatic:
```javascript
db.collection.find({ status: "active", age: { $gt: 25 } })
```
Use explicit `$and` (an array) only when you need multiple conditions on the
**same field**, or need unambiguous grouping inside a larger `$or`/`$nor`:
```javascript
db.collection.find({ $and: [{ age: { $gt: 20 } }, { age: { $lt: 30 } }] })
```

## Value typing

Strings/numbers/booleans map directly to JSON types; `null` is JSON `null`;
dates are typically `ISODate("...")` (shell syntax) or driver-native `Date`
objects — represent as an ISO 8601 string in the JSON output and note that
the caller's driver may need to wrap it in its native date constructor.

## Serialization

Output is JSON — no percent-encoding involved (this format never routes
through `scripts/encode_query.{py,mjs}`). Model writes the JSON directly;
just follow standard JSON string-escaping (backslash-escape `"`, `\`,
control characters).

## Worked example

Scenario: `(group=student AND age>20) OR (group=senior AND age<80)` — two
different top-level groups (`student`/`senior`) combined with OR, so this
uses **implicit AND** within each `$or` branch and explicit `$or` across
them:

```json
{ "$or": [
    { "group": "student", "age": { "$gt": 20 } },
    { "group": "senior",  "age": { "$lt": 80 } }
]}
```
