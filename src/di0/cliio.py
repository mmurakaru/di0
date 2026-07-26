"""The machine-readable output contract for the di0 CLI.

Every verb can emit one JSON envelope so an agent harness parses results without
scraping prose. This module owns the envelope, the structured error objects, the
did-you-mean suggester, and both mappings a caller needs - failure class to a
BSD-sysexits exit code (applied in text *and* json modes) and failure class to an
HTTP-style code carried in the error object. cli.py stays thin and imports from
here.
"""

from __future__ import annotations

import difflib
import json
import re
import sys
from dataclasses import dataclass
from typing import Any

from di0.core import AuthoringUnsupported, ValidationFailed
from di0.ports import Schema

# Bump on any change an agent could parse against: envelope keys, error shape,
# per-verb data payloads, or the exit-code contract.
CONTRACT_VERSION = "0.1.0"

# BSD sysexits (sysexits.h), applied in both text and json modes.
EX_OK = 0
EX_USAGE = 64  # argparse / bad arguments
EX_DATAERR = 65  # validation failure, unknown reference, guard violation
EX_UNAVAILABLE = 69  # execution / adapter / target runtime error, unsupported capability
EX_SOFTWARE = 70  # unexpected internal exception (a bug in di0)
EX_CONFIG = 78  # profile / config load error

# HTTP-style codes carried in the error object.
HTTP_BAD_REQUEST = 400
HTTP_NOT_FOUND = 404
HTTP_UNPROCESSABLE = 422
HTTP_INTERNAL = 500
HTTP_NOT_IMPLEMENTED = 501
HTTP_BAD_GATEWAY = 502


class ConfigError(Exception):
    """A profile or configuration failed to load or wire up to adapters."""


class ExecutionError(Exception):
    """An execution adapter or target failed at runtime (network, backend, ...)."""


@dataclass(frozen=True)
class Failure:
    """A classified failure: the sysexit exit code plus the error object."""

    exit_code: int
    error: dict


def error_object(
    code: int,
    message: str,
    suggestions: tuple[str, ...] | list[str] = (),
    detail: dict | None = None,
) -> dict:
    return {
        "code": code,
        "message": message,
        "suggestions": list(suggestions),
        "detail": detail,
    }


# --- failure-class builders (the class -> exit-code / http-code mapping) -----


def usage_failure(message: str, detail: dict | None = None) -> Failure:
    return Failure(EX_USAGE, error_object(HTTP_BAD_REQUEST, message, (), detail))


def validation_failure(
    errors: list[str], schema: Schema | None = None, detail: dict | None = None
) -> Failure:
    message = "; ".join(errors) or "validation failed"
    suggestions = suggestions_for(errors, schema) if schema is not None else []
    detail = {"errors": list(errors)} if detail is None else detail
    return Failure(EX_DATAERR, error_object(HTTP_UNPROCESSABLE, message, suggestions, detail))


def reference_failure(message: str, detail: dict | None = None) -> Failure:
    """An unknown reference (e.g. a reconcile query naming an unknown source)."""
    return Failure(EX_DATAERR, error_object(HTTP_UNPROCESSABLE, message, (), detail))


def guard_failure(count: int) -> Failure:
    return Failure(
        EX_DATAERR,
        error_object(HTTP_UNPROCESSABLE, f"{count} invariant violation(s)", (), {"count": count}),
    )


def check_failure(fail_count: int) -> Failure:
    return Failure(
        EX_DATAERR,
        error_object(
            HTTP_UNPROCESSABLE,
            f"{fail_count} query file(s) failed validation",
            (),
            {"fail_count": fail_count},
        ),
    )


def unsupported_failure(message: str) -> Failure:
    return Failure(EX_UNAVAILABLE, error_object(HTTP_NOT_IMPLEMENTED, message, (), None))


def execution_failure(message: str) -> Failure:
    return Failure(EX_UNAVAILABLE, error_object(HTTP_BAD_GATEWAY, message, (), None))


def config_failure(message: str, not_found: bool = False) -> Failure:
    code = HTTP_NOT_FOUND if not_found else HTTP_BAD_REQUEST
    return Failure(EX_CONFIG, error_object(code, message, (), None))


def internal_failure(exc: BaseException) -> Failure:
    message = str(exc) or exc.__class__.__name__
    detail = {"type": exc.__class__.__name__}
    return Failure(EX_SOFTWARE, error_object(HTTP_INTERNAL, message, (), detail))


