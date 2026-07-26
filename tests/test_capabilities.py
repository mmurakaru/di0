"""Slice #66: adapters declare their authoring surface; the core refuses first.

An execution adapter states, statically, what it can author (which displays, text
cards, parameters, grid width). Before authoring anything, the core checks a
resolved dashboard against that declaration and refuses - naming every unsupported
item - if the spec exceeds it, so no artifact is created against a target that
cannot render it. The check is generic: the core reads only the neutral
Capabilities, never a backend name.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from di0 import cliio
from di0.adapters.metabase_execution import MetabaseExecution
from di0.core import CapabilityError, Engine
from di0.deliverable import DashboardSpec
from di0.ports import (
    DEFAULT_CAPABILITIES,
    Capabilities,
    Deliverable,
    QueryResult,
    ValidationResult,
)

FIXTURE_MANIFEST = str(Path(__file__).parent / "fixtures" / "manifest.json")


# --- synthetic ports: an execution adapter with a restricted authoring surface --


class _FakeSchema:
    def resolve(self) -> dict:
        return {}


class _FakeDialect:
    def compose(self, sql: str) -> str:
        return sql


class _FakeValidation:
    def validate(self, sql: str, schema: dict) -> ValidationResult:  # noqa: ARG002
        return ValidationResult(ok=True)


class _RestrictiveExecution:
    """Authors, but only bar/table displays, no text cards, no parameters."""

    def __init__(self) -> None:
        self.writes: list[object] = []

    def execute(self, sql: str) -> QueryResult:  # noqa: ARG002 - port signature
        return QueryResult()

    @property
    def supports_authoring(self) -> bool:
        return True

    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(
            authors=True,
            displays=frozenset({"bar", "table"}),
            text_cards=False,
            parameters=False,
        )

    def author(self, dashboard: object) -> Deliverable:
        self.writes.append(dashboard)  # any call here means a create leaked through
        return Deliverable(kind="dashboard", identifier="leaked")


def _restrictive_engine(execution: _RestrictiveExecution) -> Engine:
    return Engine(
        schema_port=_FakeSchema(),
        dialect_port=_FakeDialect(),
        validation_port=_FakeValidation(),
        execution_port=execution,
    )


# --- the Capabilities structure ------------------------------------------------


def test_default_capabilities_are_permissive():
    # A third-party adapter that does not override capabilities must keep working:
    # any display, text cards, and parameters are all accepted by default.
    assert DEFAULT_CAPABILITIES.displays is None
    assert DEFAULT_CAPABILITIES.text_cards is True
    assert DEFAULT_CAPABILITIES.parameters is True


def test_capabilities_is_frozen():
    caps = Capabilities(authors=True)
    with pytest.raises(Exception):  # noqa: B017 - frozen dataclass assignment
        caps.authors = False  # type: ignore[misc]


def test_metabase_declares_a_covering_descriptor():
    caps = MetabaseExecution("http://x", 7).capabilities
    assert caps.authors is True
    assert caps.displays is None  # accepts any native display string
    assert caps.text_cards is True
    assert caps.parameters is True
    assert caps.grid_columns == 24


# --- the metabase descriptor never refuses a working spec ----------------------


_FULL_FEATURE_SPEC = """\
name: Everything
collection_id: 42
parameters:
  - name: Region
    slug: region
    values: [emea, apac]
tabs:
  - name: Main
    cards:
      - text: '# Heading'
        display: heading
      - text: 'Body copy.'
        display: text
      - title: Bars
        query: q.sql
        display: bar
      - title: Lines
        query: q.sql
        display: line
      - title: Pies
        query: q.sql
        display: pie
      - title: Rows
        query: q.sql
        display: row
      - title: Funnels
        query: q.sql
        display: funnel
      - title: Tables
        query: q.sql
        display: table
"""


def _metabase_profile(base_url: str):
    from di0.profile import Profile

    return Profile(
        "dbt-manifest", "snowflake", "sqlglot-offline", "metabase",
        {
            "manifest_path": FIXTURE_MANIFEST,
            "metabase_url": base_url,
            "metabase_database_id": 7,
            "metabase_api_key_env": "DI0_TEST_METABASE_KEY",
        },
    )


def test_full_feature_spec_passes_capability_check_and_authors(
    metabase_authoring, monkeypatch, tmp_path
):
    from di0.registry import build_engine

    base_url, recorder = metabase_authoring
    monkeypatch.setenv("DI0_TEST_METABASE_KEY", "secret-token")
    (tmp_path / "q.sql").write_text("SELECT customer_id FROM analytics.dim_customers")
    (tmp_path / "dash.yml").write_text(_FULL_FEATURE_SPEC)

    deliverable = build_engine(_metabase_profile(base_url)).author(
        DashboardSpec.from_file(tmp_path / "dash.yml"), base_dir=tmp_path
    )

    # The permissive descriptor is a no-op for this spec: it authors unchanged.
    assert deliverable.kind == "dashboard"
    assert {c["display"] for c in recorder.cards} == {
        "bar", "line", "pie", "row", "funnel", "table"
    }
    assert len(recorder.cards) == 6  # six query cards; two text cards are virtual


# --- the core refuses before creating anything ---------------------------------


_OVERREACH_SPEC = """\
name: Overreach
collection_id: 42
parameters:
  - name: Region
    slug: region
    values: [emea]
