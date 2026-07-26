"""The invariant guard: the core names no warehouse/dialect/ref and ships no driver.

> If a physical table name, column name, dialect, or warehouse appears as a string
> literal in the core, it is a bug. So is a data-store driver in the dependencies.

`scan_tree` reads string literals (including docstrings) in the core Python modules
and flags any concrete warehouse/BI/dialect name, or a bare `schema.table`
reference. `driver_dependency_violations` reads pyproject.toml and flags any
declared dependency that is a warehouse/DB client driver: credentials and drivers
belong on the far side of a port, never in the package. The composition edge
(`registry.py`), the adapter modules, and this guard itself legitimately name
adapters and are excluded from the literal scan.
"""

from __future__ import annotations

import ast
import re
import tomllib
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

# Genuine warehouse/DB client drivers. Execution goes through systems that already
# front the warehouse, so the package needs none of these. `duckdb` is deliberately
# absent: it is an in-process engine the combine port uses for LOCAL joins, not a
# driver to a remote store. `sqlglot`/`pyyaml` are parser/config deps, not drivers.
_DRIVER_DENYLIST = (
    "psycopg",
    "psycopg2",
    "psycopg2-binary",
    "asyncpg",
    "snowflake-connector-python",
    "snowflake-sqlalchemy",
    "mysqlclient",
    "PyMySQL",
    "cx_Oracle",
    "oracledb",
    "pyodbc",
    "redshift-connector",
    "databricks-sql-connector",
    "clickhouse-driver",
    "clickhouse-connect",
    "google-cloud-bigquery",
    "trino",
    "presto-python-client",
    "pymssql",
)

# Defined here, where the scan never reaches, so the CLI can name the file without
# a `pyproject.toml` literal in scanned code tripping the physical-reference check.
DEFAULT_PYPROJECT = "pyproject.toml"

# The leading name of a PEP 508 requirement, before any extras or version specifier.
_REQUIREMENT_NAME_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def _normalize_distribution_name(name: str) -> str:
    """PEP 503 normalization so extras/case/separators compare equal."""
    return re.sub(r"[-_.]+", "-", name).strip().lower()


_DRIVER_DENYSET = frozenset(_normalize_distribution_name(name) for name in _DRIVER_DENYLIST)


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


def _requirement_name(specifier: str) -> str:
    match = _REQUIREMENT_NAME_RE.match(specifier)
    return match.group(1) if match else ""


def _declared_requirements(pyproject: dict) -> list[str]:
    """Every requirement string declared anywhere in pyproject.toml."""
    requirements: list[str] = []
    project = pyproject.get("project", {})
    requirements.extend(project.get("dependencies", []))
    for extra in project.get("optional-dependencies", {}).values():
        requirements.extend(extra)
    for group in pyproject.get("dependency-groups", {}).values():
        # A group entry is either a requirement string or an {include-group: ...} table.
        requirements.extend(entry for entry in group if isinstance(entry, str))
    return requirements


def driver_dependency_violations(pyproject_path: Path) -> list[Violation]:
    """Flag any declared dependency that is a warehouse/DB client driver."""
    pyproject_path = Path(pyproject_path)
    text = pyproject_path.read_text()
    lines = text.splitlines()
    pyproject = tomllib.loads(text)
    violations: list[Violation] = []
    for specifier in _declared_requirements(pyproject):
        name = _requirement_name(specifier)
        if _normalize_distribution_name(name) not in _DRIVER_DENYSET:
            continue
        line = next((n for n, raw in enumerate(lines, start=1) if specifier in raw), 0)
        reason = f"declares database driver '{name}'"
        violations.append(Violation(pyproject_path, line, specifier, reason))
    return violations