def classify(exc: BaseException, default: str = "internal") -> Failure:
    """Map a caught exception to its failure class.

    Known types map directly; anything else falls to `default`, which a caller
    sets to the class an unexpected error in that phase most likely belongs to
    ("execution" once a target is being driven, "config" while loading input).
    """
    if isinstance(exc, ValidationFailed):
        return validation_failure(list(exc.result.errors))
    if isinstance(exc, AuthoringUnsupported):
        return unsupported_failure(str(exc))
    if isinstance(exc, ConfigError):
        return config_failure(str(exc), not_found=isinstance(exc.__cause__, FileNotFoundError))
    if isinstance(exc, ExecutionError):
        return execution_failure(str(exc))
    if isinstance(exc, FileNotFoundError):
        return config_failure(str(exc), not_found=True)
    if default == "execution":
        return execution_failure(str(exc) or exc.__class__.__name__)
    if default == "config":
        return config_failure(str(exc) or exc.__class__.__name__)
    return internal_failure(exc)


# --- did-you-mean suggestions (best-effort) ----------------------------------

# Validators quote the offending identifier, e.g. "Column 'CURRNT_ARR' could not
# be resolved." - pull those quoted tokens back out to match against the schema.
_QUOTED_IDENTIFIER_RE = re.compile(r"'([^']+)'")


def known_identifiers(schema: Schema | None) -> list[str]:
    """Every namespace, table, and column name in the resolved schema."""
    names: set[str] = set()
    for namespace, tables in (schema or {}).items():
        names.add(namespace)
        for table, columns in (tables or {}).items():
            names.add(table)
            names.update(columns or {})
    return sorted(names)


def suggestions_for(errors: list[str], schema: Schema | None) -> list[str]:
    """Close schema identifiers for the unknown names an error message quotes.

    Case-insensitive (some warehouses upper-case identifiers). Returns [] when
    the schema is unavailable or nothing is close enough - never raises.
    """
    known = known_identifiers(schema)
    if not known:
        return []
    lower_to_original: dict[str, str] = {}
    for name in known:
        lower_to_original.setdefault(name.lower(), name)
    candidates = list(lower_to_original)
    seen: set[str] = set()
    out: list[str] = []
    for message in errors:
        for token in _QUOTED_IDENTIFIER_RE.findall(message):
            for match in difflib.get_close_matches(token.lower(), candidates, n=3, cutoff=0.6):
                original = lower_to_original[match]
                if original not in seen:
                    seen.add(original)
                    out.append(original)
    return out


# --- envelope emission -------------------------------------------------------


def is_json(args: Any) -> bool:
    """True when the parsed args requested json (`--json` or `--format json`)."""
    return bool(getattr(args, "json", False)) or getattr(args, "format", "text") == "json"


def argv_wants_json(argv: list[str]) -> bool:
    """Detect json from raw argv, for failures raised before args are parsed."""
    if "--json" in argv or "--format=json" in argv:
        return True
    return any(
        token == "--format" and index + 1 < len(argv) and argv[index + 1] == "json"
        for index, token in enumerate(argv)
    )


def _emit(command: str, *, ok: bool, data: Any, error: dict | None, warnings: list[str]) -> None:
    payload = {
        "contract_version": CONTRACT_VERSION,
        "command": command,
        "ok": ok,
        "data": data,
        "error": error,
        "warnings": warnings,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))


def emit_ok(command: str, data: Any, warnings: tuple[str, ...] | list[str] = ()) -> int:
    """Emit a success envelope to stdout; return EX_OK. (json mode only)"""
    _emit(command, ok=True, data=data, error=None, warnings=list(warnings))
    return EX_OK


def emit_failure(
    command: str,
    failure: Failure,
    data: Any = None,
    warnings: tuple[str, ...] | list[str] = (),
) -> int:
    """Emit a failure envelope to stdout; return its exit code. (json mode only)"""
    _emit(command, ok=False, data=data, error=failure.error, warnings=list(warnings))
    return failure.exit_code


def handle_exception(
    command: str, exc: BaseException, json_mode: bool, *, default: str = "internal"
) -> int:
    """Classify an unexpected exception, render per mode, return its exit code.

    In json mode the error rides in the envelope on stdout; in text mode a human
    message goes to stderr, matching the CLI's existing `ERROR: ...` convention.
    """
    failure = classify(exc, default=default)
    if json_mode:
        emit_failure(command, failure)
    else:
        print(f"ERROR: {failure.error['message']}", file=sys.stderr)
    return failure.exit_code
