# Lightdash execution adapter

`execution: lightdash`

Runs validated SQL through Lightdash's SQL runner and, optionally, authors saved
SQL charts and dashboards. It provides both ExecutionPort capabilities: `execute`
(rows) and `author` (deliverables).

## Profile

```yaml
execution: lightdash
lightdash_url: https://lightdash.example.com
lightdash_project_uuid: 0a1b2c3d-...          # the project's uuid in Lightdash
lightdash_api_key_env: DI0_LIGHTDASH_TOKEN    # env var holding the Personal Access Token
lightdash_space: Analytics                    # default space for authored deliverables
```

The credential is always read from an environment variable, never stored in the
profile.

## Authentication

Lightdash uses Personal Access Tokens (PATs). Create one in your Lightdash user
settings, then export it:

```bash
export DI0_LIGHTDASH_TOKEN='...'
```

Sent as the `Authorization: ApiKey <token>` header on every request.

## Commands

```bash
di0 query  "<sql>"                               # validate, then execute and print rows
di0 author workspace/deliverables/<spec>.yml     # build a dashboard from validated queries
```

Both validate before they touch Lightdash. `execute` submits the SQL to the v2
SQL-runner query path (`POST /api/v2/projects/{uuid}/query/sql`) and fetches the
result rows. `author` issues `POST /api/v1/projects/{uuid}/sqlRunner/saved` per
query card, then `POST /api/v1/projects/{uuid}/dashboards` (or the content-as-code
slug upsert, below) with native tabs and tiles.

### Deliverable spec options

```yaml
name: Revenue Overview
collection: Revenue           # the Lightdash space (by name); created if missing
tabs:
  - name: Overview
    cards:
      - text: "# Revenue"     # heading tile
        display: heading
      - text: "Weekly signups and revenue."   # markdown tile (text card, no query)
      - title: Signups per week
        query: ../queries/signups.sql
        display: bar                           # bar | line | pie | table
        width: 6                               # logical size on the neutral 12-unit grid
        height: 4
        viz:                                   # raw Lightdash chart-config pass-through
          fieldConfig:
            x: {reference: week}
            y: [{reference: signups}]
```

- **Query cards** (`query:`) are validated before authoring, then created as saved
  SQL charts (`sqlRunner/saved`) in the space; each is referenced by a `sql_chart`
  tile on the dashboard. **Text cards** (`text:`, markdown) are virtual - no query,
  not validated - and become `markdown` or `heading` tiles.
- **`collection`** names the Lightdash space. Set `lightdash_space` in the profile
  for a default. If neither is set, authoring **refuses** rather than pick a space.
  (Lightdash spaces are addressed by uuid/slug, so `collection_id` is not used here.)
- **`display`** maps to a Lightdash chart type: `bar` -> `vertical_bar`, `line`,
  `pie`, `table`.
- **`width`/`height`** are logical sizes on the neutral 12-unit grid and scale x3
  onto Lightdash's 36-column grid; when unset, absolute `size_x`/`size_y` scale to
  36. Use `row`/`col` for explicit grid placement.
- **`viz`** passes straight through to the Lightdash chart `config` (and wins over
  defaults), so `fieldConfig`, `display`, and other config keys are reachable
  without di0 modelling each one. `native.lightdash` is a lower-precedence escape
  hatch at both the card and dashboard level.
- **`replace: true`** (or `di0 author --replace`) upserts the dashboard by slug
  through the content-as-code surface
  (`POST /api/v1/projects/{uuid}/code/dashboards/{slug}`), keeping the dashboard URL
  stable across rebuilds.

## Capability limits

Lightdash's authoring surface is narrower than Metabase's, so the adapter declares
a restrictive capability descriptor and the core refuses an over-reaching spec
**before anything is created**, naming every gap:

- **Displays**: only `bar`, `line`, `pie`, `table`. A card asking for `scalar`,
  `row`, `funnel`, `combo`, `area`, or `pivot` is refused - SQL charts render no
  such type.
- **Dashboard parameters**: unsupported. Lightdash has no `{{variable}}` SQL
  templating; its dashboard filters are result-column post-filters, a different
  model, so specs with `parameters` are refused.
- **Grid**: 36 columns.
- **Text cards**: supported (markdown / heading tiles).

A spec that stays within these limits authors unchanged; one that exceeds them
fails fast with a `CapabilityError` and writes nothing.
