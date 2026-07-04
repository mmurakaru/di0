"""Authoring extras: collection placement, card annotations, axis labels.

These let a dashboard land in a specific collection (not the shared root) with
annotated cards and readable axes - all driven by the spec, asserted against a
mocked Metabase that records the payloads it receives.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from di0.core import Engine
from di0.deliverable import DashboardSpec
from di0.profile import Profile
from di0.registry import build_engine, build_execution_port

FIXTURE_MANIFEST = str(Path(__file__).parent / "fixtures" / "manifest.json")


def _profile(base_url: str) -> Profile:
    return Profile(
        "dbt-manifest", "snowflake", "sqlglot-offline", "metabase",
        {
            "manifest_path": FIXTURE_MANIFEST,
            "metabase_url": base_url,
            "metabase_database_id": 7,
            "metabase_auth": "session",
            "metabase_session_env": "DI0_TEST_SESSION",
        },
    )


def _engine(base_url: str) -> Engine:
    return build_engine(_profile(base_url))


def test_author_places_in_collection_with_annotations_and_axes(
    metabase_authoring, monkeypatch, tmp_path
):
    base_url, recorder = metabase_authoring
    monkeypatch.setenv("DI0_TEST_SESSION", "sess")
    (tmp_path / "q.sql").write_text(
        "SELECT revenue_month, SUM(arr) AS arr FROM analytics.fct_subscription_revenue "
        "GROUP BY revenue_month"
    )
    spec_path = tmp_path / "dash.yml"
    spec_path.write_text(
        "name: Revenue\n"
        "collection_id: 42\n"
        "tabs:\n"
        "  - name: Trend\n"
        "    cards:\n"
        "      - title: Monthly ARR\n"
        "        query: q.sql\n"
        "        display: line\n"
        "        description: Monthly recurring revenue from subscriptions.\n"
        "        x_label: Month\n"
        "        y_label: ARR (USD)\n"
    )

    deliverable = _engine(base_url).author(DashboardSpec.from_file(spec_path), base_dir=tmp_path)

    card = recorder.cards[0]
    assert card["collection_id"] == 42
    assert card["description"] == "Monthly recurring revenue from subscriptions."
    assert card["visualization_settings"]["graph.x_axis.title_text"] == "Month"
    assert card["visualization_settings"]["graph.y_axis.title_text"] == "ARR (USD)"
    assert recorder.dashboard["collection_id"] == 42
    assert deliverable.detail["collection_id"] == 42


def test_text_card_is_virtual_and_grid_and_viz_passthrough(
    metabase_authoring, monkeypatch, tmp_path
):
    base_url, recorder = metabase_authoring
    monkeypatch.setenv("DI0_TEST_SESSION", "sess")
    (tmp_path / "q.sql").write_text("SELECT customer_id FROM analytics.dim_customers")
    spec_path = tmp_path / "dash.yml"
    spec_path.write_text(
        "name: Brief\n"
        "collection_id: 42\n"
        "tabs:\n"
        "  - name: Overview\n"
        "    cards:\n"
        "      - text: '# Executive Brief\\n\\nKey facts.'\n"
        "        size_x: 24\n"
        "        size_y: 2\n"
        "      - title: Customers\n"
        "        query: q.sql\n"
        "        display: scalar\n"
        "        row: 2\n"
        "        col: 0\n"
        "        size_x: 6\n"
        "        size_y: 4\n"
        "        viz:\n"
        "          scalar.field: customer_id\n"
        "          column_settings: {}\n"
    )

    _engine(base_url).author(DashboardSpec.from_file(spec_path), base_dir=tmp_path)

    # Only the query card hit /api/card; the text card did not.
    assert len(recorder.cards) == 1
    assert recorder.cards[0]["visualization_settings"]["scalar.field"] == "customer_id"

    dashcards = recorder.layout["dashcards"]
    text_dc = next(dc for dc in dashcards if dc.get("card_id") is None)
    query_dc = next(dc for dc in dashcards if dc.get("card_id") is not None)
    assert "Executive Brief" in text_dc["visualization_settings"]["text"]
    # Metabase renders a text card only with the virtual_card scaffold.
    assert text_dc["visualization_settings"]["virtual_card"]["display"] == "text"
    assert (query_dc["row"], query_dc["col"], query_dc["size_x"]) == (2, 0, 6)


def test_text_card_heading_display(metabase_authoring, monkeypatch, tmp_path):
    base_url, recorder = metabase_authoring
    monkeypatch.setenv("DI0_TEST_SESSION", "sess")
    spec_path = tmp_path / "dash.yml"
    spec_path.write_text(
        "name: H\n"
        "collection_id: 42\n"
        "tabs:\n"
        "  - name: T\n"
        "    cards:\n"
        "      - text: Section title\n"
        "        display: heading\n"
    )
    _engine(base_url).author(DashboardSpec.from_file(spec_path), base_dir=tmp_path)
    dc = recorder.layout["dashcards"][0]
    assert dc["visualization_settings"]["virtual_card"]["display"] == "heading"
    assert dc["visualization_settings"]["text"] == "Section title"


def test_replace_updates_existing_dashboard_in_place(metabase_authoring, monkeypatch, tmp_path):
    base_url, recorder = metabase_authoring
    monkeypatch.setenv("DI0_TEST_SESSION", "sess")
    recorder.collection_items = [
        {"id": 500, "name": "Revenue", "model": "dashboard"},
        {"id": 501, "name": "Something else", "model": "dashboard"},
    ]
    recorder.existing_dashboard = {
        "id": 500,
        "tabs": [{"id": 77, "name": "T"}],
        "dashcards": [
            {"card_id": 901, "card": {"name": "c"}},  # same title -> reused in place
            {"card_id": 902, "card": {"name": "gone this run"}},  # unreferenced -> archived
            {"card_id": None},  # a text card
        ],
    }
    (tmp_path / "q.sql").write_text("SELECT customer_id FROM analytics.dim_customers")
    spec_path = tmp_path / "dash.yml"
    spec_path.write_text(
        "name: Revenue\n"
        "collection_id: 42\n"
        "replace: true\n"
        "tabs:\n"
        "  - name: T\n"
        "    cards:\n"
        "      - title: c\n"
        "        query: q.sql\n"
    )

    deliverable = _engine(base_url).author(DashboardSpec.from_file(spec_path), base_dir=tmp_path)

    # Updated in place: the layout PUT targets the existing dashboard, id preserved,
    # and no new dashboard was POSTed - so the URL is stable across rebuilds.
    assert deliverable.identifier == "500"
    assert recorder.layout_path == "/api/dashboard/500"
    assert recorder.dashboard is None  # no POST /api/dashboard
    # The tab is matched by name and keeps its existing id (77), not a fresh negative id.
    assert recorder.layout["tabs"] == [{"id": 77, "name": "T"}]

    # The card "c" is matched by title and updated in place (id 901 kept), not recreated.
    assert recorder.cards == []  # no POST /api/card
    assert [p for p, _ in recorder.updated_cards] == ["/api/card/901"]
    query_dc = next(dc for dc in recorder.layout["dashcards"] if dc.get("card_id"))
    assert query_dc["card_id"] == 901

    archived_paths = [p for p, _ in recorder.archived]
    assert "/api/card/902" in archived_paths  # the card gone this run is archived
    assert "/api/card/901" not in archived_paths  # the reused card is NOT archived
    assert all("/api/dashboard/500" not in p for p in archived_paths)  # dashboard NOT archived
    assert all("501" not in p for p in archived_paths)  # the other dashboard untouched
    assert all(body == {"archived": True} for _, body in recorder.archived)


def test_replace_with_no_existing_creates_new_dashboard(metabase_authoring, monkeypatch, tmp_path):
    base_url, recorder = metabase_authoring
    monkeypatch.setenv("DI0_TEST_SESSION", "sess")
    recorder.collection_items = []  # first-ever build: nothing to update in place
    (tmp_path / "q.sql").write_text("SELECT customer_id FROM analytics.dim_customers")
    spec_path = tmp_path / "dash.yml"
    spec_path.write_text(
        "name: Fresh\n"
        "collection_id: 42\n"
        "replace: true\n"
        "tabs:\n"
        "  - name: T\n"
        "    cards:\n"
        "      - title: c\n"
        "        query: q.sql\n"
    )

    deliverable = _engine(base_url).author(DashboardSpec.from_file(spec_path), base_dir=tmp_path)

    assert recorder.dashboard == {"name": "Fresh", "collection_id": 42}  # POSTed new
    assert deliverable.identifier == "42"
    assert recorder.archived == []  # nothing to archive on a first build


def test_organize_by_tab_files_cards_into_per_tab_subcollections(
    metabase_authoring, monkeypatch, tmp_path
):
    base_url, recorder = metabase_authoring
    monkeypatch.setenv("DI0_TEST_SESSION", "sess")
    (tmp_path / "a.sql").write_text("SELECT customer_id FROM analytics.dim_customers")
    (tmp_path / "b.sql").write_text("SELECT arr FROM analytics.fct_subscription_revenue")
    spec_path = tmp_path / "dash.yml"
    spec_path.write_text(
        "name: D\n"
        "collection_id: 42\n"
        "organize_by_tab: true\n"
        "tabs:\n"
        "  - name: Census\n"
        "    cards:\n"
        "      - title: a\n"
        "        query: a.sql\n"
        "  - name: Revenue\n"
        "    cards:\n"
        "      - title: b\n"
        "        query: b.sql\n"
    )

    deliverable = _engine(base_url).author(DashboardSpec.from_file(spec_path), base_dir=tmp_path)

    # A sub-collection was created per tab, under the parent (42).
    assert {"name": "Census", "parent_id": 42} in recorder.created_collections
    assert {"name": "Revenue", "parent_id": 42} in recorder.created_collections
    # Each tab's card was filed into its tab sub-collection (701, 702), not the parent.
    assert recorder.cards[0]["collection_id"] == 701
    assert recorder.cards[1]["collection_id"] == 702
    # The dashboard itself stays in the parent collection.
    assert recorder.dashboard["collection_id"] == 42
    assert deliverable.detail["collection_id"] == 42


def test_profile_default_collection_used_when_spec_omits_it(
    metabase_authoring, monkeypatch, tmp_path
):
    base_url, recorder = metabase_authoring
    monkeypatch.setenv("DI0_TEST_SESSION", "sess")
    (tmp_path / "q.sql").write_text("SELECT customer_id FROM analytics.dim_customers")
    spec_path = tmp_path / "dash.yml"
    spec_path.write_text(
        "name: D\ntabs:\n  - name: T\n    cards:\n      - title: c\n        query: q.sql\n"
    )

    profile = Profile(
        "dbt-manifest", "snowflake", "sqlglot-offline", "metabase",
        {
            "manifest_path": FIXTURE_MANIFEST, "metabase_url": base_url,
            "metabase_database_id": 7, "metabase_auth": "session",
            "metabase_session_env": "DI0_TEST_SESSION", "metabase_collection": 555,
        },
    )
    engine = build_engine(profile)
    deliverable = engine.author(DashboardSpec.from_file(spec_path), base_dir=tmp_path)
    # Spec had no collection_id, so the profile default (555) is used.
    assert recorder.cards[0]["collection_id"] == 555
    assert recorder.dashboard["collection_id"] == 555
    assert deliverable.detail["collection_id"] == 555


def test_refuse_shared_root_when_no_collection_anywhere(metabase_authoring, monkeypatch, tmp_path):
    base_url, _ = metabase_authoring
    monkeypatch.setenv("DI0_TEST_SESSION", "sess")
    (tmp_path / "q.sql").write_text("SELECT customer_id FROM analytics.dim_customers")
    spec_path = tmp_path / "dash.yml"
    spec_path.write_text(
        "name: D\ntabs:\n  - name: T\n    cards:\n      - title: c\n        query: q.sql\n"
    )

    # No spec collection_id and no profile default -> refuse.
    with pytest.raises(ValueError, match="shared root"):
        _engine(base_url).author(DashboardSpec.from_file(spec_path), base_dir=tmp_path)


def test_ensure_collection_creates_under_parent(metabase_authoring, monkeypatch):
    base_url, recorder = metabase_authoring
    monkeypatch.setenv("DI0_TEST_SESSION", "sess")
    adapter = build_execution_port(_profile(base_url))

    new_id = adapter.ensure_collection("quarterly-reviews", parent_id=42)

    assert new_id == 701
    assert recorder.created_collections[0] == {"name": "quarterly-reviews", "parent_id": 42}


def test_ensure_collection_reuses_existing(metabase_authoring, monkeypatch):
    base_url, recorder = metabase_authoring
    monkeypatch.setenv("DI0_TEST_SESSION", "sess")
    recorder.collections = [
        {"id": 999, "name": "quarterly-reviews", "location": "/42/"},
        {"id": 111, "name": "quarterly-reviews", "location": "/9/"},  # different parent
    ]
    adapter = build_execution_port(_profile(base_url))

    found = adapter.ensure_collection("quarterly-reviews", parent_id=42)

    assert found == 999
    assert recorder.created_collections == []  # did not create a duplicate