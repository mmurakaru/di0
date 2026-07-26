"""Slice #65: a BI-neutral DashboardSpec, proven purely additive.

The first tests are a regression harness: they author a representative multi-tab
spec that exercises every feature the spec has today - text and heading cards,
the full display vocabulary in real use, raw `viz` pass-through, absolute grid
placement, collection_id, replace, and dashboard parameters wired to per-card
variables and field filters - and pin the exact Metabase API payloads the
adapter produces. They are the proof that the new neutral fields (native escape
hatch, logical width/height sizing, collection-by-name) never disturb the path
real production dashboards depend on.

The remaining tests cover each new neutral feature in isolation.
"""

from __future__ import annotations

from pathlib import Path

from di0.core import Engine
from di0.deliverable import DashboardSpec
from di0.profile import Profile
from di0.registry import build_engine

FIXTURE_MANIFEST = str(Path(__file__).parent / "fixtures" / "manifest.json")


def _profile(base_url: str) -> Profile:
    return Profile(
        "dbt-manifest", "snowflake", "sqlglot-offline", "metabase",
        {
            "manifest_path": FIXTURE_MANIFEST,
            "metabase_url": base_url,
            "metabase_database_id": 7,
            "metabase_api_key_env": "DI0_TEST_METABASE_KEY",
        },
    )


def _engine(base_url: str) -> Engine:
    return build_engine(_profile(base_url))


def _write_queries(tmp_path: Path) -> None:
    (tmp_path / "customers.sql").write_text(
        "SELECT customer_id, current_arr FROM analytics.dim_customers"
    )
    (tmp_path / "revenue.sql").write_text(
        "SELECT revenue_month, SUM(arr) AS total_arr "
        "FROM analytics.fct_subscription_revenue GROUP BY revenue_month"
    )
    (tmp_path / "filtered.sql").write_text(
        "SELECT customer_id, current_arr FROM analytics.dim_customers "
        "WHERE [[ current_arr = {{arr}} AND ]] [[ {{region}} AND ]] true"
    )


COCKPIT_SPEC = """\
name: Revenue Cockpit
collection_id: 42
replace: true
parameters:
  - name: ARR band
    slug: arr
    type: category
    values: [100, 200]
  - name: Region
    slug: region
    type: string/=
    default: [emea, apac]
tabs:
  - name: Overview
    cards:
      - text: '# Revenue Cockpit'
        display: heading
        size_x: 24
        size_y: 1
      - text: 'Key revenue facts for the quarter.'
        size_x: 24
        size_y: 2
      - title: Total customers
        query: customers.sql
        display: scalar
        row: 3
        col: 0
        size_x: 6
        size_y: 4
        description: Distinct customers.
        viz:
          scalar.field: customer_id
      - title: ARR by month
        query: revenue.sql
        display: bar
        row: 3
        col: 6
        size_x: 18
        size_y: 8
        x_label: Month
        y_label: ARR (USD)
        viz:
          graph.dimensions: [revenue_month]
          graph.metrics: [total_arr]
          graph.y_axis.scale: log
      - title: Customer table
        query: customers.sql
        display: table
        row: 11
        col: 0
        size_x: 24
        size_y: 6
  - name: Detail
    cards:
      - title: ARR trend
        query: revenue.sql
        display: line
      - title: Customers by plan
        query: customers.sql
        display: row
      - title: ARR share
        query: customers.sql
        display: pie
      - title: Conversion funnel
        query: customers.sql
        display: funnel
      - title: ARR combo
        query: revenue.sql
        display: combo
      - title: Filtered ARR
        query: filtered.sql
        display: table
        params: {arr: arr, region: region}
        field_filters:
          region:
            field_id: 555
            widget_type: string/=
"""


