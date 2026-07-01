# di0 - data independence, zero hard-coded references

A thin, break-safe analytics wrapper. di0 lets an agent ask analytics questions
and build dashboards while owning **zero schema knowledge**: every table, column,
join, and metric is resolved live from a schema source, and every query is
validated against that schema before it runs - so schema drift breaks the build,
not a 2am dashboard.

## The principle

Hard-coding physical table and column names into application code is the kind of
coupling Codd's *data independence* was meant to avoid. di0 leans the other way:
the core references a logical schema and resolves the physical details at the edges.

> Aim: keep physical table and column names out of the core - resolve them from the
> schema source instead. An invariant check flags stray references.

The heart of di0 is the validation loop, not any single query:

```
resolve refs (SchemaPort) -> compose SQL (DialectPort)
  -> validate against the schema (ValidationPort) -> only then execute (ExecutionPort)
```

For questions that span sources in different systems, di0 also does
[cross-source reconcile](docs/reconcile.md): fetch reduced results per source, then
join them locally.

## Ports and adapters

di0 is hexagonal: an agnostic core that talks to four swappable ports. The
warehouse is configuration, not code.

| Port | Responsibility | Default adapter |
|---|---|---|
| **SchemaPort** | Resolve tables, columns, joins, metrics | dbt `manifest.json` |
| **DialectPort** | Render SQL for a target dialect | sqlglot |
| **ValidationPort** | Prove a query before running it | sqlglot offline |
| **ExecutionPort** | Run validated SQL; optionally author artifacts | (pluggable) |

The available adapters and their options live in [docs/adapters/](docs/adapters/).
Cross-source questions (join results from several sources locally) are covered in
[docs/reconcile.md](docs/reconcile.md).

Everything warehouse-specific lives in one adapter module and one profile:

```yaml
# di0.profile.yml
schema_source: dbt-manifest
manifest_path: tests/fixtures/manifest.json
dialect: snowflake
validation: sqlglot-offline
execution: noop
```

## Quickstart

```bash
uv sync --dev
uv run di0 init   # scaffold your gitignored workspace/ from examples/ (put your queries/profiles/specs there)
uv run di0 validate "SELECT customer_id, current_arr FROM analytics.dim_customers"
uv run pytest -q
```

A query over unknown columns fails before it ever reaches a warehouse.

To execute a validated query (`di0 query`) or author a dashboard (`di0 author`),
point the profile at an execution adapter. Execution is always gated on
validation, and authoring is an optional capability - a row-only adapter refuses
it. Adapter-specific options, endpoints, and auth live in
[docs/adapters/](docs/adapters/).
