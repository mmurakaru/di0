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

from di0 import cliio, core
from di0.core import Engine, ValidationFailed
from di0.deliverable import DashboardSpec
from di0.guard import DEFAULT_PYPROJECT
from di0.profile import DEFAULT_PROFILE_NAME, load_profile
from di0.reconcile import ReconcileSpec
from di0.registry import build_combine_port, build_engine

# Your private content (queries, profiles, specs) lives in a workspace directory,
# gitignored so nothing private is ever committed. Default `./workspace`; override
# with DI0_WORKSPACE. Scaffold it from the committed `examples/` template via `di0 init`.
EXAMPLES_DIR = "examples"

# The verbs that speak the machine-readable contract (init scaffolds, so is exempt).
_CONTRACT_COMMANDS = ("schema", "guard", "validate", "query", "check", "reconcile", "author")


def _workspace() -> Path:
    return Path(os.environ.get("DI0_WORKSPACE", "workspace"))


def _default_profile() -> str:
    return str(_workspace() / DEFAULT_PROFILE_NAME)


def _build_engine(profile_path: str) -> Engine:
    """Load the profile and wire adapters, surfacing failures as a ConfigError."""
    try:
        return build_engine(load_profile(profile_path))
    except (FileNotFoundError, ValueError, OSError) as error:
        raise cliio.ConfigError(str(error)) from error


def _read_sql(value: str) -> str:
    path = Path(value)
    if path.exists():
        return path.read_text()
    return value


def _resolved_schema(engine: Engine) -> dict | None:
    """The resolved schema for did-you-mean suggestions; None if it can't resolve."""
    try:
        return engine.schema_port.resolve()
    except Exception:  # noqa: BLE001 - suggestions are best-effort, never fatal
        return None


def _cmd_validate(args: argparse.Namespace) -> int:
    json_mode = cliio.is_json(args)
    try:
        engine = _build_engine(args.profile)
        result = engine.validate(_read_sql(args.sql))
    except Exception as error:  # noqa: BLE001 - classified centrally
        return cliio.handle_exception("validate", error, json_mode)
    if result.ok:
        if json_mode:
            return cliio.emit_ok("validate", {"valid": True, "errors": []})
        print("OK")
        return 0
    errors = list(result.errors)
    if json_mode:
        failure = cliio.validation_failure(errors, schema=_resolved_schema(engine))
        return cliio.emit_failure("validate", failure, data={"valid": False, "errors": errors})
    for error in errors:
        print(f"INVALID: {error}", file=sys.stderr)
    return cliio.EX_DATAERR


def _cmd_query(args: argparse.Namespace) -> int:
    json_mode = cliio.is_json(args)
    try:
        engine = _build_engine(args.profile)
    except Exception as error:  # noqa: BLE001 - classified centrally
        return cliio.handle_exception("query", error, json_mode)
    try:
        result = engine.query(_read_sql(args.sql))
    except ValidationFailed as failure:
        errors = list(failure.result.errors)
        if json_mode:
            classified = cliio.validation_failure(errors, schema=_resolved_schema(engine))
            return cliio.emit_failure("query", classified)
        for error in errors:
            print(f"INVALID: {error}", file=sys.stderr)
        return cliio.EX_DATAERR
    except Exception as error:  # noqa: BLE001 - a target/adapter runtime failure
        return cliio.handle_exception("query", error, json_mode, default="execution")
    if json_mode:
        data = {"columns": list(result.columns), "rows": [list(row) for row in result.rows]}
        return cliio.emit_ok("query", data)
    if result.columns:
        print("\t".join(result.columns))
    for row in result.rows:
        print("\t".join("" if value is None else str(value) for value in row))
    return 0


