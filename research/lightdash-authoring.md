# Can the Lightdash API author SQL-based charts and dashboards?

Resolves [#53](https://github.com/mmurakaru/di0/issues/53).
Researched 2026-07-26 against the official docs (docs.lightdash.com API reference, generated from Lightdash's OpenAPI spec) and the `lightdash/lightdash` source on GitHub.

## Direct answer

**Yes.**
Raw-SQL charts are first-class, API-authorable content in Lightdash via the SQL Runner's "saved SQL charts" (`savedSql`), independent of dbt explores.
Dashboards are also API-authorable and natively support `sql_chart` tiles alongside `markdown`, `heading`, and `loom` tiles, plus tabs and dashboard-level filters that can target SQL-chart result columns.
Explore-based saved charts (built on dbt models/metrics) are a separate, parallel chart type; di0 does not need them.

Confidence: high.
Sources: [create-sql-chart](https://docs.lightdash.com/api-reference/sql-runner/create-sql-chart.md), [create-dashboard](https://docs.lightdash.com/api-reference/projects/create-dashboard.md), and the type definitions in [`packages/common/src/types/dashboard.ts`](https://github.com/lightdash/lightdash/blob/main/packages/common/src/types/dashboard.ts) and [`packages/common/src/types/sqlRunner.ts`](https://github.com/lightdash/lightdash/blob/main/packages/common/src/types/sqlRunner.ts).

## Authentication

Personal Access Tokens, sent as `Authorization: ApiKey <token>`.
Confirmed in source: the backend registers `passport-headerapikey` with `{ header: 'Authorization', prefix: 'ApiKey ' }` in [`packages/backend/src/controllers/authentication/strategies/apiKeyStrategy.ts`](https://github.com/lightdash/lightdash/blob/main/packages/backend/src/controllers/authentication/strategies/apiKeyStrategy.ts), and the SQL Runner controller wraps its routes in `@Middlewares([allowApiKeyAuthentication, isAuthenticated])` ([`sqlRunnerController.ts`](https://github.com/lightdash/lightdash/blob/main/packages/backend/src/controllers/sqlRunnerController.ts)).
PATs are created in user settings or via `POST /api/v1/user/me/personal-access-tokens` ([docs](https://docs.lightdash.com/api-reference/my-account/create-personal-access-token.md), [PAT guide](https://docs.lightdash.com/references/workspace/personal-tokens.md)).
Session-cookie auth also works but is irrelevant for an adapter.
Confidence: high (read from source).

## Endpoints and payloads

All endpoints are project-scoped; the adapter needs a `projectUuid` the way the Metabase adapter needs a database id.

### Create a space (di0 collection analogue)

`POST /api/v1/projects/{projectUuid}/spaces`

```json
{ "name": "Revenue Overview", "parentSpaceUuid": null, "access": [] }
```

Spaces nest via `parentSpaceUuid`, which covers di0's `own_collection` / `organize_by_tab` sub-collection behavior.
Source: [create-space](https://docs.lightdash.com/api-reference/roles-&-permissions/create-space.md).
Confidence: high.

### Create a raw-SQL chart

`POST /api/v1/projects/{projectUuid}/sqlRunner/saved`

```json
{
  "name": "Signups per week",
  "description": null,
  "sql": "select date_trunc('week', created_at) as week, count(*) as signups from users group by 1",
  "limit": 500,
  "config": {
    "type": "vertical_bar",
    "fieldConfig": { "x": { "reference": "week" }, "y": [{ "reference": "signups" }] },
    "display": {}
  },
  "spaceUuid": "<space-uuid>",
  "slug": "signups-per-week"
}
```

Returns `{ "status": "ok", "results": { "savedSqlUuid": "...", "slug": "..." } }`.
`config` is `AllVizChartConfig`: exactly `vertical_bar | line | pie | table` ([`packages/common/src/visualizations/types/index.ts`](https://github.com/lightdash/lightdash/blob/main/packages/common/src/visualizations/types/index.ts)).
`limit` and `description` are required fields; `slug` is optional and used by content-as-code.
Update via `PATCH`-style [update-sql-chart](https://docs.lightdash.com/api-reference/sql-runner/update-sql-chart.md) on `sqlRunner/saved/{uuid}`.
Source: [create-sql-chart](https://docs.lightdash.com/api-reference/sql-runner/create-sql-chart.md) plus `CreateSqlChart` in [`sqlRunner.ts`](https://github.com/lightdash/lightdash/blob/main/packages/common/src/types/sqlRunner.ts).
Confidence: high.

### Validate/run SQL before authoring

`POST /api/v2/projects/{projectUuid}/query/sql` with `{ "sql": "...", "limit": 1 }`.
Async: returns a `queryUuid`; results are fetched from the paginated query-results endpoint.
The older `POST /api/v1/projects/{projectUuid}/sqlRunner/run` (job-id based) is marked deprecated in the OpenAPI spec.
Sources: [execute-sql-query (v2)](https://docs.lightdash.com/api-reference/v2/execute-sql-query.md), [run-sql-query (v1, deprecated)](https://docs.lightdash.com/api-reference/sql-runner/run-sql-query.md).
Confidence: high on paths; medium on the exact results-polling flow (results endpoint schema not read in full).

### Create a dashboard with tiles and tabs

`POST /api/v1/projects/{projectUuid}/dashboards`

`CreateDashboard` requires `name`, `tabs`, `tiles`; optional `description`, `spaceUuid`, `filters`, `parameters`, `config`, `colorPaletteUuid`.
Tile shape (all types): `uuid`, `x`, `y`, `w`, `h` (numbers), `type`, `tabUuid` (nullable), `properties`.
Tile types and their `properties`:

- `sql_chart`: `savedSqlUuid`, `chartName`, optional `title`, `hideTitle`.
- `saved_chart` (explore-based): `savedChartUuid`, optional `title`, `hideTitle`.
- `markdown`: `content` (required), `title` (required), `hideFrame`.
- `heading`: `text` (required), `showDivider`.
- `loom`: `url`, `title`.
- `data_app`: `appUuid`, `title`.

Tabs are `{ uuid, name, order, hidden? }`; the client generates tab uuids and points each tile's `tabUuid` at one.
Sources: [create-dashboard](https://docs.lightdash.com/api-reference/projects/create-dashboard.md), `CreateDashboard`/`DashboardTab`/`DashboardSqlChartTileProperties` in [`dashboard.ts`](https://github.com/lightdash/lightdash/blob/main/packages/common/src/types/dashboard.ts).
Confidence: high.

Updates go through [update-dashboards (v1, bulk)](https://docs.lightdash.com/api-reference/projects/update-dashboards.md) or [update-dashboard (v2)](https://docs.lightdash.com/api-reference/v2/update-dashboard.md), which lets a `replace`-style flow keep a stable URL.
Confidence: medium (paths from the docs index; payloads not read in full).

### Content-as-code upserts (alternative authoring surface)

`POST /api/v1/projects/{projectUuid}/code/dashboards/{slug}` upserts a dashboard by slug, with `tiles`, `tabs`, `filters`, `spaceSlug`, and can auto-create the space (`skipSpaceCreate: false`).
A matching [upsert-chart-as-code](https://docs.lightdash.com/api-reference/projects/upsert-chart-as-code.md) exists for charts.
This slug-keyed idempotent surface is arguably a better fit for di0's `replace` semantics than create-then-update.
Source: [upsert-dashboard-as-code](https://docs.lightdash.com/api-reference/projects/upsert-dashboard-as-code.md).
Confidence: high for the dashboard endpoint; medium for whether the as-code chart payload covers saved SQL charts as well as explore charts.

## Mapping di0's DashboardSpec onto Lightdash

di0 concept (`src/di0/deliverable.py`) to Lightdash concept:

- `collection_id` / `own_collection` / `organize_by_tab` -> **space** (+ `parentSpaceUuid` nesting). Clean fit, except spaces are addressed by uuid/slug, not integer id.
- `DashboardSpec` -> **dashboard**; `replace` -> as-code upsert by slug, or v2 update.
- `TabSpec` -> **native dashboard tabs** (`tabs[]` + `tile.tabUuid`). Better fit than Metabase, where di0 had to plan tab placement itself.
- query `CardSpec` -> **two objects**: a saved SQL chart (`sqlRunner/saved`) plus a `sql_chart` tile referencing its `savedSqlUuid`. Charts cannot be embedded inline in the dashboard payload; each is a standalone content item in a space (the `belongsToDashboard` flag exists only for explore charts, per `dashboard.ts`).
- text `CardSpec` -> **markdown tile** (`content` + required `title`) or **heading tile**. Direct fit.
- `size_x/size_y/row/col` -> tile `w/h/y/x`, but the grid is **36 columns** wide (`DEFAULT_COLS = 36` in [`packages/frontend/src/features/dashboardTabs/gridUtils.ts`](https://github.com/lightdash/lightdash/blob/main/packages/frontend/src/features/dashboardTabs/gridUtils.ts)) versus Metabase's 24, so di0's grid planner needs a per-backend column count.
- `display`/`viz` -> `AllVizChartConfig`. **Biggest mismatch**: only `vertical_bar`, `line`, `pie`, `table` exist for SQL charts, so di0's raw viz pass-through cannot promise Metabase-parity (no area, scatter, funnel, big-number, map equivalents on this chart type).
- `parameters`/`params`/`field_filters` -> **dashboard `filters`** (`DashboardFilters = { dimensions, metrics, tableCalculations }` of `DashboardFilterRule` with per-tile `tileTargets`, [`filter.ts`](https://github.com/lightdash/lightdash/blob/main/packages/common/src/types/filter.ts)). For SQL tiles a filter targets a **result column** of the chart's SQL, and the frontend passes `dashboardFilters` into saved-SQL execution ([`DashboardSqlChartTile.tsx`](https://github.com/lightdash/lightdash/blob/main/packages/frontend/src/components/DashboardTiles/DashboardSqlChartTile.tsx); [filters guide](https://docs.lightdash.com/guides/limiting-data-using-filters)). **Model mismatch**: there is no Metabase-style `{{variable}}` templating inside the SQL text, so di0's variable-to-widget wiring becomes column-level post-filters on the query result rather than SQL substitution; anything relying on variables changing the query shape (date grain switches, table swaps) does not translate. Confidence: high that column filters work on SQL tiles, medium on exact `tileTargets` payload shape for SQL tiles.
- No equivalent of Metabase's archive/trash-scoped duplicate handling; slugs are the uniqueness handle.

## Closest-path note (not needed, but for completeness)

Had raw-SQL charts not been authorable, the fallback would have been Lightdash **virtual views** ([create-virtual-view](https://docs.lightdash.com/api-reference/sql-runner/create-virtual-view.md)): register the raw SQL as a virtual explore, then author explore-based saved charts on it.
That path remains useful if di0 ever needs richer viz types or semantic-field filters on top of raw SQL, at the cost of an extra intermediate object per query.
Confidence: medium (endpoint verified, workflow inferred from docs).
