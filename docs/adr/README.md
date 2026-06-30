# Architecture Decision Records

Each ADR records one decision, the context that forced it, and the consequences
we accept. They resolve the open questions raised in the design notes.

- [0001](0001-ports-and-adapters-with-data-independence.md) - Ports and adapters, with data independence as the core invariant
- [0002](0002-python-core-wrapped-by-skills.md) - Python core, wrapped by agent skills
- [0003](0003-no-hand-rolled-sql-checker.md) - No hand-rolled SQL checker; offline sqlglot default, EXPLAIN option
- [0004](0004-swappable-execution-port.md) - Execution is a swappable port; execute portable, author optional
- [0005](0005-schema-from-version-controlled-sources.md) - Resolve schema from version-controlled sources; push semantics upstream

New ADRs start from [0000-template.md](0000-template.md).