def _cmd_guard(args: argparse.Namespace) -> int:
    from di0.guard import driver_dependency_violations, scan_tree

    json_mode = cliio.is_json(args)
    try:
        violations = list(scan_tree(Path(args.path)))
        pyproject = Path(args.pyproject)
        if pyproject.exists():
            violations.extend(driver_dependency_violations(pyproject))
    except Exception as error:  # noqa: BLE001 - classified centrally
        return cliio.handle_exception("guard", error, json_mode)
    data = {
        "violations": [
            {"file": str(v.file), "line": v.line, "literal": v.literal, "reason": v.reason}
            for v in violations
        ]
    }
    if violations:
        if json_mode:
            return cliio.emit_failure("guard", cliio.guard_failure(len(violations)), data=data)
        for violation in violations:
            snippet = violation.literal.splitlines()[0][:60]
            print(
                f"VIOLATION {violation.file}:{violation.line} {violation.reason}: {snippet!r}",
                file=sys.stderr,
            )
        print(f"\n{len(violations)} invariant violation(s)", file=sys.stderr)
        return cliio.EX_DATAERR
    if json_mode:
        return cliio.emit_ok("guard", data)
    print("core holds no warehouse, dialect, or physical reference; no driver dependencies")
    return 0


def _cmd_schema(args: argparse.Namespace) -> int:
    import json

    json_mode = cliio.is_json(args)
    try:
        engine = _build_engine(args.profile)
        schema = engine.schema_port.resolve()
    except Exception as error:  # noqa: BLE001 - classified centrally
        return cliio.handle_exception("schema", error, json_mode)
    if json_mode:
        return cliio.emit_ok("schema", schema)
    print(json.dumps(schema, indent=2, sort_keys=True))
    return 0


def _cmd_author(args: argparse.Namespace) -> int:
    import dataclasses

    json_mode = cliio.is_json(args)
    try:
        engine = _build_engine(args.profile)
        spec_path = Path(args.spec)
        spec = DashboardSpec.from_file(spec_path)
    except Exception as error:  # noqa: BLE001 - engine/spec loading = config phase
        return cliio.handle_exception("author", error, json_mode, default="config")
    if args.replace:
        spec = dataclasses.replace(spec, replace=True)
    try:
        deliverable = engine.author(spec, base_dir=spec_path.parent)
    except ValidationFailed as failure:
        errors = list(failure.result.errors)
        if json_mode:
            classified = cliio.validation_failure(errors, schema=_resolved_schema(engine))
            return cliio.emit_failure("author", classified)
        for error in errors:
            print(f"INVALID: {error}", file=sys.stderr)
        return cliio.EX_DATAERR
    except Exception as error:  # noqa: BLE001 - unsupported capability or target failure
        return cliio.handle_exception("author", error, json_mode, default="execution")
    data = {
        "kind": deliverable.kind,
        "identifier": deliverable.identifier,
        "detail": deliverable.detail,
    }
    if json_mode:
        return cliio.emit_ok("author", data)
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
    json_mode = cliio.is_json(args)
    try:
        spec_path = Path(args.spec)
        spec = ReconcileSpec.from_file(spec_path)
    except Exception as error:  # noqa: BLE001 - spec loading = config phase
        return cliio.handle_exception("reconcile", error, json_mode, default="config")
    try:
        result = core.reconcile(spec, spec_path.parent, build_engine, build_combine_port())
    except (ValueError, ValidationFailed) as error:
        # An unknown source / unresolved dependency / query that fails validation:
        # the spec references something the data can't satisfy - a data error.
        message = (
            "; ".join(error.result.errors)
            if isinstance(error, ValidationFailed)
            else str(error)
        )
        failure = cliio.reference_failure(message)
        if json_mode:
            return cliio.emit_failure("reconcile", failure)
        print(f"ERROR: {message}", file=sys.stderr)
        return failure.exit_code
    except Exception as error:  # noqa: BLE001 - a source/adapter runtime failure
        return cliio.handle_exception("reconcile", error, json_mode, default="execution")
    if json_mode:
        data = {"columns": list(result.columns), "rows": [list(row) for row in result.rows]}
        return cliio.emit_ok("reconcile", data)
    if result.columns:
        print("\t".join(result.columns))
    for row in result.rows:
        print("\t".join("" if value is None else str(value) for value in row))
    return 0


