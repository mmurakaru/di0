# ADR 0001: Ports and adapters, with data independence as the core invariant

- Status: accepted
- Date: 2026-06-30

## Context

Analytics code commonly re-encodes the warehouse schema by hand - physical table
and column names as string literals scattered across scripts. The same schema
knowledge then drifts across several places, and a rename upstream fails silently
at query time. This is precisely the regression that Codd's logical/physical
*data independence* was invented to prevent.

## Decision

Build di0 as a hexagonal (ports-and-adapters) system with four ports - Schema,
Dialect, Validation, Execution - and keep one invariant absolute:

> If a physical table name, column name, dialect, or warehouse appears as a
> string literal in the core, it is a bug.

The core references a logical schema and resolves everything physical at the
edges through adapters. The warehouse is configuration (one profile, one adapter
module), not code.

## Consequences

- The core is portable and testable without a warehouse; adapters isolate every
  dialect- and vendor-specific concern.
- We accept one composition edge (the registry) where adapter names appear, and
  enforce the invariant everywhere else with a lint (see the invariant-guard
  slice).
- Swapping schema source, dialect, validation tier, or execution target is a
  profile change, proven by running the same flow over multiple sources.
