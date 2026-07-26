"""Slice #60: the adapter conformance kit, run against di0's own adapters.

`di0.testing.conformance` is a shared, reusable contract suite any adapter author
runs to prove an adapter satisfies a port - and the trust gate an agent-adapted
adapter re-passes. Here we point it at every in-tree adapter, over the existing
fixtures, so the kit is proven to pass on real adapters (and to catch a violation).
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler
from pathlib import Path

import pytest

from di0 import cli
from di0.adapters.dbt_manifest import DbtManifestSchema
from di0.adapters.duckdb_combine import DuckdbCombine
from di0.adapters.http_rows_execution import HttpRowsExecution
from di0.adapters.metabase_execution import MetabaseExecution
from di0.adapters.noop_execution import NoopExecution
from di0.adapters.sqlglot_dialect import SqlglotDialect
from di0.adapters.sqlglot_validation import SqlglotOfflineValidation
from di0.deliverable import DashboardSpec, ResolvedCard, ResolvedDashboard, ResolvedTab
from di0.ports import Capabilities, Deliverable, QueryResult
from di0.testing import conformance

FIXTURE_MANIFEST = str(Path(__file__).parent / "fixtures" / "manifest.json")
DIALECT = "snowflake"
NOOP_REFERENCE = "di0.adapters.noop_execution:NoopExecution"

VALID_SQL = "SELECT customer_id, current_arr FROM analytics.dim_customers"
INVALID_SQL = "SELECT nonexistent_column FROM analytics.dim_customers"
PARAMETERIZED_SQL = (
    "SELECT customer_id FROM analytics.dim_customers "
    "WHERE plan_name = {{plan}} [[ AND current_arr = {{arr}} ]]"
)


def _fixture_schema() -> dict:
    return DbtManifestSchema(FIXTURE_MANIFEST).resolve()


# --- di0's own adapters satisfy their ports ----------------------------------


def test_dbt_manifest_schema_conforms():
    conformance.check_schema_port(DbtManifestSchema(FIXTURE_MANIFEST))


def test_sqlglot_dialect_conforms():
    conformance.check_dialect_port(SqlglotDialect(DIALECT), VALID_SQL)


def test_sqlglot_validation_conforms():
    conformance.check_validation_port(
        SqlglotOfflineValidation(DIALECT),
        _fixture_schema(),
        valid_sql=VALID_SQL,
        invalid_sql=INVALID_SQL,
        parameterized_sql=PARAMETERIZED_SQL,
    )


def test_noop_execution_conforms():
    conformance.check_execution_port(NoopExecution(), valid_sql=VALID_SQL)


def _rows_handler() -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # noqa: ARG002 - silence test server logging
            pass

        def do_POST(self):  # noqa: N802 - http.server API
            length = int(self.headers.get("Content-Length", 0))
            self.rfile.read(length)
            payload = json.dumps({"columns": ["customer_id"], "rows": [[1], [2]]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    return Handler


def test_http_rows_execution_conforms(start_http_server, monkeypatch):
    monkeypatch.setenv("DI0_TEST_ROWS_KEY", "secret-token")
    base_url = start_http_server(_rows_handler())
    port = HttpRowsExecution(base_url, api_key_env="DI0_TEST_ROWS_KEY")
    conformance.check_execution_port(port, valid_sql=VALID_SQL)


def _resolved_dashboard() -> ResolvedDashboard:
    return ResolvedDashboard(
        name="Conformance",
        collection_id=42,
        tabs=(ResolvedTab(name="Main", cards=(ResolvedCard(title="Customers", sql=VALID_SQL),)),),
    )


def test_metabase_execution_authoring_conforms(metabase_authoring, monkeypatch):
    base_url, _ = metabase_authoring
    monkeypatch.setenv("DI0_TEST_METABASE_KEY", "secret-token")
    port = MetabaseExecution(base_url, 7, api_key_env="DI0_TEST_METABASE_KEY")
    deliverable = conformance.check_authoring(port, _resolved_dashboard())
    assert isinstance(deliverable, Deliverable)


def test_duckdb_combine_conforms():
    customers = QueryResult(columns=("customer_id", "plan"), rows=((1, "pro"), (2, "free")))
    revenue = QueryResult(columns=("customer_id", "arr"), rows=((1, 100), (2, 0)))
    result = conformance.check_combine_port(
        DuckdbCombine(),
        tables={"customers": customers, "revenue": revenue},
        sql=(
            "SELECT c.customer_id, c.plan, r.arr "
            "FROM customers c JOIN revenue r ON r.customer_id = c.customer_id"
        ),
    )
    assert set(result.columns) == {"customer_id", "plan", "arr"}


# --- the #66 trust gate: an over-reaching spec is refused before any side effect --


class _RestrictedAuthoring:
    """A third-party-style authoring adapter with a deliberately narrow surface."""

    def __init__(self) -> None:
        self.authored: list[object] = []

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
        self.authored.append(dashboard)  # any call here means a create leaked through
        return Deliverable(kind="dashboard", identifier="leaked")


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
      - title: Trend
        query: q.sql
        display: line
"""


