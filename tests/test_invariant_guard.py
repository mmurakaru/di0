"""Slice #9: the invariant guard catches hard-coded references in the core.

The clean core passes. A planted warehouse name or a bare `schema.table` literal
is caught. Adapter modules and the composition edge are excluded, which is what
lets the clean scan pass even though adapters legitimately name warehouses.
"""

from __future__ import annotations

from pathlib import Path

from di0.guard import scan_tree

CORE = Path(__file__).parent.parent / "src" / "di0"


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
