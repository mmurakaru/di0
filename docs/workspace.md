# Workspace - your private content

di0 ships the tool; your queries, profiles, deliverable specs, and agent-context
live in a **workspace** directory that is **gitignored**, so nothing private is
ever committed.

- `di0 init` scaffolds `workspace/` from the committed [`examples/`](../examples/) template
  (idempotent) and gitignores it.
- Default path is `./workspace`; override with `DI0_WORKSPACE=/path` to point at a
  private directory or a separate private repo.
- di0 resolves the profile from `<workspace>/di0.profile.yml`.
- Credentials go through the environment (`DI0_METABASE_SESSION=...`), never
  through files di0 reads.

## One primitive: the deliverable bundle

A deliverable is a directory containing a `spec.yml`. Everything the deliverable
needs lives next to its spec, so a bundle is self-contained - move, rebuild, or
retire it as a unit. `di0 author` already resolves a spec's `query:` paths
relative to the spec file, so bundle-local references stay short.

```
workspace/
  di0.profile.yml     # your profile(s) - warehouse, dialect, targets
  queries/            # ad-hoc .sql not tied to any deliverable
  context/            # agent context - notes, schema snapshots, reference extracts
  <deliverable>/      # one directory per deliverable
    spec.yml          #   the dashboard spec (this file marks the bundle)
    *.sql             #   the queries the spec or its reconcile fetches
    combine.sql       #   optional - cross-source combine stage (di0 reconcile)
    build.py          #   optional - build script where the spec alone isn't enough
```

Only `spec.yml` carries meaning; organize the rest of a bundle however it reads
best. Three conventions the tooling respects:

- `di0 check` scans `<workspace>/queries` by default; check a bundle explicitly
  with `di0 check --queries <bundle>` (and the bundle's own profile if it has
  one). A cross-source bundle can't be validated against a single profile - its
  source queries are validated per-source when the reconcile runs.
- `_*.sql` and `combine.sql` run against the **local combine stage** (DuckDB),
  not a source, so `di0 check` skips them.
- Superseding a dashboard is `replace: true` in its spec (same bundle, updated in
  place, stable URL). A retired bundle is deleted; keep the workspace in a
  private repo if you want history.

Keeping your content here is how you build on di0 without forking the tool or
leaking anything into the public repo - the pattern is baked in, the content is yours.
