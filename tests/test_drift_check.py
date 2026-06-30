"""Slice #3: the precompile check turns a column rename into a red build.

The same committed query is validated against two manifests - before and after a
column rename. Drift must flip the result from valid to invalid.
"""

from __future__ import annotations

import json
from pathlib import Path

from di0.core import Engine
from di0.profile import Profile
from di0.registry import (
    build_dialect_port,
    build_execution_port,
    build_schema_port,
    build_validation_port,
)


def _manifest(current_arr_name: str) -> dict:
    return {
        "nodes": {
            "model.acme.dim_customers": {
                "resource_type": "model",
                "name": "dim_customers",
                "schema": "analytics",
                "columns": {
                    "customer_id": {"name": "customer_id", "data_type": "integer"},
                    current_arr_name: {"name": current_arr_name, "data_type": "number"},
                },
            }
        }
    }


def _engine(manifest_path: Path) -> Engine:
    profile = Profile(
        schema_source="dbt-manifest",
        dialect="snowflake",
        validation="sqlglot-offline",
        execution="noop",
        options={"manifest_path": str(manifest_path)},
    )
    return Engine(
        schema_port=build_schema_port(profile),
        dialect_port=build_dialect_port(profile),
        validation_port=build_validation_port(profile),
        execution_port=build_execution_port(profile),
    )


def test_rename_upstream_turns_check_red(tmp_path):
    query = tmp_path / "arr.sql"
    query.write_text("SELECT customer_id, current_arr FROM analytics.dim_customers")
    manifest = tmp_path / "manifest.json"

    manifest.write_text(json.dumps(_manifest("current_arr")))
    before = _engine(manifest).validate_paths([query])
    assert before[0][1].ok  # query matches the schema

    manifest.write_text(json.dumps(_manifest("annual_recurring_revenue")))
    after = _engine(manifest).validate_paths([query])
    assert not after[0][1].ok  # the rename is now caught at build time
    assert after[0][1].errors
