# Metabase execution adapter

`execution: metabase`

Runs validated SQL through Metabase's REST API and, optionally, authors cards and
multi-tab dashboards. It provides both ExecutionPort capabilities: `execute`
(rows) and `author` (deliverables).

## Profile

```yaml
execution: metabase
metabase_url: https://metabase.example.com
metabase_database_id: 7              # the database's id in Metabase
metabase_auth: api-key               # api-key (default) | session
metabase_api_key_env: DI0_METABASE_API_KEY   # env var holding the API key
# metabase_session_env: DI0_METABASE_SESSION # env var holding a session token (auth: session)
```

The credential is always read from an environment variable, never stored in the
profile.

## Authentication

Metabase documents two auth schemes; di0 supports both.

### API key (default, recommended)

Create an API key in Metabase (Admin settings -> Authentication -> API keys),
then export it:

```bash
export DI0_METABASE_API_KEY='mb_...'
```

Sent as the `x-api-key` header.

### Session token (`auth: session`)

For deployments that do not expose API keys. Obtain a session token (Metabase's
`POST /api/session` returns one as `id`) and export it:

```bash
export DI0_METABASE_SESSION='...'
```

Sent as the `X-Metabase-Session` header. This is the non-default option; prefer an
API key where available.

## Commands

```bash
di0 query  "<sql>"                   # validate, then execute and print rows
di0 author deliverables/<spec>.yml   # build a multi-tab dashboard from validated queries
```

Both validate before they touch Metabase. `author` issues `POST /api/card` per
query, `POST /api/dashboard`, then `PUT /api/dashboard/:id` with the tabs and
card placements.

## Live validation

With `validation: explain`, di0 proves each query with `EXPLAIN` over this same
connection before running or authoring it - no compute cost.
