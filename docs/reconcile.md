# Reconcile - cross-source questions

Some questions span sources that live in different systems (e.g. content in one
database, traffic in another). They can't be answered by a single query. `reconcile`
runs one validated query per source, then joins the fetched results **locally** -
the cross-source join never runs in any source warehouse.

## How it works

1. Each named **source** is a full profile (its own schema/dialect/validation/execution).
2. Each **query** runs against one source: validated against that source's schema, then
   executed there - reduced/aggregated at the source so only small result sets come back.
3. The **combine** SQL joins those results in-process via DuckDB (the CombinePort). It's
   real SQL over the fetched tables - no DataFrame DSL, consistent with di0's core.

Sources only fetch rows; the join is local. This scales by *reduce-at-source, combine-locally*
- keep each per-source query aggregated so the local join stays small.

## Spec

```yaml
# reconcile.yml
sources:
  a: { schema_source: ..., dialect: ..., validation: ..., execution: ... }   # + adapter options
  b: { schema_source: ..., dialect: ..., validation: ..., execution: ... }
queries:
  - { name: left,  source: a, query: left.sql }     # table name the combine refers to
  - { name: right, source: b, query: right.sql }
combine: combine.sql                                 # SELECT ... FROM left JOIN right ...
```

```bash
di0 reconcile reconcile.yml     # prints the combined rows
```

## Scope

`reconcile` produces the cross-source **answer** (rows). Turning that into a *live*
BI dashboard requires a materialization sink (a cross-source result is otherwise a
snapshot); that sink is a future execution adapter.
