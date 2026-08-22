# ADR 0007: Portable semantic references; resolve metrics from an interchange artifact

- Status: proposed
- Date: 2026-08-22

## Context

A deliverable card today names a metric only as free text in its viz config and
carries the real calculation in a hand-written SQL file next to the spec. The
same metric - "revenue", "active accounts", a conversion rate - is therefore
re-derived in raw SQL in every bundle that needs it. The physical columns and the
aggregation live in each query, so a rename or a redefinition must be chased
through every deliverable by hand. This is the duplication a semantic layer
removes: define a metric once, reference it by name everywhere.

Two forces constrain how di0 may add this.

- ADR 0005 already decided that business semantics belong upstream, in the schema
  source, not in the wrapper: "Anything expressible in the schema source (metrics,
  accepted values, tier buckets, filters) belongs there... A hosted metadata /
  semantic service is an alternative SchemaPort adapter, not a prerequisite." So
  di0 must not become the home of metric definitions.
- ADR 0001 keeps the core free of any physical name and any tool name. A metric
  layer must not smuggle table names, column names, or a BI-tool schema into the
  core.

Metric definitions in the wild are written in several incompatible conventions -
a BI tool's `meta` blocks in a dbt project, a metrics engine's model files, a
warehouse's own metric objects. None of these is understood by every BI tool, so
picking one convention would tie di0 to one vendor. A vendor-neutral interchange
format for semantic metadata (metrics, dimensions, datasets, relationships)
exists for exactly this reason: definitions authored in one tool can be consumed
in another without re-authoring. We refer to it here as the interchange artifact.

## Decision

Add a portable semantic layer as a resolve-and-compile capability, not as a store
of definitions. Three parts, no new port.

- **A new SchemaPort adapter reads the interchange artifact.** The artifact is a
  version-controlled file (or a directory of files) at a path named in the
  profile - the same shape as pointing the dbt adapter at a compiled manifest.
  The adapter's `resolve()` flattens the artifact's datasets and fields into the
  existing `Schema` map, so validation keeps working unchanged. Metric
  definitions are exposed through a separate accessor; they never enter the frozen
  `Schema` type.

- **A resolver composes SQL from a metric reference at run time.** Given a metric
  name plus dimensions and filters, the resolver reads the metric's stored
  expression from the artifact and emits SQL. It infers nothing. The definitions
  are authored upstream; di0 composes a query from them, it does not compose the
  definitions. The emitted SQL then flows through the existing loop unchanged:
  `DialectPort.compose` -> `ValidationPort.validate` -> `ExecutionPort.execute`
  or `author`. So policy denial and the audit ledger apply with no new code path.

- **The artifact is produced upstream, by a converter, once per change.** A team
  that keeps its metrics in a BI tool's `meta` convention runs a converter that
  maps that convention into the interchange format and commits the result. The
  mapping is deterministic - an aggregation keyword plus a column becomes a SQL
  expression, a declared join becomes a relationship. di0 only ever reads the
  produced artifact. The converter is out of scope for di0 and lives with the
  upstream project, so di0 stays driver-free and definition-free.

Because the output of the resolver is ordinary validated SQL, the same metric
definition renders through any ExecutionPort di0 already has. A metric defined
once is served to every supported authoring target from the one definition.

### Rejected alternatives

- **Model metrics as first-class core entities.** Widening `Schema` or adding a
  metric type to the core would break the lean-core invariant and ADR 0005, and
  would force a conformance-kit change for every SchemaPort adapter. Rejected.
- **Adopt one BI tool's metric convention directly.** Reading one vendor's `meta`
  schema into the core would tie di0 to that vendor and would not serve a second
  BI tool from the same definition. Rejected in favour of the vendor-neutral
  interchange format.
- **Infer metric definitions at run time.** Non-deterministic, unauditable, and it
  would make di0 the source of truth. Rejected; definitions are read from a fixed
  upstream artifact.

## Consequences

- A metric is defined once, upstream, and referenced by name in any deliverable.
  A redefinition changes one artifact, not every bundle.
- The core is untouched: no new port, no change to the `Schema` type, so the
  conformance kit and the guard stay green. The new SchemaPort adapter must pass
  `check_schema_port`; the resolver lives in the core and names nothing physical.
- Provenance improves. The audit record for a composed metric query can carry the
  metric name and a digest of the artifact, so the ledger answers which definition
  produced a query, not only which SQL ran.
- The hard part is metric-expression translation. Simple aggregations map
  cleanly; ratios, filtered measures, and templated expressions need care in the
  converter and must be proven against the validator. This is the spike's focus.
- A later native reader (a BI tool that consumes the interchange format directly)
  is an ExecutionPort improvement, not a rewrite - the swap promised by ADR 0001
  and ADR 0005.
- Extending a deliverable card to carry a metric reference (`metric:`,
  `dimensions:`, `filters:`) instead of a raw `query:` is a follow-on slice; this
  ADR covers the resolve-and-compile foundation the card grammar will build on.
