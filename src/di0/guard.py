"""The invariant guard: the core must name no warehouse, dialect, or physical ref.

> If a physical table name, column name, dialect, or warehouse appears as a string
> literal in the core, it is a bug.

This scans string literals (including docstrings) in the core Python modules and
flags any concrete warehouse/BI/dialect name, or a bare `schema.table` reference.
The composition edge (`registry.py`), the adapter modules, and this guard itself
legitimately name adapters and are excluded.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

# Concrete warehouses, BI tools, and SQL dialects - never in the core.
_DENYLIST = (
    "snowflake",
    "metabase",
    "postgres",
    "postgresql",
    "cockroach",
    "cockroachdb",
    "bigquery",
    "redshift",
    "databricks",
    "mysql",
    "sqlite",
    "oracle",
    "duckdb",
    "clickhouse",
    "trino",
    "presto",
    "looker",
    "superset",
    "tableau",
    "drizzle",
    "strapi",
)
_DENY_RE = re.compile(r"\b(" + "|".join(_DENYLIST) + r")\b", re.IGNORECASE)

# A bare physical reference: exactly `identifier.identifier` (one dot, snake_case).
_PHYSICAL_REF_RE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")

_EXCLUDED_NAMES = {"registry.py", "guard.py"}


@dataclass(frozen=True)
class Violation:
    file: Path
    line: int
    literal: str
    reason: str


def _is_excluded(path: Path) -> bool:
    return "adapters" in path.parts or path.name in _EXCLUDED_NAMES


def _scan_file(path: Path) -> list[Violation]:
    violations: list[Violation] = []
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        literal = node.value
        match = _DENY_RE.search(literal)
        if match:
            violations.append(
                Violation(path, node.lineno, literal, f"names '{match.group(1).lower()}'")
            )
        elif _PHYSICAL_REF_RE.match(literal.strip()):
            reason = "looks like a physical schema.table reference"
            violations.append(Violation(path, node.lineno, literal, reason))
    return violations


def scan_tree(root: Path) -> list[Violation]:
    violations: list[Violation] = []
    for path in sorted(root.glob("**/*.py")):
        if _is_excluded(path):
            continue
        violations.extend(_scan_file(path))
    return violations
