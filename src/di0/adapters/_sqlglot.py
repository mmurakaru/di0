"""Shared sqlglot helpers for the dialect and validation adapters.

Some target dialects are wire-compatible with a dialect sqlglot already models
(e.g. CockroachDB speaks the Postgres wire protocol). We map those to the
sqlglot dialect that parses them, keeping the alias in one place.
"""

from __future__ import annotations

_DIALECT_ALIASES = {
    "cockroachdb": "postgres",
    "cockroach": "postgres",
}


def to_sqlglot_dialect(name: str) -> str:
    return _DIALECT_ALIASES.get(name, name)
