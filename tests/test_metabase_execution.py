"""Slice #2: execute validated SQL through a mocked Metabase dataset API.

A local HTTP server stands in for Metabase so the test runs offline. It records
the request it received so we can assert the adapter speaks the dataset API and
sends the API key from the environment.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from di0.core import Engine, ValidationFailed
from di0.profile import Profile
from di0.registry import (
    build_dialect_port,
    build_execution_port,
    build_schema_port,
    build_validation_port,
)

FIXTURE_MANIFEST = str(Path(__file__).parent / "fixtures" / "manifest.json")

CANNED_RESPONSE = {
    "data": {
        "cols": [{"name": "customer_id"}, {"name": "total_arr"}],
        "rows": [[1, 1200], [2, 3400]],
    }
}


class _Recorder:
    request_body: dict | None = None
    request_headers: dict | None = None


def _make_server(recorder: _Recorder) -> HTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # noqa: A002 - silence test server logging
            pass

        def do_POST(self):  # noqa: N802 - http.server API
            length = int(self.headers.get("Content-Length", 0))
            recorder.request_body = json.loads(self.rfile.read(length))
            recorder.request_headers = self.headers  # case-insensitive HTTPMessage
            payload = json.dumps(CANNED_RESPONSE).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

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


def test_validated_query_returns_rows(metabase_server, monkeypatch):
    base_url, recorder = metabase_server
    monkeypatch.setenv("DI0_TEST_METABASE_KEY", "secret-token")
    sql = (
        "SELECT c.customer_id, SUM(r.arr) AS total_arr "
        "FROM analytics.dim_customers c "
        "JOIN analytics.fct_subscription_revenue r ON r.customer_id = c.customer_id "
        "GROUP BY c.customer_id"
    )

    result = _engine(base_url).query(sql)

    assert result.columns == ("customer_id", "total_arr")
    assert result.rows == ((1, 1200), (2, 3400))
    assert recorder.request_body["type"] == "native"
    assert recorder.request_body["database"] == 7
    assert recorder.request_headers.get("x-api-key") == "secret-token"


def test_invalid_sql_is_refused_before_execution(metabase_server, monkeypatch):
    base_url, recorder = metabase_server
    monkeypatch.setenv("DI0_TEST_METABASE_KEY", "secret-token")

    with pytest.raises(ValidationFailed):
        _engine(base_url).query("SELECT churn_risk FROM analytics.dim_customers")

    assert recorder.request_body is None  # never reached the warehouse