tabs:
  - name: Main
    cards:
      - text: '# Intro'
        display: heading
      - title: Trend
        query: q.sql
        display: line
      - title: Share
        query: q.sql
        display: pie
      - title: Census
        query: q.sql
        display: table
"""


def test_restrictive_adapter_refuses_before_any_create(tmp_path):
    (tmp_path / "q.sql").write_text("SELECT 1")
    (tmp_path / "dash.yml").write_text(_OVERREACH_SPEC)
    execution = _RestrictiveExecution()
    engine = _restrictive_engine(execution)

    with pytest.raises(CapabilityError) as caught:
        engine.author(DashboardSpec.from_file(tmp_path / "dash.yml"), base_dir=tmp_path)

    message = str(caught.value)
    # Every offending item is named: the two unsupported displays, the text card,
    # and the dashboard parameters.
    assert "Trend" in message and "line" in message
    assert "Share" in message and "pie" in message
    assert "Intro" in message or "text" in message.lower()
    assert "parameter" in message.lower()
    # Supported cards are not flagged.
    assert "Census" not in message
    # Nothing was created: the refusal happened before any author() write.
    assert execution.writes == []


def test_capability_error_exposes_unsupported_items(tmp_path):
    (tmp_path / "q.sql").write_text("SELECT 1")
    (tmp_path / "dash.yml").write_text(_OVERREACH_SPEC)
    execution = _RestrictiveExecution()

    with pytest.raises(CapabilityError) as caught:
        _restrictive_engine(execution).author(
            DashboardSpec.from_file(tmp_path / "dash.yml"), base_dir=tmp_path
        )

    # The structured list is available for a machine to enumerate, not just prose.
    assert len(caught.value.unsupported) == 4


def test_no_capability_error_when_spec_stays_within_surface(tmp_path):
    (tmp_path / "q.sql").write_text("SELECT 1")
    (tmp_path / "dash.yml").write_text(
        "name: Within\n"
        "tabs:\n"
        "  - name: Main\n"
        "    cards:\n"
        "      - title: Bars\n"
        "        query: q.sql\n"
        "        display: bar\n"
        "      - title: Grid\n"
        "        query: q.sql\n"
        "        display: table\n"
    )
    execution = _RestrictiveExecution()

    deliverable = _restrictive_engine(execution).author(
        DashboardSpec.from_file(tmp_path / "dash.yml"), base_dir=tmp_path
    )

    # Within the surface: the adapter authored, so its author() ran exactly once.
    assert deliverable.identifier == "leaked"
    assert len(execution.writes) == 1


# --- row-only adapters still refuse via the existing path ----------------------


def test_row_only_adapter_refuses_before_capability_check(tmp_path):
    from di0.adapters.noop_execution import NoopExecution
    from di0.core import AuthoringUnsupported

    (tmp_path / "q.sql").write_text("SELECT 1")
    (tmp_path / "dash.yml").write_text(
        "name: D\ntabs:\n  - name: T\n    cards:\n      - title: c\n        query: q.sql\n"
    )
    engine = Engine(
        schema_port=_FakeSchema(),
        dialect_port=_FakeDialect(),
        validation_port=_FakeValidation(),
        execution_port=NoopExecution(),
    )
    # A row-only adapter is refused by supports_authoring, not the capability check.
    with pytest.raises(AuthoringUnsupported):
        engine.author(DashboardSpec.from_file(tmp_path / "dash.yml"), base_dir=tmp_path)


# --- cliio classification ------------------------------------------------------


def test_capability_error_maps_to_501_and_ex_unavailable():
    failure = cliio.classify(CapabilityError(("card 'Trend': display 'line' unsupported",)))
    assert failure.exit_code == cliio.EX_UNAVAILABLE == 69
    assert failure.error["code"] == cliio.HTTP_NOT_IMPLEMENTED == 501
    assert "line" in failure.error["message"]
