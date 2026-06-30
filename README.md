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

To execute a validated query and return rows, point the profile at an execution
adapter (e.g. `execution: metabase` with `metabase_url` and
`metabase_database_id`) and run:

```bash
export DI0_METABASE_API_KEY=...   # the API key is read from the environment, never the profile
uv run di0 query "SELECT customer_id, current_arr FROM analytics.dim_customers"
```

Execution is gated on validation: a query that fails validation never reaches the
warehouse.

A dashboard is a versioned spec built only from validated queries. With an
authoring-capable execution adapter:

```bash
uv run di0 author deliverables/arr_overview.yml
```

Every query in the spec is validated before any card is created; row-only
adapters (which cannot author) refuse the request.
