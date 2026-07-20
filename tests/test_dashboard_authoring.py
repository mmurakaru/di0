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


def test_authors_into_own_subcollection(metabase_authoring, monkeypatch, tmp_path):
    base_url, recorder = metabase_authoring
    monkeypatch.setenv("DI0_TEST_METABASE_KEY", "secret-token")

    (tmp_path / "q.sql").write_text("SELECT customer_id FROM analytics.dim_customers")
    spec_path = tmp_path / "dash.yml"
    spec_path.write_text(
        "name: Account Health\n"
        "collection_id: 42\n"
        "own_collection: true\n"
        "tabs:\n"
        "  - name: Main\n"
        "    cards:\n"
        "      - title: Customers\n"
        "        query: q.sql\n"
    )

    spec = DashboardSpec.from_file(spec_path)
    deliverable = _engine(base_url).author(spec, base_dir=tmp_path)

    # a sub-collection named for the dashboard is created under the parent (fake -> id 701)
    assert recorder.created_collections == [{"name": "Account Health", "parent_id": 42}]
    # the dashboard and its card land in that sub-collection, not the parent
    assert recorder.dashboard["collection_id"] == 701
    assert recorder.cards[0]["collection_id"] == 701
    assert deliverable.detail["collection_id"] == 701


def test_authors_dashboard_with_wired_filter(metabase_authoring, monkeypatch, tmp_path):
    base_url, recorder = metabase_authoring
    monkeypatch.setenv("DI0_TEST_METABASE_KEY", "secret-token")

    # A parameterized query: the [[ ]] optional block and {{arr}} tag are stripped
    # for validation, then authored verbatim so the filter has a tag to target.
    (tmp_path / "arr.sql").write_text(
        "SELECT customer_id, current_arr FROM analytics.dim_customers "
        "WHERE [[ current_arr = {{arr}} AND ]] true"
    )
    spec_path = tmp_path / "dash.yml"
    spec_path.write_text(
        "name: Filtered ARR\n"
        "collection_id: 42\n"
        "parameters:\n"
        "  - name: ARR band\n"
        "    slug: arr\n"
        "    type: category\n"
        "    values: [100, 200]\n"
        "tabs:\n"
        "  - name: Main\n"
        "    cards:\n"
        "      - title: ARR\n"
        "        query: arr.sql\n"
        "        params: {arr: arr}\n"
    )

    spec = DashboardSpec.from_file(spec_path)
    _engine(base_url).author(spec, base_dir=tmp_path)

    # 1. the card declares the template tag Metabase filters target, authored verbatim
    native = recorder.cards[0]["dataset_query"]["native"]
    assert "arr" in native["template-tags"]
    assert "{{arr}}" in native["query"]

    # 2. the dashboard carries the filter as a static-list parameter
    layout = recorder.layout
    assert len(layout["parameters"]) == 1
    param = layout["parameters"][0]
    assert param["slug"] == "arr"
    assert param["values_source_type"] == "static-list"
    assert param["values_source_config"]["values"] == [100, 200]

    # 3. the card is wired to the parameter through its template-tag variable
    dashcard = next(dc for dc in layout["dashcards"] if dc.get("card_id"))
    mapping = dashcard["parameter_mappings"][0]
    assert mapping["parameter_id"] == param["id"]
    assert mapping["target"] == ["variable", ["template-tag", "arr"]]


def test_authors_dashboard_with_field_filter(metabase_authoring, monkeypatch, tmp_path):
    base_url, recorder = metabase_authoring
    monkeypatch.setenv("DI0_TEST_METABASE_KEY", "secret-token")

    # A variable listed under `field_filters` is authored as a Metabase Field Filter
    # (a `dimension` tag bound to a column), which is what unlocks multi-value filtering.
    (tmp_path / "region.sql").write_text(
        "SELECT customer_id FROM analytics.dim_customers WHERE [[ {{region}} AND ]] true"
    )
    spec_path = tmp_path / "dash.yml"
    spec_path.write_text(
        "name: Region breakdown\n"
        "collection_id: 42\n"
        "parameters:\n"
        "  - name: Region\n"
        "    slug: region\n"
        "    type: string/=\n"
        "    default: [emea, apac]\n"
        "tabs:\n"
        "  - name: Main\n"
        "    cards:\n"
        "      - title: Customers\n"
        "        query: region.sql\n"
        "        params: {region: region}\n"
        "        field_filters:\n"
        "          region:\n"
        "            field_id: 555\n"
        "            widget_type: string/=\n"
    )

    spec = DashboardSpec.from_file(spec_path)
    _engine(base_url).author(spec, base_dir=tmp_path)

    # 1. the template tag is a Field Filter (dimension) bound to the given column
    tag = recorder.cards[0]["dataset_query"]["native"]["template-tags"]["region"]
    assert tag["type"] == "dimension"
    assert tag["dimension"] == ["field", 555, None]
    assert tag["widget-type"] == "string/="

    # 2. the card is wired to the parameter through a dimension target (not a raw variable)
    layout = recorder.layout
    param = layout["parameters"][0]
    assert param["type"] == "string/="
    assert param["default"] == ["emea", "apac"]
    dashcard = next(dc for dc in layout["dashcards"] if dc.get("card_id"))
    mapping = dashcard["parameter_mappings"][0]
    assert mapping["target"] == ["dimension", ["template-tag", "region"]]


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
