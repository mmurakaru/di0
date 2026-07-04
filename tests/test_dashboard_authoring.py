"""Slice #4: author a multi-tab dashboard from validated queries.

A mocked Metabase records the cards, dashboard, and final layout PUT so we can
assert the artifact was assembled from the spec - and that an invalid query
prevents any card from being created.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from di0.core import Engine, ValidationFailed
from di0.deliverable import DashboardSpec
from di0.profile import Profile
from di0.registry import build_engine

FIXTURE_MANIFEST = str(Path(__file__).parent / "fixtures" / "manifest.json")


def _engine(base_url: str) -> Engine:
    profile = Profile(
        schema_source="dbt-manifest",
        dialect="snowflake",
        validation="sqlglot-offline",
        execution="metabase",
        options={
            "manifest_path": FIXTURE_MANIFEST,
            "metabase_url": base_url,
            "metabase_database_id": 7,
            "metabase_api_key_env": "DI0_TEST_METABASE_KEY",
        },
    )
    return build_engine(profile)


def test_authors_multi_tab_dashboard(metabase_authoring, monkeypatch, tmp_path):
    base_url, recorder = metabase_authoring
    monkeypatch.setenv("DI0_TEST_METABASE_KEY", "secret-token")

    (tmp_path / "overview.sql").write_text(
        "SELECT customer_id, current_arr FROM analytics.dim_customers"
    )
    (tmp_path / "trend.sql").write_text(
        "SELECT revenue_month, SUM(arr) AS total_arr "
        "FROM analytics.fct_subscription_revenue GROUP BY revenue_month"
    )
    spec_path = tmp_path / "dash.yml"
    spec_path.write_text(
        "name: ARR Overview\n"
        "collection_id: 42\n"
        "tabs:\n"
        "  - name: Overview\n"
        "    cards:\n"
        "      - title: ARR by customer\n"
        "        query: overview.sql\n"
        "  - name: Trend\n"
        "    cards:\n"
        "      - title: Monthly ARR\n"
        "        query: trend.sql\n"
    )

    spec = DashboardSpec.from_file(spec_path)
    deliverable = _engine(base_url).author(spec, base_dir=tmp_path)

    assert deliverable.kind == "dashboard"
    assert deliverable.identifier == "42"
    assert len(recorder.cards) == 2  # one card per query
    assert recorder.dashboard == {"name": "ARR Overview", "collection_id": 42}
    # two tabs declared, each with its card pinned to the right tab
    assert [tab["name"] for tab in recorder.layout["tabs"]] == ["Overview", "Trend"]
    tab_ids = {dc["dashboard_tab_id"] for dc in recorder.layout["dashcards"]}
    assert tab_ids == {-1, -2}


def test_invalid_query_blocks_all_card_creation(metabase_authoring, monkeypatch, tmp_path):
    base_url, recorder = metabase_authoring
    monkeypatch.setenv("DI0_TEST_METABASE_KEY", "secret-token")

    (tmp_path / "bad.sql").write_text("SELECT churn_risk FROM analytics.dim_customers")
    spec_path = tmp_path / "dash.yml"
    spec_path.write_text(
        "name: Broken\ntabs:\n  - name: T\n    cards:\n      - title: bad\n        query: bad.sql\n"
    )

    spec = DashboardSpec.from_file(spec_path)
    with pytest.raises(ValidationFailed):
        _engine(base_url).author(spec, base_dir=tmp_path)

    assert recorder.cards == []  # nothing authored when a query is invalid
