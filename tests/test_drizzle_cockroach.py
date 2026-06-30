"""Slice #6: a Drizzle schema source + CockroachDB dialect, profile-only swap.

A third schema source and a third dialect, with the `catalog` namespace and the
soft-delete column both read from the drizzle-kit snapshot - no table name typed
by hand, and only the profile changed from the earlier slices.
"""

from __future__ import annotations

from pathlib import Path

from di0.core import Engine
from di0.profile import Profile
from di0.registry import (
    build_dialect_port,
    build_execution_port,
    build_schema_port,
    build_validation_port,
)

SNAPSHOT = str(Path(__file__).parent / "fixtures" / "drizzle" / "snapshot.json")

PRODUCTS_BY_CATEGORY = """
SELECT
  c.name                AS category,
  COUNT(*)              AS products,
  SUM(p.price)          AS total_price
FROM catalog.product p
JOIN catalog.category c ON c.id = p.category_id
WHERE p.deleted_at IS NULL
  AND c.deleted_at IS NULL
GROUP BY c.name
ORDER BY total_price DESC
"""


def _engine() -> Engine:
    profile = Profile(
        schema_source="drizzle-snapshot",
        dialect="cockroachdb",
        validation="sqlglot-offline",
        execution="noop",
        options={"snapshot_path": SNAPSHOT},
    )
    return Engine(
        schema_port=build_schema_port(profile),
        dialect_port=build_dialect_port(profile),
        validation_port=build_validation_port(profile),
        execution_port=build_execution_port(profile),
    )


def test_namespaces_resolved_from_snapshot():
    schema = build_schema_port(
        Profile("drizzle-snapshot", "cockroachdb", "sqlglot-offline", "noop",
                {"snapshot_path": SNAPSHOT})
    ).resolve()
    assert "catalog" in schema
    assert set(schema["catalog"]) == {"product", "category"}
    assert "deleted_at" in schema["catalog"]["product"]


def test_schema_qualified_soft_delete_join_validates():
    assert _engine().validate(PRODUCTS_BY_CATEGORY).ok


def test_unknown_column_on_cockroach_schema_fails():
    result = _engine().validate("SELECT sku FROM catalog.product")
    assert not result.ok
