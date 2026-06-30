# Skills - the agnostic verb layer

Each skill encodes a verb (a method) and calls a port through the `di0` CLI - it
never names a warehouse, dialect, or physical table. A skill that names a specific
warehouse is a bug, exactly like a hard-coded table name.

| Skill | Port(s) |
|---|---|
| [resolve-schema](resolve-schema/SKILL.md) | SchemaPort |
| [compose-and-validate](compose-and-validate/SKILL.md) | DialectPort + ValidationPort |
| [execute-and-author](execute-and-author/SKILL.md) | ExecutionPort |
| [investigate](investigate/SKILL.md) | warehouse-blind method |
| [reconcile](reconcile/SKILL.md) | warehouse-blind method |
| [narrate](narrate/SKILL.md) | warehouse-blind method |

Genuinely non-derivable analytical knowledge lives in [`../context/`](../context),
not in code or queries.
