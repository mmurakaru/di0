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

## Writing the query

- Read the real column names from `resolve-schema` before you write. Do not guess them.
- Build the query as a pipeline of CTEs: read each source once at the top, do one step
  per CTE, end with a `final` CTE, and select from it. Put no subquery inside a join.
- Give each table a descriptive alias with `AS` (`customers`, not `c`), and name the
  join type (`INNER JOIN`, `LEFT JOIN`).
- Narrow the data first. Filter by a time window or add a `LIMIT` before the expensive
  joins, and check the row count before you run the full query.
- When you restyle a query, run it again and compare the row count and the key totals
  with the old result. The same numbers show that the meaning did not change.
- Write in the style that `compose` returns: uppercase keywords, one select target per
  line, trailing commas, and a 4-space indent.

## Rule

Compose against resolved references only. Do not hard-code a table, column, or
dialect - the dialect is a profile setting.
