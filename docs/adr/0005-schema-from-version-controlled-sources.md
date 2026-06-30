# ADR 0005: Resolve schema from version-controlled sources; push semantics upstream

- Status: accepted
- Date: 2026-06-30

## Context

PRD open questions: maintain a local schema catalog or not; adopt a hosted
metadata/semantic service or use a local metadata server; and how much business
semantics should live in the wrapper.

## Decision

- **No hand-maintained schema mirror.** The SchemaPort resolves from a source
  that already describes the schema - a dbt `manifest.json`, a content-type
  schema, an ORM snapshot - read offline from version control where possible.
- **Push business semantics upstream.** Anything expressible in the schema source
  (metrics, accepted values, tier buckets, filters) belongs there, where it is
  canonical and derivable, not copied into the wrapper.
- **Keep only non-derivable knowledge local,** in a small agent-context file, not
  scattered through code.
- A hosted metadata/semantic service is an alternative SchemaPort/ExecutionPort
  adapter, not a prerequisite; the offline manifest path works with no platform.

## Consequences

- A single source of truth; a rename upstream is caught by validation rather than
  silently diverging from a prose mirror.
- The wrapper stays thin and gets thinner as more semantics move upstream.
- Adopting a hosted platform later is an adapter swap, not a rewrite.
