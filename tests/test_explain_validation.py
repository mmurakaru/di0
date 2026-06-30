"""Slice #7: live-schema validation via EXPLAIN, selected by the profile.

A mocked warehouse resolves `EXPLAIN <query>`: unknown columns fail as the
warehouse would, valid queries return a plan. The EXPLAIN tier and the offline
tier satisfy the same ValidationPort, so the profile picks the trade-off.
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


class _Recorder:
    last_query: str | None = None


def _make_server(recorder: _Recorder) -> HTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            query = body["native"]["query"]
            recorder.last_query = query
            if "churn_risk" in query.lower():
                payload = {
                    "status": "failed",
                    "error": {"message": "SQL compilation error: invalid identifier 'CHURN_RISK'"},
                }
            else:
                payload = {"data": {"cols": [{"name": "Query Plan"}], "rows": [["GroupBy"]]}}
            encoded = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    return HTTPServer(("127.0.0.1", 0), Handler)


@pytest.fixture
def warehouse():
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
        validation="explain",
        execution="metabase",
        options={
            "manifest_path": FIXTURE_MANIFEST,
            "metabase_url": base_url,
            "metabase_database_id": 7,
            "metabase_api_key_env": "DI0_TEST_METABASE_KEY",
        },
    )
    execution_port = build_execution_port(profile)
    return Engine(
        schema_port=build_schema_port(profile),
        dialect_port=build_dialect_port(profile),
        validation_port=build_validation_port(profile, execution_port),
        execution_port=execution_port,
    )


def test_explain_passes_valid_query(warehouse, monkeypatch):
    base_url, recorder = warehouse
    monkeypatch.setenv("DI0_TEST_METABASE_KEY", "secret-token")

    result = _engine(base_url).validate("SELECT customer_id FROM analytics.dim_customers")

    assert result.ok
    assert recorder.last_query.startswith("EXPLAIN ")  # checked live, via EXPLAIN


def test_explain_fails_unknown_column(warehouse, monkeypatch):
    base_url, _ = warehouse
    monkeypatch.setenv("DI0_TEST_METABASE_KEY", "secret-token")

    result = _engine(base_url).validate("SELECT churn_risk FROM analytics.dim_customers")

    assert not result.ok
    assert "invalid identifier" in result.errors[0]


def test_explain_tier_gates_execution(warehouse, monkeypatch):
    base_url, _ = warehouse
    monkeypatch.setenv("DI0_TEST_METABASE_KEY", "secret-token")

    with pytest.raises(ValidationFailed):
        _engine(base_url).query("SELECT churn_risk FROM analytics.dim_customers")


def test_explain_requires_native_capable_execution():
    profile = Profile(
        schema_source="dbt-manifest",
        dialect="snowflake",
        validation="explain",
        execution="noop",
        options={"manifest_path": FIXTURE_MANIFEST},
    )
    with pytest.raises(ValueError, match="explain validation requires"):
        build_validation_port(profile, build_execution_port(profile))
