"""di0 command-line entry point.

The CLI builds an Engine from the profile via the registry and drives the
validation loop. It is warehouse-agnostic: every concrete choice comes from the
profile passed in with --profile.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from di0.core import AuthoringUnsupported, Engine, ValidationFailed
from di0.deliverable import DashboardSpec
from di0.profile import DEFAULT_PROFILE_NAME, load_profile
from di0.registry import (
    build_dialect_port,
    build_execution_port,
    build_schema_port,
    build_validation_port,
)


def _build_engine(profile_path: str) -> Engine:
    profile = load_profile(profile_path)
    execution_port = build_execution_port(profile)
    return Engine(
        schema_port=build_schema_port(profile),
        dialect_port=build_dialect_port(profile),
        validation_port=build_validation_port(profile, execution_port),
        execution_port=execution_port,
    )


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


def _cmd_schema(args: argparse.Namespace) -> int:
    import json

    engine = _build_engine(args.profile)
    print(json.dumps(engine.schema_port.resolve(), indent=2, sort_keys=True))
    return 0


def _cmd_author(args: argparse.Namespace) -> int:
    engine = _build_engine(args.profile)
    spec_path = Path(args.spec)
    spec = DashboardSpec.from_file(spec_path)
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


def _cmd_check(args: argparse.Namespace) -> int:
    engine = _build_engine(args.profile)
    paths = sorted(Path(args.queries).glob("**/*.sql"))
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
        default=DEFAULT_PROFILE_NAME,
        help=f"path to the profile (default: {DEFAULT_PROFILE_NAME})",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    schema = sub.add_parser("schema", help="resolve and print the schema as JSON")
    schema.set_defaults(func=_cmd_schema)

    validate = sub.add_parser("validate", help="validate SQL (literal or path) against the schema")
    validate.add_argument("sql", help="SQL string or path to a .sql file")
    validate.set_defaults(func=_cmd_validate)

    query = sub.add_parser("query", help="validate then execute SQL, printing rows")
    query.add_argument("sql", help="SQL string or path to a .sql file")
    query.set_defaults(func=_cmd_query)

    check = sub.add_parser("check", help="validate every .sql file against the schema (CI gate)")
    check.add_argument("--queries", default="queries", help="directory of .sql files")
    check.set_defaults(func=_cmd_check)

    author = sub.add_parser("author", help="author a dashboard from a deliverable spec")
    author.add_argument("spec", help="path to a dashboard spec (.yml)")
    author.set_defaults(func=_cmd_author)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