def test_refuses_over_reaching_spec_before_side_effect(tmp_path):
    (tmp_path / "q.sql").write_text("SELECT 1")
    (tmp_path / "dash.yml").write_text(_OVERREACH_SPEC)
    port = _RestrictedAuthoring()
    conformance.check_refuses_before_side_effect(
        port,
        spec=DashboardSpec.from_file(tmp_path / "dash.yml"),
        base_dir=tmp_path,
    )
    assert port.authored == []


# --- the kit is a real gate: it catches a non-conforming adapter -----------------


class _BadSchema:
    def resolve(self) -> dict:
        return {"ns": {"t": {"c": 123}}}  # a column type must be a string, not an int


class _FlakySchema:
    def __init__(self) -> None:
        self._calls = 0

    def resolve(self) -> dict:
        self._calls += 1
        return {"ns": {"t": {"c": str(self._calls)}}}  # not idempotent


class _BrokenExecution:
    def execute(self, sql: str) -> object:  # noqa: ARG002 - port signature
        return "not a query result"

    @property
    def supports_authoring(self) -> bool:
        return False


def test_check_schema_port_rejects_non_string_types():
    with pytest.raises(AssertionError):
        conformance.check_schema_port(_BadSchema())


def test_check_schema_port_requires_idempotence():
    with pytest.raises(AssertionError):
        conformance.check_schema_port(_FlakySchema())


def test_run_cli_checks_flags_nonconforming_adapter():
    outcomes = conformance.run_cli_checks(_BrokenExecution(), sql="SELECT 1")
    assert any(outcome.port == "ExecutionPort" and not outcome.passed for outcome in outcomes)


def test_run_cli_checks_rejects_a_non_port_object():
    with pytest.raises(ValueError):
        conformance.run_cli_checks(object(), sql="SELECT 1")


# --- the CLI wrapper honours the #57 contract and exit codes ---------------------


def test_cli_conformance_passes_for_noop_json(capsys):
    code = cli.main(["conformance", "--adapter", NOOP_REFERENCE, "--json"])
    env = json.loads(capsys.readouterr().out)
    assert code == 0
    assert env["ok"] is True
    assert env["command"] == "conformance"
    assert any(check["port"] == "ExecutionPort" for check in env["data"]["checks"])
    assert all(check["passed"] for check in env["data"]["checks"])


def test_cli_conformance_text_mode(capsys):
    code = cli.main(["conformance", "--adapter", NOOP_REFERENCE])
    out = capsys.readouterr().out
    assert code == 0
    assert "PASS" in out
    assert "ExecutionPort" in out


def test_cli_conformance_reports_failure_for_unknown_adapter(capsys):
    code = cli.main(
        ["conformance", "--adapter", "di0.adapters.noop_execution:Missing", "--json"]
    )
    env = json.loads(capsys.readouterr().out)
    assert code != 0
    assert env["ok"] is False
