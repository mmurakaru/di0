"""di0 command-line entry point.

The CLI builds an Engine from the profile via the registry and drives the
validation loop. It is warehouse-agnostic: every concrete choice comes from the
profile passed in with --profile.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from di0.core import Engine
from di0.profile import DEFAULT_PROFILE_NAME, load_profile
from di0.registry import (
    build_dialect_port,
    build_execution_port,
    build_schema_port,
    build_validation_port,
)


def _build_engine(profile_path: str) -> Engine:
    profile = load_profile(profile_path)
    return Engine(
        schema_port=build_schema_port(profile),
        dialect_port=build_dialect_port(profile),
        validation_port=build_validation_port(profile),
        execution_port=build_execution_port(profile),
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="di0", description=__doc__)
    parser.add_argument(
        "--profile",
        default=DEFAULT_PROFILE_NAME,
        help=f"path to the profile (default: {DEFAULT_PROFILE_NAME})",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    validate = sub.add_parser("validate", help="validate SQL (literal or path) against the schema")
    validate.add_argument("sql", help="SQL string or path to a .sql file")
    validate.set_defaults(func=_cmd_validate)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
