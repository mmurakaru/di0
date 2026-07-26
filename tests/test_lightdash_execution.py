"""Slice #55: the Lightdash ExecutionPort adapter.

A fake Lightdash HTTP backend (see conftest.lightdash_backend) stands in for the
real API so these run offline. They assert the adapter speaks the SQL-runner query
path for `execute`, and - for `author` - creates a space, one saved SQL chart per
query card, and a dashboard with native tabs plus sql_chart / markdown / heading
tiles. The restrictive capability descriptor means an unsupported display or any
dashboard parameter is refused by the core before a single write.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from di0.adapters.lightdash_execution import LightdashExecution
from di0.core import CapabilityError
from di0.deliverable import DashboardSpec
from di0.profile import Profile
from di0.registry import build_engine, build_execution_port

FIXTURE_MANIFEST = str(Path(__file__).parent / "fixtures" / "manifest.json")

CUSTOMERS_SQL = "SELECT customer_id, current_arr FROM analytics.dim_customers"


def _profile(base_url: str, **extra: object) -> Profile:
    options: dict[str, object] = {
        "manifest_path": FIXTURE_MANIFEST,
        "lightdash_url": base_url,
        "lightdash_project_uuid": "proj-uuid",
        "lightdash_api_key_env": "DI0_TEST_LIGHTDASH_TOKEN",
        "lightdash_space": "Analytics",
    }
    options.update(extra)
    return Profile("dbt-manifest", "snowflake", "sqlglot-offline", "lightdash", options)


# --- capability descriptor -----------------------------------------------------


def test_declares_the_restrictive_descriptor():
    caps = LightdashExecution("http://x", "proj").capabilities
    assert caps.authors is True
    assert caps.displays == frozenset({"bar", "line", "pie", "table"})
    assert caps.text_cards is True
    assert caps.parameters is False
    assert caps.grid_columns == 36


def test_registry_selects_the_adapter(lightdash_backend):
    base_url, _ = lightdash_backend
    adapter = build_execution_port(_profile(base_url))
    assert isinstance(adapter, LightdashExecution)
    assert adapter.supports_authoring is True


# --- execute -------------------------------------------------------------------


def test_execute_submits_sql_and_returns_rows(lightdash_backend, monkeypatch):
    base_url, recorder = lightdash_backend
    monkeypatch.setenv("DI0_TEST_LIGHTDASH_TOKEN", "pat-secret")
    recorder.query_columns = [{"reference": "customer_id"}, {"reference": "current_arr"}]
    recorder.query_rows = [
        {"customer_id": 1, "current_arr": 1200},
        {"customer_id": 2, "current_arr": 3400},
    ]

    result = build_engine(_profile(base_url)).query(CUSTOMERS_SQL)

    assert result.columns == ("customer_id", "current_arr")
    assert result.rows == ((1, 1200), (2, 3400))
    # the SQL reached the v2 SQL-runner query path, and the PAT rode as `ApiKey <token>`
    assert recorder.queries and recorder.queries[0]["sql"]
    assert recorder.auth_header == "ApiKey pat-secret"


# --- authoring: space + charts + dashboard -------------------------------------


_SPEC = """\
name: Revenue Overview
collection: Revenue
tabs:
  - name: Overview
    cards:
      - text: '# Revenue'
        display: heading
      - text: 'Weekly signups and revenue.'
      - title: Signups per week
        query: q.sql
        display: bar
        width: 6
        height: 4
