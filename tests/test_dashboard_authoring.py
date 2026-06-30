"""Slice #4: author a multi-tab dashboard from validated queries.

A mocked Metabase records the cards, dashboard, and final layout PUT so we can
assert the artifact was assembled from the spec - and that an invalid query
prevents any card from being created.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from di0.core import Engine, ValidationFailed
from di0.deliverable import DashboardSpec
from di0.profile import Profile
from di0.registry import (
    build_dialect_port,
    build_execution_port,
    build_schema_port,
    build_validation_port,
)

FIXTURE_MANIFEST = str(Path(__file__).parent / "fixtures" / "manifest.json")


class _Recorder:
    def __init__(self) -> None:
        self.cards: list[dict] = []
        self.dashboard: dict | None = None
        self.layout: dict | None = None


def _make_server(recorder: _Recorder) -> HTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _read(self) -> dict:
            length = int(self.headers.get("Content-Length", 0))
            return json.loads(self.rfile.read(length))

        def _send(self, body: dict) -> None:
            payload = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_POST(self):  # noqa: N802
            body = self._read()
            if self.path == "/api/card":
                recorder.cards.append(body)
                self._send({"id": 900 + len(recorder.cards)})
            elif self.path == "/api/dashboard":
                recorder.dashboard = body
                self._send({"id": 42})
            else:
                self._send({})

        def do_PUT(self):  # noqa: N802
            recorder.layout = self._read()
            self._send({"id": 42})

    return HTTPServer(("127.0.0.1", 0), Handler)


@pytest.fixture
def metabase_server():
    recorder = _Recorder()
    server = _make_server(recorder)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield f"http://{host}:{port}", recorder
    finally:
        server.shutdown()
        thread.join()


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
    return Engine(
        schema_port=build_schema_port(profile),
        dialect_port=build_dialect_port(profile),
        validation_port=build_validation_port(profile),
        execution_port=build_execution_port(profile),
    )


def test_authors_multi_tab_dashboard(metabase_server, monkeypatch, tmp_path):
    base_url, recorder = metabase_server
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
    assert recorder.dashboard == {"name": "ARR Overview"}
    # two tabs declared, each with its card pinned to the right tab
    assert [tab["name"] for tab in recorder.layout["tabs"]] == ["Overview", "Trend"]
    tab_ids = {dc["dashboard_tab_id"] for dc in recorder.layout["dashcards"]}
    assert tab_ids == {-1, -2}


def test_invalid_query_blocks_all_card_creation(metabase_server, monkeypatch, tmp_path):
    base_url, recorder = metabase_server
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