def test_backcompat_full_authoring_payloads(metabase_authoring, monkeypatch, tmp_path):
    base_url, recorder = metabase_authoring
    monkeypatch.setenv("DI0_TEST_METABASE_KEY", "secret-token")
    _write_queries(tmp_path)
    (tmp_path / "dash.yml").write_text(COCKPIT_SPEC)

    deliverable = _engine(base_url).author(
        DashboardSpec.from_file(tmp_path / "dash.yml"), base_dir=tmp_path
    )

    # --- cards: every display value in real use reached /api/card ---
    assert {c["display"] for c in recorder.cards} == {
        "scalar", "bar", "table", "line", "row", "pie", "funnel", "combo"
    }
    assert len(recorder.cards) == 9  # nine query cards; the two text cards are virtual
    assert all(c["collection_id"] == 42 for c in recorder.cards)

    # --- scalar card: viz shorthand pass-through + description ---
    scalar = next(c for c in recorder.cards if c["name"] == "Total customers")
    assert scalar["display"] == "scalar"
    assert scalar["visualization_settings"] == {"scalar.field": "customer_id"}
    assert scalar["description"] == "Distinct customers."

    # --- bar card: raw viz keys pass through and axis-label shorthands are merged ---
    bar = next(c for c in recorder.cards if c["name"] == "ARR by month")
    assert bar["display"] == "bar"
    assert bar["visualization_settings"] == {
        "graph.x_axis.title_text": "Month",
        "graph.y_axis.title_text": "ARR (USD)",
        "graph.dimensions": ["revenue_month"],
        "graph.metrics": ["total_arr"],
        "graph.y_axis.scale": "log",
    }

    # --- parameterized card: field filter is a dimension tag, raw variable is text ---
    filtered = next(c for c in recorder.cards if c["name"] == "Filtered ARR")
    native = filtered["dataset_query"]["native"]
    assert "{{arr}}" in native["query"] and "{{region}}" in native["query"]
    assert native["template-tags"]["arr"]["type"] == "text"
    region_tag = native["template-tags"]["region"]
    assert region_tag["type"] == "dimension"
    assert region_tag["dimension"] == ["field", 555, None]
    assert region_tag["widget-type"] == "string/="

    # --- dashboard POST body and stable-URL PUT target ---
    assert recorder.dashboard == {"name": "Revenue Cockpit", "collection_id": 42}
    assert recorder.layout_path == "/api/dashboard/42"

    layout = recorder.layout
    dashcards = layout["dashcards"]

    # --- tabs: two tabs, negative placeholder ids, each card pinned to its tab ---
    assert [t["name"] for t in layout["tabs"]] == ["Overview", "Detail"]
    assert [t["id"] for t in layout["tabs"]] == [-1, -2]
    assert {dc["dashboard_tab_id"] for dc in dashcards} == {-1, -2}

    # --- text/heading cards are virtual (no card_id) with the right scaffold ---
    text_dcs = [dc for dc in dashcards if dc.get("card_id") is None]
    heading = next(
        dc for dc in text_dcs
        if dc["visualization_settings"]["virtual_card"]["display"] == "heading"
    )
    assert "Revenue Cockpit" in heading["visualization_settings"]["text"]
    body = next(
        dc for dc in text_dcs
        if dc["visualization_settings"]["virtual_card"]["display"] == "text"
    )
    assert "Key revenue facts" in body["visualization_settings"]["text"]

    # --- absolute grid placement is preserved exactly ---
    def at(row: int, col: int) -> dict:
        return next(
            dc for dc in dashcards
            if (dc["row"], dc["col"]) == (row, col) and dc.get("card_id")
        )

    scalar_dc = at(3, 0)
    assert (scalar_dc["size_x"], scalar_dc["size_y"]) == (6, 4)
    bar_dc = at(3, 6)
    assert (bar_dc["size_x"], bar_dc["size_y"]) == (18, 8)
    table_dc = at(11, 0)
    assert (table_dc["size_x"], table_dc["size_y"]) == (24, 6)

    # --- dashboard parameters normalized; values shorthand becomes a static list ---
    params = layout["parameters"]
    arr_param = next(p for p in params if p["slug"] == "arr")
    assert arr_param["values_source_type"] == "static-list"
    assert arr_param["values_source_config"]["values"] == [100, 200]
    region_param = next(p for p in params if p["slug"] == "region")
    assert region_param["type"] == "string/="
    assert region_param["default"] == ["emea", "apac"]

    # --- the parameterized card is wired to both parameters, dimension vs variable ---
    filtered_dc = next(dc for dc in dashcards if dc.get("parameter_mappings"))
    by_param = {m["parameter_id"]: m["target"] for m in filtered_dc["parameter_mappings"]}
    assert by_param[arr_param["id"]] == ["variable", ["template-tag", "arr"]]
    assert by_param[region_param["id"]] == ["dimension", ["template-tag", "region"]]

    # --- returned deliverable ---
    assert deliverable.kind == "dashboard"
    assert deliverable.identifier == "42"
    assert len(deliverable.detail["card_ids"]) == 9
    assert deliverable.detail["collection_id"] == 42


