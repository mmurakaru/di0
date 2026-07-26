"""Slice #9: the invariant guard catches hard-coded references in the core.

The clean core passes. A planted warehouse name or a bare `schema.table` literal
is caught. Adapter modules and the composition edge are excluded, which is what
lets the clean scan pass even though adapters legitimately name warehouses.

The guard also enforces the other half of the invariant: the package declares no
database-driver dependency. A driver added to pyproject.toml is caught; the
in-process combine engine (duckdb) and the parser/config deps are not flagged.
"""

from __future__ import annotations

from pathlib import Path

from di0 import cli
from di0.guard import driver_dependency_violations, scan_tree

CORE = Path(__file__).parent.parent / "src" / "di0"
PYPROJECT = Path(__file__).parent.parent / "pyproject.toml"


def test_clean_core_passes():
    assert scan_tree(CORE) == []


def test_adapters_are_excluded():
    # An adapter module names its warehouse (e.g. metabase); the clean scan above
    # only passes because adapters/ is excluded. Assert the exclusion explicitly.
    metabase = CORE / "adapters" / "metabase_execution.py"
    assert metabase.exists()
    assert all("adapters" not in v.file.parts for v in scan_tree(CORE))


def test_planted_warehouse_name_caught(tmp_path):
    (tmp_path / "leak.py").write_text('CONNECTION = "snowflake://prod"\n')
    violations = scan_tree(tmp_path)
    assert len(violations) == 1
    assert "snowflake" in violations[0].reason


def test_planted_physical_reference_caught(tmp_path):
    (tmp_path / "leak.py").write_text('TABLE = "analytics.dim_customers"\n')
    violations = scan_tree(tmp_path)
    assert len(violations) == 1
    assert "physical" in violations[0].reason


def test_filename_literal_is_not_flagged(tmp_path):
    # `di0.profile.yml`-style names have two dots and must not trip the ref check.
    (tmp_path / "ok.py").write_text('NAME = "di0.profile.yml"\nGLOB = "**/*.sql"\n')
    assert scan_tree(tmp_path) == []


def test_real_pyproject_declares_no_driver():
    assert driver_dependency_violations(PYPROJECT) == []


def test_planted_driver_dependency_caught(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\n'
        'name = "leak"\n'
        'dependencies = [\n'
        '    "sqlglot>=30",\n'
        '    "psycopg2-binary>=2.9",\n'
        ']\n'
    )
    violations = driver_dependency_violations(pyproject)
    assert len(violations) == 1
    assert "psycopg2-binary" in violations[0].reason
    assert violations[0].line == 5


def test_duckdb_and_parser_deps_not_flagged(tmp_path):
    # duckdb is the in-process combine engine (LOCAL joins), explicitly allowed;
    # sqlglot and pyyaml are the parser/config deps and must never trip the check.
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\n'
        'name = "ok"\n'
        'dependencies = [\n'
        '    "sqlglot>=30",\n'
        '    "pyyaml>=6",\n'
        '    "duckdb>=1.5",\n'
        ']\n'
    )
    assert driver_dependency_violations(pyproject) == []


def test_driver_matched_case_insensitively_ignoring_extras_and_version(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\n'
        'name = "leak"\n'
        'dependencies = [\n'
        '    "PyMySQL==1.1",\n'
        '    "cx_Oracle[thick]>=8",\n'
        ']\n'
    )
    reasons = " ".join(v.reason for v in driver_dependency_violations(pyproject))
    assert len(driver_dependency_violations(pyproject)) == 2
    assert "PyMySQL" in reasons
    assert "cx_Oracle" in reasons


def test_driver_in_optional_and_group_dependencies_caught(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\n'
        'name = "leak"\n'
        'dependencies = ["sqlglot>=30"]\n'
        '\n'
        '[project.optional-dependencies]\n'
        'warehouse = ["snowflake-connector-python>=3"]\n'
        '\n'
        '[dependency-groups]\n'
        'dev = ["pytest>=9", "asyncpg>=0.29"]\n'
    )
    names = {v.literal for v in driver_dependency_violations(pyproject)}
    assert names == {"snowflake-connector-python>=3", "asyncpg>=0.29"}


def test_guard_command_fails_when_a_driver_is_declared(tmp_path, capsys):
    # The clean core scan passes, but the planted driver dependency must still
    # drive the exit code non-zero and name the offender.
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\n'
        'name = "leak"\n'
        'dependencies = ["psycopg[binary]>=3"]\n'
    )
    exit_code = cli.main(["guard", "--path", str(CORE), "--pyproject", str(pyproject)])
    captured = capsys.readouterr()
    assert exit_code == cli.cliio.EX_DATAERR  # guard violation -> EX_DATAERR (was 1)
    assert "psycopg" in captured.err


def test_guard_command_passes_on_the_real_project(capsys):
    exit_code = cli.main(["guard", "--path", str(CORE), "--pyproject", str(PYPROJECT)])
    assert exit_code == 0
