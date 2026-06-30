---
name: resolve-schema
description: Resolve tables, columns, joins, and metrics from the configured schema source. Use before composing any query, so references come from the source of truth rather than memory.
---

# resolve-schema

Maps to the SchemaPort. Resolve the schema from whatever source the profile names
- never recall a table or column from memory.

## How

```bash
di0 schema                      # print the resolved schema as JSON
di0 --profile <path> schema     # for a non-default profile
```

Use the output to discover exact namespaces, tables, and columns before writing
SQL. If a reference is not in the resolved schema, it does not exist - do not
guess it.

## Rule

This skill names no warehouse, dialect, or physical table. Everything physical
comes from `di0 schema`, driven by the profile.