def test_backcompat_replace_updates_in_place(metabase_authoring, monkeypatch, tmp_path):
    base_url, recorder = metabase_authoring
    monkeypatch.setenv("DI0_TEST_METABASE_KEY", "secret-token")
    recorder.collection_items = [{"id": 500, "name": "Revenue Cockpit", "model": "dashboard"}]
    recorder.existing_dashboard = {
        "id": 500,
        "tabs": [{"id": 77, "name": "Overview"}],
        "dashcards": [
            {"card_id": 901, "card": {"name": "Total customers"}},  # reused in place
            {"card_id": 902, "card": {"name": "gone this run"}},  # archived
        ],
    }
    (tmp_path / "customers.sql").write_text(
        "SELECT customer_id FROM analytics.dim_customers"
    )
    (tmp_path / "dash.yml").write_text(
        "name: Revenue Cockpit\n"
        "collection_id: 42\n"
        "replace: true\n"
        "tabs:\n"
        "  - name: Overview\n"
        "    cards:\n"
        "      - title: Total customers\n"
        "        query: customers.sql\n"
    )

    deliverable = _engine(base_url).author(
        DashboardSpec.from_file(tmp_path / "dash.yml"), base_dir=tmp_path
    )

    assert deliverable.identifier == "500"
    assert recorder.layout_path == "/api/dashboard/500"
    assert recorder.dashboard is None  # no POST /api/dashboard
    assert recorder.layout["tabs"] == [{"id": 77, "name": "Overview"}]
    assert recorder.cards == []  # matched by title -> updated in place, not recreated
    assert [p for p, _ in recorder.updated_cards] == ["/api/card/901"]
    assert "/api/card/902" in [p for p, _ in recorder.archived]


# --------------------------------------------------------------------------- #
# New neutral features, each additive and inert when unset.
# --------------------------------------------------------------------------- #


def _author_single_card(base_url, tmp_path, card_yaml: str, *, dashboard_yaml: str = "") -> None:
    (tmp_path / "q.sql").write_text("SELECT customer_id FROM analytics.dim_customers")
    (tmp_path / "dash.yml").write_text(
        "name: D\n"
        "collection_id: 42\n"
        f"{dashboard_yaml}"
        "tabs:\n"
        "  - name: T\n"
        "    cards:\n"
        f"{card_yaml}"
    )
    _engine(base_url).author(DashboardSpec.from_file(tmp_path / "dash.yml"), base_dir=tmp_path)


def test_native_merges_into_card_visualization_settings(metabase_authoring, monkeypatch, tmp_path):
    base_url, recorder = metabase_authoring
    monkeypatch.setenv("DI0_TEST_METABASE_KEY", "secret-token")
    _author_single_card(
        base_url, tmp_path,
        "      - title: c\n"
        "        query: q.sql\n"
        "        native:\n"
        "          metabase:\n"
        "            click_behavior: {type: link}\n"
        "            graph.show_values: true\n",
    )
    settings = recorder.cards[0]["visualization_settings"]
    assert settings["click_behavior"] == {"type": "link"}
    assert settings["graph.show_values"] is True


def test_viz_takes_precedence_over_native_on_conflict(metabase_authoring, monkeypatch, tmp_path):
    base_url, recorder = metabase_authoring
    monkeypatch.setenv("DI0_TEST_METABASE_KEY", "secret-token")
    _author_single_card(
        base_url, tmp_path,
        "      - title: c\n"
        "        query: q.sql\n"
        "        native:\n"
        "          metabase:\n"
        "            graph.y_axis.scale: linear\n"
        "        viz:\n"
        "          graph.y_axis.scale: log\n",
    )
    # viz wins on key conflict, so existing viz-only specs stay byte-identical.
    assert recorder.cards[0]["visualization_settings"]["graph.y_axis.scale"] == "log"


def test_logical_width_height_scale_to_metabase_grid(metabase_authoring, monkeypatch, tmp_path):
    base_url, recorder = metabase_authoring
    monkeypatch.setenv("DI0_TEST_METABASE_KEY", "secret-token")
    _author_single_card(
        base_url, tmp_path,
        "      - title: c\n"
        "        query: q.sql\n"
        "        width: 4\n"
        "        height: 3\n",
    )
    # A 12-unit logical grid scales x2 onto Metabase's 24-column grid.
    dc = next(d for d in recorder.layout["dashcards"] if d.get("card_id"))
    assert (dc["size_x"], dc["size_y"]) == (8, 6)


