"""di0 command-line entry point.

The CLI builds an Engine from the profile via the registry and drives the
validation loop. It is warehouse-agnostic: every concrete choice comes from the
profile passed in with --profile.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

from di0 import core
from di0.core import AuthoringUnsupported, Engine, ValidationFailed
from di0.deliverable import DashboardSpec
from di0.profile import DEFAULT_PROFILE_NAME, load_profile
from di0.reconcile import ReconcileSpec
from di0.registry import build_combine_port, build_engine

# Your private content (queries, profiles, specs) lives in a workspace directory,
# gitignored so nothing private is ever committed. Default `./workspace`; override
# with DI0_WORKSPACE. Scaffold it from the committed `examples/` template via `di0 init`.
EXAMPLES_DIR = "examples"


def _workspace() -> Path:
    return Path(os.environ.get("DI0_WORKSPACE", "workspace"))


def _default_profile() -> str:
    return str(_workspace() / DEFAULT_PROFILE_NAME)


def _build_engine(profile_path: str) -> Engine:
    return build_engine(load_profile(profile_path))


def _read_sql(value: str) -> str:
    path = Path(value)
    if path.exists():
        return path.read_text()
    return value


def _cmd_validate(args: argparse.Namespace) -> int:
    engine = _build_engine(args.profile)
    result = engine.validate(_read_sql(args.sql))
    if result.ok:
        print("OK")
        return 0
    for error in result.errors:
        print(f"INVALID: {error}", file=sys.stderr)
    return 1


def _cmd_query(args: argparse.Namespace) -> int:
    engine = _build_engine(args.profile)
    try:
        result = engine.query(_read_sql(args.sql))
    except ValidationFailed as failure:
        for error in failure.result.errors:
            print(f"INVALID: {error}", file=sys.stderr)
        return 1
    if result.columns:
        print("\t".join(result.columns))
    for row in result.rows:
        print("\t".join("" if value is None else str(value) for value in row))
    return 0


def _cmd_guard(args: argparse.Namespace) -> int:
    from di0.guard import scan_tree

    violations = scan_tree(Path(args.path))
    for violation in violations:
        snippet = violation.literal.splitlines()[0][:60]
        print(
            f"VIOLATION {violation.file}:{violation.line} {violation.reason}: {snippet!r}",
            file=sys.stderr,
        )
    if violations:
        print(f"\n{len(violations)} invariant violation(s)", file=sys.stderr)
        return 1
    print("core holds no warehouse, dialect, or physical reference")
    return 0


def _cmd_schema(args: argparse.Namespace) -> int:
    import json

    engine = _build_engine(args.profile)
    print(json.dumps(engine.schema_port.resolve(), indent=2, sort_keys=True))
    return 0


def _cmd_author(args: argparse.Namespace) -> int:
    import dataclasses

    engine = _build_engine(args.profile)
    spec_path = Path(args.spec)
    spec = DashboardSpec.from_file(spec_path)
    if args.replace:
        spec = dataclasses.replace(spec, replace=True)
    try:
        deliverable = engine.author(spec, base_dir=spec_path.parent)
    except ValidationFailed as failure:
        for error in failure.result.errors:
            print(f"INVALID: {error}", file=sys.stderr)
        return 1
    except AuthoringUnsupported as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    print(f"Authored {deliverable.kind} {deliverable.identifier}: {deliverable.detail['url']}")
    return 0


def _cmd_init(args: argparse.Namespace) -> int:
    workspace = _workspace()
    template = Path(args.template)
    if template.is_dir():
        shutil.copytree(template, workspace, dirs_exist_ok=True)
        made = f"scaffolded {workspace}/ from {template}/"
    else:
        for sub in ("queries", "context"):
            (workspace / sub).mkdir(parents=True, exist_ok=True)
        made = f"created empty {workspace}/ (no {template}/ template found)"
    # Only gitignore an in-repo workspace; an external (absolute) one needs no entry.
    gitignore = Path(".gitignore")
    entry = f"/{workspace}/"
    if not workspace.is_absolute() and gitignore.exists() and entry not in gitignore.read_text():
        with gitignore.open("a") as handle:
            handle.write(f"\n{entry}\n")
    print(f"{made}. Drop your queries/profiles/specs there; it is gitignored.")
    return 0


def _cmd_reconcile(args: argparse.Namespace) -> int:
    spec_path = Path(args.spec)
    spec = ReconcileSpec.from_file(spec_path)
    result = core.reconcile(spec, spec_path.parent, build_engine, build_combine_port())
    if result.columns:
        print("\t".join(result.columns))
    for row in result.rows:
        print("\t".join("" if value is None else str(value) for value in row))
    return 0


def _cmd_check(args: argparse.Namespace) -> int:
    engine = _build_engine(args.profile)
    # `_*.sql` and `combine.sql` run against the local combine stage, not a source.
    paths = sorted(
        path
        for path in Path(args.queries).glob("**/*.sql")
        if not path.name.startswith("_") and path.stem != "combine"
    )
    if not paths:
        print(f"no .sql files found under {args.queries}")
        return 0
    results = engine.validate_paths(paths)
    failed = 0
    for path, result in results:
        if result.ok:
            print(f"OK    {path}")
        else:
            failed += 1
            print(f"DRIFT {path}: {'; '.join(result.errors)}", file=sys.stderr)
    print(f"\n{len(results) - failed}/{len(results)} queries valid")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="di0", description=__doc__)
    parser.add_argument(
        "--profile",
        default=_default_profile(),
        help=f"path to the profile (default: {_default_profile()})",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="scaffold a gitignored workspace/ from examples/")
    init.add_argument("--template", default=EXAMPLES_DIR, help="template dir to copy")
    init.set_defaults(func=_cmd_init)

    schema = sub.add_parser("schema", help="resolve and print the schema as JSON")
    schema.set_defaults(func=_cmd_schema)

    guard = sub.add_parser("guard", help="fail if the core names a warehouse/dialect/table")
    guard.add_argument("--path", default="src/di0", help="core package to scan")
    guard.set_defaults(func=_cmd_guard)

    validate = sub.add_parser("validate", help="validate SQL (literal or path) against the schema")
    validate.add_argument("sql", help="SQL string or path to a .sql file")
    validate.set_defaults(func=_cmd_validate)

    query = sub.add_parser("query", help="validate then execute SQL, printing rows")
    query.add_argument("sql", help="SQL string or path to a .sql file")
    query.set_defaults(func=_cmd_query)

    check = sub.add_parser("check", help="validate every .sql file against the schema (CI gate)")
    check.add_argument(
        "--queries",
        default=str(_workspace() / "queries"),
        help="directory scanned recursively for .sql files (skips _*.sql and combine.sql)",
    )
    check.set_defaults(func=_cmd_check)

    reconcile = sub.add_parser("reconcile", help="run a cross-source reconcile spec, printing rows")
    reconcile.add_argument("spec", help="path to a reconcile spec (.yml)")
    reconcile.set_defaults(func=_cmd_reconcile)

    author = sub.add_parser("author", help="author a dashboard from a deliverable spec")
    author.add_argument("spec", help="path to a dashboard spec (.yml)")
    author.add_argument(
        "--replace",
        action="store_true",
        help="archive an existing same-name dashboard in the collection first",
    )
    author.set_defaults(func=_cmd_author)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
