# How much authoring control does the Hex CLI/API expose?

Resolves [#54](https://github.com/mmurakaru/di0/issues/54).
Researched 2026-07-26 against primary sources: the Hex CLI binary itself (`hex` v1.2026.07.21 `--help` output, downloaded from the official [hex-inc/hex-cli releases](https://github.com/hex-inc/hex-cli/releases)), the published OpenAPI spec at <https://static.hex.site/openapi.json> (Hex API 1.0.0), the published Hex file JSON Schema at <https://static.hex.site/hex-file-schema.json> (registered on SchemaStore for `*.hex.yaml`), and learn.hex.tech docs pages.

## Direct answer

Programmatic authoring end to end without the UI is possible for everything except the final "Publish" click, and the primitive-level cell API only covers code/SQL/markdown cells.
There are two authoring channels with very different power:

1. **Primitive channel (CLI `hex cell` / API `/v1/cells`):** create a project and add `code`, `sql`, and `markdown` cells only. No chart cells, no filter cells, no app layout.
2. **Whole-project channel (CLI `hex project import` of a `.hex.yaml` file):** the Hex file format carries the entire project, including chart cells, filter cells, text cells, shared filters, and the full published-app layout (`appLayout` with tabs, grid rows, and 120-unit columns). This is the channel a DashboardSpec compiler would target.

**The one hard gap: publishing.**
Neither the CLI (`hex app` exposes only `run`) nor the HTTP API (the only publish endpoint in the OpenAPI spec is `POST /v1/guides/publish`, for guides, not apps) can publish a project's app.
Publishing is a UI action in the App builder ([app-builder docs](https://learn.hex.tech/docs/share-insights/apps/app-builder)), and several read endpoints explicitly 422 on unpublished projects ([API overview](https://learn.hex.tech/docs/api/api-overview)).
Confidence: high (documented absence in both the CLI self-help and the OpenAPI spec).

## Command inventory (from `hex --help`, v1.2026.07.21)

Source: help output of the official release binary; the docs page <https://learn.hex.tech/docs/api-integrations/cli> reproduces the top-level list.

Top-level command groups: `app`, `auth`, `cell`, `collection`, `config`, `connection`, `group`, `install`, `project`, `run`, `suggestion`, `thread`, `user`, `guide`, `context`.
Global flags include `--profile`, `--json`, `-q`, `-v`.

### `hex project` - "Manage and run Hex projects"

| Subcommand | What it does |
| --- | --- |
| `create <title> [-d <desc>]` | Create a new (empty, draft) project. Title and description only. |
| `list` | List all accessible projects. |
| `get` | Get details of a specific project. |
| `open` | Open a project in the browser. |
| `run <project_id> [--no-cache]` | Run the draft notebook version of a project. |
| `export <project_id> [--hex-version draft\|latest\|N] [-o path]` | Export a project as a YAML file (`draft` is the notebook version, `latest` is the latest published app version). |
| `import <file>` | Import a project from a YAML file. |

### `hex cell` - "Manage project cells"

| Subcommand | What it does |
| --- | --- |
| `list <project_id>` | List cells in a project. |
| `get <cell_id>` | Get a single cell by ID. |
| `create <project_id> -t <type> -s <source> ...` | Create a cell. `--cell-type` choices are exactly `"code"`, `"sql"`, `"markdown"`. SQL cells take `--data-connection-id` and `--output-dataframe`. Placement via `--after-cell-id`, `--parent-cell-id`, `--child-position first\|last`. |
| `update <cell_id> [-s <source>] [--data-connection-id] [--output-dataframe]` | Update a cell's source and/or data connection. |
| `delete <cell_id>` | Delete a cell. |
| `run <cell_id> [--dry-run] [--with-output]` | Run a cell and its dependencies. |

### `hex app` - "Manage and run Hex apps"

| Subcommand | What it does |
| --- | --- |
| `run <project_id> [-i key=value ...] [--wait/--no-wait]` | Run a Hex app (the published version) with input parameters. |

That is the entire `hex app` group.
There is no `hex app publish`, no layout subcommand, and no app-editing subcommand.
Confidence: high (verbatim `--help` output).

### `hex run` - "Manage running Hex projects and apps"

`list`, `status`, `cancel` - run lifecycle only.

## HTTP API inventory (OpenAPI spec, Hex API 1.0.0)

Source: <https://static.hex.site/openapi.json>; prose reference at <https://learn.hex.tech/docs/api/api-reference>.
Authoring-relevant endpoints:

- `POST /v1/projects` (CreateProject: title + description only), `GET/PATCH /v1/projects/{id}`, `GET /v1/projects`.
- `POST /v1/cells` (CreateCell), `GET /v1/cells`, `GET/PATCH/DELETE /v1/cells/{cellId}`, `GET /v1/cells/{cellId}/output`, `GET /v1/cells/{cellId}/image`.
  CreateCell's `cellType` enum is exactly `CODE`, `SQL`, `MARKDOWN`, with matching `codeCell`/`sqlCell`/`markdownCell` content variants and the same placement options as the CLI.
  Read responses, by contrast, enumerate the full cell zoo (`VEGA_CHART`, `CHART`, `METRIC`, `FILTER`, `PIVOT`, `MAP`, `EXPLORE`, `TEXT`, ...), so richer cell types are readable but not creatable through this endpoint.
- `POST /v1/projects/export` (ExportProject, version `draft`/`latest`/N).
  No `import` path appears in the published spec, although `ImportProjectApiResource` / `ImportProjectWarningsApiResource` response schemas (whose warning fields include `appLayout`) exist in its components.
  Inferred: `hex project import` calls an import endpoint that is not yet documented in the public paths list. Confidence: medium for the inference, high that no import path is documented.
- `POST /v1/projects/{id}/runs` (RunProject, runs the latest published version; `updatePublishedResults` only refreshes cached app state), plus run status/cancel, sharing PATCHes, collections, groups, users, data connections, threads, embedding presigned URLs.
- Publish exists only for guides (`POST /v1/guides/publish`). No project/app publish endpoint. Confidence: high.

## Auth requirements

Documented at <https://learn.hex.tech/docs/api/api-overview> and <https://learn.hex.tech/docs/api-integrations/cli>:

- API and CLI access require a **Team or Enterprise plan** and admin-enabled API access in workspace settings.
- **Personal access tokens** (`hxtp_` prefix): require Editor or higher workspace role, mirror the user's own permissions, must expire within an admin-configured window (7-120 days), auto-revoked on deactivation.
- **Workspace tokens** (`hxtw_` prefix): admin-created, can be non-expiring, scoped to read projects / run projects / read-write admin resources (users, groups, collections, data connections).
  Documented workspace-token scopes do not include creating or editing projects, so authoring flows should assume a personal access token. Inferred; confidence: medium.
- CLI login: `hex auth login` (browser flow, per-workspace profiles, credentials in the system keyring) or `--token-from-env` (`HEX_CLI_LOGIN_TOKEN`) for CI. Tokens are workspace-scoped; multi-workspace use means one profile per workspace.

## Layout control: what exists, what doesn't

The Hex file format is the real layout API.
Its published JSON Schema (<https://static.hex.site/hex-file-schema.json>) defines, at the top level: `appLayout`, `cells`, `sharedFilters`, `projectAssets`, `meta`, and more.
Documented structure:

- `AppLayout`: `fullWidth` flag, `visibleMetadataFields`, and `tabs` (required).
- `AppTab`: `name` + `rows`.
- `GridRow`: `columns`.
- `GridColumn`: `start`/`end` indices on a **120-unit grid** plus `elements`.
- `GridElement`: `cellId` or `sharedFilterId`, `height`, `hideOutput`, `showLabel`, `showSource`, type `CELL` or `SHARED_FILTER`.
- Cell definitions include `SqlCell`, `ChartCell`/`ChartCellV2` (full viz config: series, axes, colors, facets, legends), `MarkdownCell`, `TextCell`, `MetricCell`, `FilterCell`, `PivotCell`, `MapCell`, `CollapsibleCell`, and input cells.
- `SharedFilter`: typed app-level filters (dropdown, multiselect, date, slider, ...) with operators (`IS_ONE_OF`, `DATE_BETWEEN`, ...) and auto/manual links to dataframes - Hex's equivalent of dashboard filters.

The import/export docs confirm the format "represents the logic of your entire project (including the layout of an app)" and is "fully compatible with all features of Hex" (<https://learn.hex.tech/docs/explore-data/projects/import-export>; also <https://learn.hex.tech/docs/explore-data/projects/git-export>).
Confidence: high (schema is a primary source published by Hex).

What does not exist programmatically:

- No incremental layout mutation. The CLI/API cell primitives place cells in the notebook order only; app layout changes require exporting, editing, and re-importing the whole YAML (or the UI). Documented absence; confidence: high.
- No chart/filter/text cell creation via `hex cell create` or `POST /v1/cells`. Documented; confidence: high.
- No programmatic publish (see above).

## Where the model mismatch bites for a grid-of-cards DashboardSpec

Hex is notebook-first: a project is a DAG of cells, and the app is a projection of those cells onto a grid ([apps introduction](https://learn.hex.tech/docs/share-insights/apps/apps-introduction)).
Mapping di0's DashboardSpec (tabs, cards with SQL + viz + grid position, text cards, filters) onto that model:

**Maps cleanly (via YAML import):**

- Tabs -> `appLayout.tabs` (named `AppTab`s). Direct fit.
- Card grid position -> `GridRow`/`GridColumn` with `start`/`end` on a 120-unit grid plus element `height`. Comparable to Metabase's 24-unit dashboard grid, just row-structured: columns live inside rows, so layout is rows-of-columns rather than free 2D placement. A card that spans multiple rows has no direct representation.
- SQL card -> one `SqlCell` (needs a `dataConnectionId`) + one `ChartCell` reading its output dataframe, then a `GridElement` referencing the chart cell. Two linked entities per card instead of Metabase's one card object.
- Text card -> `MarkdownCell`/`TextCell` + grid element.
- Dashboard filters -> `sharedFilters` with links to dataframes, placed as `SHARED_FILTER` grid elements.

**Bites:**

1. **Publish is manual.** A wrapper can create/update the entire draft but a human must click Publish in the App builder for every change to go live. This breaks unattended CI-style authoring; confidence: high.
2. **No card-level idempotent updates for viz.** Since chart cells are not creatable/updatable via the cell API, any change to a card's viz settings means regenerating and re-importing the full project YAML. `hex project import` creates a project (with import warnings, including `appLayout` warnings per the OpenAPI components); whether it can update an existing project in place is not documented. Inferred risk: update-in-place may require export/diff/import gymnastics or produce new projects per deploy; confidence: medium.
3. **Two-layer coupling.** Every visual card is a chart cell bound to a SQL cell's output dataframe by name; renames or SQL swaps must keep dataframe names consistent across `cells` and `appLayout`, which di0 would have to manage itself.
4. **Row-structured grid.** DashboardSpec positions expressed as free (x, y, w, h) boxes must be normalized into rows of columns; arbitrary overlapping or row-spanning placements cannot be expressed.
5. **Run model differs.** The published app re-runs the notebook (`autoRerunApp`, `cachePublishedAppState` in `ProjectMetadata`); there is no per-card query object with its own cache, so per-card freshness control is coarser than Metabase's.

## Sources

- CLI `--help` output, hex v1.2026.07.21 binary from <https://github.com/hex-inc/hex-cli/releases> (primary).
- <https://learn.hex.tech/docs/api-integrations/cli> (CLI docs).
- <https://hex.tech/blog/introducing-the-hex-cli/> and <https://learn.hex.tech/changelog/2026-04-07> (CLI launch, capabilities framing).
- <https://static.hex.site/openapi.json> (Hex API 1.0.0 OpenAPI spec, primary).
- <https://learn.hex.tech/docs/api/api-reference> and <https://learn.hex.tech/docs/api/api-overview> (API reference, auth/token docs).
- <https://static.hex.site/hex-file-schema.json> (Hex file JSON Schema, primary; registered in the SchemaStore catalog).
- <https://learn.hex.tech/docs/explore-data/projects/import-export> and <https://learn.hex.tech/docs/explore-data/projects/git-export> (file format and git export).
- <https://learn.hex.tech/docs/share-insights/apps/app-builder> and <https://learn.hex.tech/docs/share-insights/apps/apps-introduction> (app builder, publishing, layout).
