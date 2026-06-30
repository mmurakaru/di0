"""Authoring extras: collection placement, card annotations, axis labels.

These let a dashboard land in a specific collection (not the shared root) with
annotated cards and readable axes - all driven by the spec, asserted against a
mocked Metabase that records the payloads it receives.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from di0.core import Engine
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
        self.created_collections: list[dict] = []
        self.collections: list[dict] = []  # what GET /api/collection returns


def _make_server(recorder: _Recorder) -> HTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _body(self) -> dict:
            return json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")

        def _send(self, obj) -> None:
            payload = json.dumps(obj).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):  # noqa: N802
            if self.path == "/api/collection":
                self._send(recorder.collections)
            else:
                self._send([])

        def do_POST(self):  # noqa: N802
            body = self._body()
            if self.path == "/api/card":
                recorder.cards.append(body)
                self._send({"id": 900 + len(recorder.cards)})
            elif self.path == "/api/dashboard":
                recorder.dashboard = body
                self._send({"id": 42})
            elif self.path == "/api/collection":
                recorder.created_collections.append(body)
                self._send({"id": 777})
            else:
                self._send({})

        def do_PUT(self):  # noqa: N802
            self._body()
            self._send({"id": 42})

    return HTTPServer(("127.0.0.1", 0), Handler)


@pytest.fixture
def server():
    recorder = _Recorder()
    srv = _make_server(recorder)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    host, port = srv.server_address
    try:
        yield f"http://{host}:{port}", recorder
    finally:
        srv.shutdown()
        thread.join()


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
    profile = _profile(base_url)
    execution_port = build_execution_port(profile)
    return Engine(
        schema_port=build_schema_port(profile),
        dialect_port=build_dialect_port(profile),
        validation_port=build_validation_port(profile, execution_port),
        execution_port=execution_port,
    )


def test_author_places_in_collection_with_annotations_and_axes(server, monkeypatch, tmp_path):
    base_url, recorder = server
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


def test_ensure_collection_creates_under_parent(server, monkeypatch):
    base_url, recorder = server
    monkeypatch.setenv("DI0_TEST_SESSION", "sess")
    adapter = build_execution_port(_profile(base_url))

    new_id = adapter.ensure_collection("quarterly-reviews", parent_id=42)

    assert new_id == 777
    assert recorder.created_collections[0] == {"name": "quarterly-reviews", "parent_id": 42}


def test_ensure_collection_reuses_existing(server, monkeypatch):
    base_url, recorder = server
    monkeypatch.setenv("DI0_TEST_SESSION", "sess")
    recorder.collections = [
        {"id": 999, "name": "quarterly-reviews", "location": "/42/"},
        {"id": 111, "name": "quarterly-reviews", "location": "/9/"},  # different parent
    ]
    adapter = build_execution_port(_profile(base_url))

    found = adapter.ensure_collection("quarterly-reviews", parent_id=42)

    assert found == 999
    assert recorder.created_collections == []  # did not create a duplicate