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

### Deliverable spec options

```yaml
name: My dashboard
collection_id: 123            # place cards + dashboard in this collection (omit = default/root)
tabs:
  - name: Overview
    cards:
      - text: "# Overview\n\nSection narrative in **markdown**."   # text card (no query)
        size_x: 24
        size_y: 2
      - title: Total customers
        query: ../queries/customers.sql
        display: scalar
        row: 2                                   # explicit grid placement (omit = auto-stack)
        col: 0
        size_x: 6
        size_y: 4
      - title: Monthly total
        query: ../queries/monthly.sql
        display: line
        description: What this card measures.     # card annotation
        x_label: Month                            # axis-label shorthands
        y_label: Total (USD)
        viz:                                      # raw visualization_settings pass-through
          graph.series_breakout: true
          column_settings: {}
```

- **Query cards** (`query:`) are validated before authoring. **Text cards**
  (`text:`, markdown) are virtual - no query, not validated.
- **`viz`** passes straight through to Metabase `visualization_settings` (and wins
  over the `x_label`/`y_label` shorthands on conflict), so series breakout, pie
  dimensions, `scalar.field`, `column_settings`, y-axis scale, etc. are reachable
  without di0 modelling each one.
- **`row`/`col`** place a card on the grid explicitly; omit to auto-stack.
- `collection_id` keeps a deliverable out of the shared root. To create (or reuse) a
  collection first, the adapter exposes `ensure_collection(name, parent_id)`.
- **`replace: true`** (or `di0 author --replace`) makes authoring idempotent: it
  archives an existing same-name dashboard in the collection (and its query cards)
  before authoring, so re-runs replace rather than duplicate.
- **`organize_by_tab: true`** files each tab's cards into a sub-collection named
  after the tab (created under `collection_id`), keeping the collection navigable;
  the dashboard itself stays in the parent collection.

## Live validation

With `validation: explain`, di0 proves each query with `EXPLAIN` over this same
connection before running or authoring it - no compute cost.
