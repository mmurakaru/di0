---
name: compose-and-validate
description: Compose SQL from resolved references and prove it against the schema before it can run. Use whenever you have a question to turn into a query.
---

# compose-and-validate

Maps to the DialectPort + ValidationPort. Compose real SQL using only references
returned by `resolve-schema`, then validate it. A query that does not validate is
not allowed to run.

## How

```bash
di0 validate "<sql>"            # validate a literal query
di0 validate path/to/query.sql  # validate a file
di0 check                       # validate every query under queries/ (the drift gate)
```

Iterate until validation passes. Validation is the gate: the dialect and the
validation tier (offline or live EXPLAIN) come from the profile.

## Rule

Compose against resolved references only. Do not hard-code a table, column, or
dialect - the dialect is a profile setting.
