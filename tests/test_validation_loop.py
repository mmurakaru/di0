"""End-to-end test of the offline validation loop on the sample manifest.

Good SQL over known columns passes; SQL referencing a non-existent column fails.
No warehouse, no credentials.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from di0.core import Engine, ValidationFailed
from di0.profile import Profile
from di0.registry import (
    build_dialect_port,
    build_execution_port,
    build_schema_port,
    build_validation_port,
)

FIXTURE_MANIFEST = str(Path(__file__).parent / "fixtures" / "manifest.json")


def _engine() -> Engine:
    profile = Profile(
        schema_source="dbt-manifest",
        dialect="snowflake",
        validation="sqlglot-offline",
        execution="noop",
        options={"manifest_path": FIXTURE_MANIFEST},
    )
    return Engine(
        schema_port=build_schema_port(profile),
        dialect_port=build_dialect_port(profile),
        validation_port=build_validation_port(profile),
        execution_port=build_execution_port(profile),
    )


def test_known_columns_pass() -> None:
    sql = """
        SELECT customer_id, current_arr
        FROM analytics.dim_customers
        WHERE is_internal_account = FALSE
    """
    assert _engine().validate(sql).ok


def test_join_across_models_passes() -> None:
    sql = """
        SELECT c.customer_id, SUM(r.arr) AS total_arr
        FROM analytics.dim_customers c
        JOIN analytics.fct_subscription_revenue r ON r.customer_id = c.customer_id
        GROUP BY c.customer_id
    """
    assert _engine().validate(sql).ok


def test_unknown_column_fails() -> None:
    sql = "SELECT customer_id, nonexistent_column FROM analytics.dim_customers"
    result = _engine().validate(sql)
    assert not result.ok
    assert result.errors


def test_unknown_table_fails() -> None:
    sql = "SELECT customer_id FROM analytics.dim_not_a_table"
    result = _engine().validate(sql)
    assert not result.ok


def test_query_refuses_to_execute_invalid_sql() -> None:
    sql = "SELECT nope FROM analytics.dim_customers"
    with pytest.raises(ValidationFailed):
        _engine().query(sql)
