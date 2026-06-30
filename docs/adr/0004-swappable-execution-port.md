# ADR 0004: Execution is a swappable port; execute is portable, author is optional

- Status: accepted
- Date: 2026-06-30

## Context

PRD open question: reuse a BI tool's dataset API for execution (which also gives
artifact authoring) versus a direct warehouse driver. We also need to decide
whether di0 is bound to one output platform.

## Decision

Output is a port, not a binding. The ExecutionPort has two capabilities with
different portability:

- `execute(sql) -> rows` is **portable** - every adapter implements it (a BI
  dataset API, a direct driver, or a plain stdout/CSV sink).
- `author(...)` (cards, dashboards, tabs) is **BI-tool-specific** and therefore
  an optional capability; adapters that cannot author simply do not, and report
  so via `supports_authoring`.

A BI dataset API is the default execution adapter because it provides both
execution and authoring through one interface. The execution target is chosen in
the profile.

## Consequences

- Row execution is provable across multiple adapters (demonstrated with a second
  execute-only adapter), so the output platform is genuinely swappable.
- Deliverable authoring stays adapter-dependent and honest about it, rather than
  pretending dashboards are portable across BI tools.
- A direct-driver adapter remains available when authoring is not needed.