"""


def _author(base_url: str, tmp_path: Path, spec_text: str, monkeypatch) -> object:
    monkeypatch.setenv("DI0_TEST_LIGHTDASH_TOKEN", "pat-secret")
    (tmp_path / "q.sql").write_text(CUSTOMERS_SQL)
    (tmp_path / "dash.yml").write_text(spec_text)
    return build_engine(_profile(base_url)).author(
        DashboardSpec.from_file(tmp_path / "dash.yml"), base_dir=tmp_path
    )


def test_author_creates_space_chart_and_dashboard(lightdash_backend, monkeypatch, tmp_path):
    base_url, recorder = lightdash_backend

    deliverable = _author(base_url, tmp_path, _SPEC, monkeypatch)

    # 1. the space is ensured from the spec `collection`
    assert recorder.created_spaces == [
        {"name": "Revenue", "parentSpaceUuid": None, "access": []}
    ]
    # 2. one saved SQL chart per query card, in the space, with the SQL and mapped viz
    assert len(recorder.charts) == 1
    chart = recorder.charts[0]
    assert chart["name"] == "Signups per week"
    assert chart["sql"] == CUSTOMERS_SQL
    assert chart["spaceUuid"] == "space-1"
    assert chart["slug"] == "signups-per-week"
    assert chart["config"]["type"] == "vertical_bar"  # display: bar -> vertical_bar

    # 3. a dashboard was created (not upserted) with native tabs and one tile per card
    assert recorder.dashboard is not None
    assert recorder.upserted_dashboard is None
    dash = recorder.dashboard
    assert dash["spaceUuid"] == "space-1"
    assert [tab["name"] for tab in dash["tabs"]] == ["Overview"]
    tab_uuid = dash["tabs"][0]["uuid"]
    assert all(tile["tabUuid"] == tab_uuid for tile in dash["tiles"])

    by_type = {tile["type"] for tile in dash["tiles"]}
    assert by_type == {"heading", "markdown", "sql_chart"}
    sql_tile = next(t for t in dash["tiles"] if t["type"] == "sql_chart")
    assert sql_tile["properties"]["savedSqlUuid"] == "chart-1"
    # logical width/height (6x4 on the 12-unit grid) scale x3 onto the 36-col grid
    assert sql_tile["w"] == 18
    assert sql_tile["h"] == 12

    assert deliverable.kind == "dashboard"
    assert deliverable.identifier == "dashboard-1"


def test_text_cards_become_markdown_and_heading_tiles(lightdash_backend, monkeypatch, tmp_path):
    base_url, recorder = lightdash_backend

    _author(base_url, tmp_path, _SPEC, monkeypatch)

    tiles = {tile["type"]: tile for tile in recorder.dashboard["tiles"]}
    assert tiles["heading"]["properties"]["text"] == "# Revenue"
    assert tiles["markdown"]["properties"]["content"] == "Weekly signups and revenue."
    assert "title" in tiles["markdown"]["properties"]


_REPLACE_SPEC = """\
name: Revenue Overview
collection: Revenue
replace: true
tabs:
  - name: Overview
    cards:
      - title: Signups per week
        query: q.sql
        display: line
"""


def test_replace_uses_the_as_code_slug_upsert(lightdash_backend, monkeypatch, tmp_path):
    base_url, recorder = lightdash_backend

    deliverable = _author(base_url, tmp_path, _REPLACE_SPEC, monkeypatch)

    # replace routes through the content-as-code slug upsert (stable URL), never create
    assert recorder.dashboard is None
    assert recorder.upserted_dashboard is not None
    assert recorder.upsert_path.endswith("/code/dashboards/revenue-overview")
    assert recorder.upserted_dashboard["spaceSlug"]  # references the space by slug
    assert deliverable.detail["replaced"] is True


# --- refusal before any write --------------------------------------------------


_SCALAR_SPEC = """\
name: Scalars
collection: Revenue
tabs:
  - name: Main
    cards:
      - title: Total
        query: q.sql
        display: scalar
"""

_PARAMS_SPEC = """\
name: Filtered
collection: Revenue
parameters:
  - name: Region
    slug: region
    values: [emea, apac]
tabs:
  - name: Main
    cards:
      - title: Customers
        query: q.sql
        display: table
"""


@pytest.mark.parametrize("spec_text", [_SCALAR_SPEC, _PARAMS_SPEC])
def test_overreaching_spec_is_refused_with_zero_writes(
    lightdash_backend, monkeypatch, tmp_path, spec_text
):
    base_url, recorder = lightdash_backend
    monkeypatch.setenv("DI0_TEST_LIGHTDASH_TOKEN", "pat-secret")
    (tmp_path / "q.sql").write_text(CUSTOMERS_SQL)
    (tmp_path / "dash.yml").write_text(spec_text)

    with pytest.raises(CapabilityError):
        build_engine(_profile(base_url)).author(
            DashboardSpec.from_file(tmp_path / "dash.yml"), base_dir=tmp_path
        )

    # refused before creation: nothing was written to the fake backend
    assert recorder.created_spaces == []
    assert recorder.charts == []
    assert recorder.dashboard is None
    assert recorder.upserted_dashboard is None


def test_missing_space_is_refused(lightdash_backend, monkeypatch, tmp_path):
    base_url, recorder = lightdash_backend
    monkeypatch.setenv("DI0_TEST_LIGHTDASH_TOKEN", "pat-secret")
    (tmp_path / "q.sql").write_text(CUSTOMERS_SQL)
    (tmp_path / "dash.yml").write_text(
        "name: No space\ntabs:\n  - name: Main\n    cards:\n"
        "      - title: C\n        query: q.sql\n        display: table\n"
    )
    # a profile with no default space and a spec with no collection: refuse, no writes
    engine = build_engine(_profile(base_url, lightdash_space=None))

    with pytest.raises(ValueError, match="space"):
        engine.author(DashboardSpec.from_file(tmp_path / "dash.yml"), base_dir=tmp_path)
    assert recorder.charts == []
    assert recorder.dashboard is None
