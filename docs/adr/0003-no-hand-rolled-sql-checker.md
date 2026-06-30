# ADR 0003: No hand-rolled SQL checker; offline sqlglot default, EXPLAIN option

- Status: accepted
- Date: 2026-06-30

## Context

PRD open question: which validation tier, and do we build a checker? Static
validation is a solved problem at every level, from a zero-build database
`EXPLAIN` to standalone SQL compilers. Hand-rolling a dialect-aware checker would
be reinventing mature tooling.

## Decision

Never hand-roll a SQL checker. The ValidationPort is an abstraction with two
shipped adapters, selected by the profile:

1. **Offline (default):** sqlglot qualifies the query against the schema derived
   from the version-controlled manifest - no warehouse connection, catches
   unknown tables/columns at build time.
2. **Live `EXPLAIN`:** the warehouse parses and resolves every object without
   executing (no compute cost), reusing the existing execution connection -
   break-safety against the live schema.

Anything expressible as a model can additionally be checked upstream by the
dbt/SDF compiler; we do not duplicate that.

## Consequences

- Offline checking runs in CI with no credentials, so drift is a red build.
- The live tier catches drift against the real warehouse but needs a connection
  and does not see things that are not schema (e.g. semi-structured key typos).
- Both adapters satisfy one interface, so a project picks its trade-off in the
  profile without core changes.
