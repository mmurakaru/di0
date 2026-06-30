# di0 - data independence, zero hard-coded references

A thin, break-safe analytics wrapper. di0 lets an agent ask analytics questions
and build dashboards while owning **zero schema knowledge**: every table, column,
join, and metric is resolved live from a schema source, and every query is
validated against that schema before it runs - so schema drift breaks the build,
not a 2am dashboard.

## The principle

Hard-coding physical table and column names into application code is the exact
regression that Codd's *data independence* was invented to prevent. di0 restores
it: the core references a logical schema and resolves it at the edges.

> If a physical table or column name appears as a string literal in the core, it
> is a bug.

The IP is the validation loop, not any single query:

```
resolve refs (SchemaPort) -> compose SQL (DialectPort)
  -> validate against the schema (ValidationPort) -> only then execute (ExecutionPort)
```

## Ports and adapters

di0 is hexagonal: an agnostic core that talks to four swappable ports. The
warehouse is configuration, not code.

| Port | Responsibility | Default adapter |
|---|---|---|
| **SchemaPort** | Resolve tables, columns, joins, metrics | dbt `manifest.json` |
| **DialectPort** | Render SQL for a target dialect | sqlglot |
| **ValidationPort** | Prove a query before running it | sqlglot offline |
| **ExecutionPort** | Run validated SQL; optionally author artifacts | (pluggable) |

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
uv run di0 validate "SELECT customer_id, current_arr FROM analytics.dim_customers"
uv run pytest -q
```

A query over unknown columns fails before it ever reaches a warehouse.
