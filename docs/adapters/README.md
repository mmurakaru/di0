# Adapters

The core defines four ports; adapters are the swappable drivers plugged into
them. The warehouse, dialect, schema source, and execution target are all chosen
in `di0.profile.yml` - the core and skills never name an adapter.

| Port | Adapters | Profile key |
|---|---|---|
| SchemaPort | dbt manifest, Strapi content-types, Drizzle snapshot | `schema_source` |
| DialectPort | sqlglot (any dialect) | `dialect` |
| ValidationPort | sqlglot offline, EXPLAIN (live) | `validation` |
| ExecutionPort | Metabase, http-rows, no-op | `execution` |

Adapter-specific options and auth live in a page per adapter:

- [Metabase](metabase.md) - execute, author dashboards, auth schemes