def test_absolute_size_used_when_logical_sizing_unset(metabase_authoring, monkeypatch, tmp_path):
    base_url, recorder = metabase_authoring
    monkeypatch.setenv("DI0_TEST_METABASE_KEY", "secret-token")
    _author_single_card(
        base_url, tmp_path,
        "      - title: c\n"
        "        query: q.sql\n"
        "        size_x: 10\n"
        "        size_y: 5\n",
    )
    dc = next(d for d in recorder.layout["dashcards"] if d.get("card_id"))
    assert (dc["size_x"], dc["size_y"]) == (10, 5)


def test_collection_by_name_resolves_to_id(metabase_authoring, monkeypatch, tmp_path):
    base_url, recorder = metabase_authoring
    monkeypatch.setenv("DI0_TEST_METABASE_KEY", "secret-token")
    (tmp_path / "q.sql").write_text("SELECT customer_id FROM analytics.dim_customers")
    (tmp_path / "dash.yml").write_text(
        "name: D\n"
        "collection: Quarterly Reviews\n"
        "tabs:\n"
        "  - name: T\n"
        "    cards:\n"
        "      - title: c\n"
        "        query: q.sql\n"
    )
    _engine(base_url).author(DashboardSpec.from_file(tmp_path / "dash.yml"), base_dir=tmp_path)

    # The name is resolved to an id through ensure_collection (fake -> 701).
    assert recorder.created_collections == [{"name": "Quarterly Reviews"}]
    assert recorder.dashboard["collection_id"] == 701
    assert recorder.cards[0]["collection_id"] == 701


def test_collection_id_takes_precedence_over_name(metabase_authoring, monkeypatch, tmp_path):
    base_url, recorder = metabase_authoring
    monkeypatch.setenv("DI0_TEST_METABASE_KEY", "secret-token")
    _author_single_card(
        base_url, tmp_path,
        "      - title: c\n        query: q.sql\n",
        dashboard_yaml="collection: Ignored\n",
    )
    # collection_id (42) wins, so the name is never resolved.
    assert recorder.created_collections == []
    assert recorder.dashboard["collection_id"] == 42


def test_dashboard_native_merges_into_dashboard_put(metabase_authoring, monkeypatch, tmp_path):
    base_url, recorder = metabase_authoring
    monkeypatch.setenv("DI0_TEST_METABASE_KEY", "secret-token")
    _author_single_card(
        base_url, tmp_path,
        "      - title: c\n        query: q.sql\n",
        dashboard_yaml="native:\n  metabase:\n    auto_apply_filters: false\n",
    )
    layout = recorder.layout
    assert layout["auto_apply_filters"] is False
    # The adapter's own keys are still present and win over native.
    assert "tabs" in layout and "dashcards" in layout and "parameters" in layout


def test_neutral_displays_documents_the_portable_vocabulary():
    from di0.deliverable import NEUTRAL_DISPLAYS

    # Free-form `display` is never validated against this; it is documentation
    # plus a set adapters can map from.
    for name in ("bar", "line", "area", "pie", "table", "scalar",
                 "pivot", "row", "funnel", "combo", "heading", "text"):
        assert name in NEUTRAL_DISPLAYS


def test_collection_by_name_reuses_existing(metabase_authoring, monkeypatch, tmp_path):
    base_url, recorder = metabase_authoring
    monkeypatch.setenv("DI0_TEST_METABASE_KEY", "secret-token")
    recorder.collections = [{"id": 321, "name": "Quarterly Reviews", "location": "/"}]
    (tmp_path / "q.sql").write_text("SELECT customer_id FROM analytics.dim_customers")
    (tmp_path / "dash.yml").write_text(
        "name: D\n"
        "collection: Quarterly Reviews\n"
        "tabs:\n"
        "  - name: T\n"
        "    cards:\n"
        "      - title: c\n"
        "        query: q.sql\n"
    )
    _engine(base_url).author(DashboardSpec.from_file(tmp_path / "dash.yml"), base_dir=tmp_path)

    # An existing same-name collection is reused, not duplicated.
    assert recorder.created_collections == []
    assert recorder.dashboard["collection_id"] == 321
