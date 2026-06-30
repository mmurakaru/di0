# ADR 0002: Implement the core in Python, wrapped by agent skills

- Status: accepted
- Date: 2026-06-30

## Context

PRD open question: is di0 a library, or just agent skills plus configuration, and
in which language? The validation loop is the project's IP and must lean on a
real SQL parser/transpiler with dialect-aware, schema-aware qualification.

## Decision

Implement the core ports and adapters as a Python package, wrapped by thin agent
skills that shell out to its CLI and read the profile.

The deciding constraint is the ecosystem: sqlglot (multi-dialect parsing and
schema-aware qualification) and the offline validators (SQLMesh, dbt) are Python,
and there is no equivalent-tier alternative in another language. Choosing another
language would mean shelling out to Python for the core step anyway. The schema
sources (dbt `manifest.json`, content-type JSON, ORM snapshots) and the execution
APIs are language-neutral, so they impose no constraint.

## Consequences

- The validation loop gets first-class unit tests, where the IP belongs.
- Skills stay the agnostic verb layer; they name no warehouse and call only the
  CLI, so they are language-agnostic over the core.
- We take a Python runtime dependency for anyone embedding di0 directly.
