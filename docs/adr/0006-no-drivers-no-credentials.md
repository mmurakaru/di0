# ADR 0006: No data-store drivers, no credentials in the package

- Status: accepted
- Date: 2026-07-26

## Context

Data independence (ADR 0001) keeps physical references out of the core. A second
leak is just as damaging: a data-store driver or a credential inside the package.
Once a driver is a dependency, the package can open its own connection to a
warehouse, and a credential is soon wanted to feed it. That reintroduces the
vendor coupling and the secret-handling surface the ports were meant to remove.

The design already routes every physical concern through a port. Execution goes
through a system that already fronts the warehouse (ADR 0004); schema comes from
version-controlled artifacts read offline (ADR 0005); even EXPLAIN validation
borrows the execution adapter's connection rather than opening one (ADR 0003).
So the package needs no driver and no credential of its own.

## Decision

- **The package declares zero data-store drivers.** Warehouse/DB client drivers
  (psycopg, asyncpg, snowflake-connector-python, mysqlclient, pyodbc, and the
  like) never appear in the dependencies. `duckdb` is not a driver in this sense:
  it is an in-process engine the combine port uses for LOCAL joins, so it is
  allowed, alongside the parser (`sqlglot`) and config (`pyyaml`) dependencies.
- **Credentials always live on the far side of a port.** Adapters read them from
  environment variables at the edge; no secret is stored in, or passed through,
  the core.
- **The guard enforces the no-driver half in CI.** Alongside the string-literal
  scan, `di0 guard` reads pyproject.toml and fails, naming the offender, if any
  declared dependency (runtime, optional, or dependency-group) is a driver. Names
  are matched case-insensitively, ignoring extras and version specifiers.

## Consequences

- The invariant is machine-checked, not merely documented: adding `psycopg2` to
  pyproject.toml turns CI red with a message naming it.
- Reaching a new warehouse stays an adapter-and-profile change; the driver and
  its credential land in the adapter's environment, never in the package.
- The credential half is not yet linted. It rests on the port boundary and
  review; a future check could scan adapters for hard-coded secrets.
