# Workspace - your private content

di0 ships the tool; your queries, profiles, deliverable/reconcile specs, and
agent-context live in a **workspace** directory that is **gitignored**, so nothing
private is ever committed.

- `di0 init` scaffolds `workspace/` from the committed [`examples/`](../examples/) template
  (idempotent) and gitignores it.
- Default path is `./workspace`; override with `DI0_WORKSPACE=/path` to point at a
  private directory or a separate private repo.
- di0 resolves the profile from `<workspace>/di0.profile.yml` and `di0 check` scans
  `<workspace>/queries` by default.

## Layout (mirrors `examples/`)

```
workspace/
  di0.profile.yml     # your profile(s)
  queries/            # your .sql
  deliverables/       # dashboard specs (.yml)
  reconcile/          # reconcile specs + combine.sql
  context/            # agent-context notes
```

Keeping your content here is how you build on di0 without forking the tool or
leaking anything into the public repo - the pattern is baked in, the content is yours.