def _cmd_check(args: argparse.Namespace) -> int:
    json_mode = cliio.is_json(args)
    try:
        engine = _build_engine(args.profile)
    except Exception as error:  # noqa: BLE001 - classified centrally
        return cliio.handle_exception("check", error, json_mode)
    # `_*.sql` and `combine.sql` run against the local combine stage, not a source.
    paths = sorted(
        path
        for path in Path(args.queries).glob("**/*.sql")
        if not path.name.startswith("_") and path.stem != "combine"
    )
    if not paths:
        if json_mode:
            return cliio.emit_ok("check", {"files": [], "ok_count": 0, "fail_count": 0})
        print(f"no .sql files found under {args.queries}")
        return 0
    results = engine.validate_paths(paths)
    failed = sum(1 for _, result in results if not result.ok)
    if json_mode:
        data = {
            "files": [
                {"path": str(path), "valid": result.ok, "errors": list(result.errors)}
                for path, result in results
            ],
            "ok_count": len(results) - failed,
            "fail_count": failed,
        }
        if failed:
            return cliio.emit_failure("check", cliio.check_failure(failed), data=data)
        return cliio.emit_ok("check", data)
    for path, result in results:
        if result.ok:
            print(f"OK    {path}")
        else:
            print(f"DRIFT {path}: {'; '.join(result.errors)}", file=sys.stderr)
    print(f"\n{len(results) - failed}/{len(results)} queries valid")
    return cliio.EX_DATAERR if failed else 0


def _format_parent() -> argparse.ArgumentParser:
    """The shared `--format {text,json}` / `--json` options, added to every verb."""
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="output format: text (human, default) or json (machine-readable envelope)",
    )
    parent.add_argument(
        "--json", action="store_true", help="shorthand for --format json"
    )
    return parent


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="di0", description=__doc__)
    parser.add_argument(
        "--profile",
        default=_default_profile(),
        help=f"path to the profile (default: {_default_profile()})",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    fmt = _format_parent()

    init = sub.add_parser("init", help="scaffold a gitignored workspace/ from examples/")
    init.add_argument("--template", default=EXAMPLES_DIR, help="template dir to copy")
    init.set_defaults(func=_cmd_init)

    schema = sub.add_parser("schema", parents=[fmt], help="resolve and print the schema as JSON")
    schema.set_defaults(func=_cmd_schema)

    guard = sub.add_parser(
        "guard",
        parents=[fmt],
        help="fail if the core names a warehouse/dialect/table or declares a driver",
    )
    guard.add_argument("--path", default="src/di0", help="core package to scan")
    guard.add_argument(
        "--pyproject", default=DEFAULT_PYPROJECT, help="project metadata scanned for driver deps"
    )
    guard.set_defaults(func=_cmd_guard)

    validate = sub.add_parser(
        "validate", parents=[fmt], help="validate SQL (literal or path) against the schema"
    )
    validate.add_argument("sql", help="SQL string or path to a .sql file")
    validate.set_defaults(func=_cmd_validate)

    query = sub.add_parser("query", parents=[fmt], help="validate then execute SQL, printing rows")
    query.add_argument("sql", help="SQL string or path to a .sql file")
    query.set_defaults(func=_cmd_query)

    check = sub.add_parser(
        "check", parents=[fmt], help="validate every .sql file against the schema (CI gate)"
    )
    check.add_argument(
        "--queries",
        default=str(_workspace() / "queries"),
        help="directory scanned recursively for .sql files (skips _*.sql and combine.sql)",
    )
    check.set_defaults(func=_cmd_check)

    reconcile = sub.add_parser(
        "reconcile", parents=[fmt], help="run a cross-source reconcile spec, printing rows"
    )
    reconcile.add_argument("spec", help="path to a reconcile spec (.yml)")
    reconcile.set_defaults(func=_cmd_reconcile)

    author = sub.add_parser(
        "author", parents=[fmt], help="author a dashboard from a deliverable spec"
    )
    author.add_argument("spec", help="path to a dashboard spec (.yml)")
    author.add_argument(
        "--replace",
        action="store_true",
        help="archive an existing same-name dashboard in the collection first",
    )
    author.set_defaults(func=_cmd_author)

    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exit_signal:
        # argparse prints usage to stderr then exits; --help exits cleanly (0/None),
        # a bad invocation exits non-zero. Remap the latter to EX_USAGE, and in json
        # mode still deliver the error as an envelope on stdout.
        if exit_signal.code in (0, None):
            return cliio.EX_OK
        if cliio.argv_wants_json(argv):
            command = next((token for token in argv if token in _CONTRACT_COMMANDS), "di0")
            return cliio.emit_failure(command, cliio.usage_failure("invalid or missing arguments"))
        return cliio.EX_USAGE
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
