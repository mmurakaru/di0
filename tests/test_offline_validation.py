"""Offline validation must tolerate manifests with zero-column models.

Real dbt manifests contain models without a column-level contract; sqlglot's
MappingSchema raises on a zero-column table. The validator prunes those rather
than crashing, while still catching unknown columns on contracted tables.
"""

from __future__ import annotations

from di0.adapters.sqlglot_validation import SqlglotOfflineValidation

SCHEMA = {
    "analytics": {
        "dim_customers": {"customer_id": "integer", "current_arr": "number"},
        "uncontracted_model": {},  # zero columns - would crash MappingSchema unpruned
    }
}


def test_valid_query_passes_despite_empty_column_table():
    validator = SqlglotOfflineValidation("snowflake")
    result = validator.validate(
        "SELECT customer_id, current_arr FROM analytics.dim_customers", SCHEMA
    )
    assert result.ok


def test_unknown_column_still_caught():
    validator = SqlglotOfflineValidation("snowflake")
    result = validator.validate("SELECT nope FROM analytics.dim_customers", SCHEMA)
    assert not result.ok
