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

## Dependent queries (large sources)

When one source is huge, you don't want to fetch it whole just to join. A query can
depend on another and pull only the keys it needs: it declares `depends_on` + `keys`,
and its SQL uses a `{keys}` placeholder that di0 fills with the dependency's distinct
key values (a SQL IN-list).

```yaml
queries:
  - { name: approvals, source: events, query: approvals.sql }         # small: the keys
  - { name: words, source: warehouse, query: words.sql,               # huge: fetch only those keys
      depends_on: approvals, keys: segment_id }
combine: combine.sql
```

```sql
-- words.sql : only the segments 'approvals' referenced, not the whole table
SELECT id AS segment_id, word_count FROM huge_table WHERE id IN ({keys})
```

Independent queries run first; dependents run once their dependency is available
(cycles / missing deps are reported). This is how di0 iterates over a large dataset -
reduce to keys on one side, fetch just those on the other.

## Scope

`reconcile` produces the cross-source **answer** (rows). Turning that into a *live*
BI dashboard requires a materialization sink (a cross-source result is otherwise a
snapshot); that sink is a future execution adapter.
