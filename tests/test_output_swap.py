"""Slice #10: the output platform is swappable, proven by a second adapter.

The same validated query runs through Metabase and through a row-only adapter and
returns identical rows - execute() is portable. The row-only adapter cannot
author, so a deliverable request is refused: author() is the optional capability.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from di0.core import AuthoringUnsupported, Engine
from di0.deliverable import DashboardSpec
from di0.profile import Profile
from di0.registry import (
    build_dialect_port,
    build_execution_port,
    build_schema_port,
    build_validation_port,
)

FIXTURE_MANIFEST = str(Path(__file__).parent / "fixtures" / "manifest.json")

# One logical result, served in each adapter's wire shape from the same source.
COLUMNS = ["customer_id", "total_arr"]
ROWS = [[1, 1200], [2, 3400]]


def _make_server() -> HTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):  # noqa: N802
            if self.path == "/api/dataset/csv":  # Metabase execute() -> CSV export
                lines = [",".join(COLUMNS)] + [",".join(str(v) for v in r) for r in ROWS]
                encoded = ("\n".join(lines) + "\n").encode()
                ctype = "text/csv"
            elif self.path == "/rows":  # http-rows shape
                encoded = json.dumps({"columns": COLUMNS, "rows": ROWS}).encode()
                ctype = "application/json"
            else:
                encoded = b"{}"
                ctype = "application/json"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    return HTTPServer(("127.0.0.1", 0), Handler)


@pytest.fixture
def server():
    srv = _make_server()
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    host, port = srv.server_address
    try:
        yield f"http://{host}:{port}"
    finally:
        srv.shutdown()
        thread.join()


def _engine(execution: str, base_url: str) -> Engine:
    options = {"manifest_path": FIXTURE_MANIFEST}
    if execution == "metabase":
        options |= {
            "metabase_url": base_url,
            "metabase_database_id": 7,
            "metabase_api_key_env": "DI0_TEST_KEY",
        }
    else:
        options |= {"rows_url": base_url, "rows_api_key_env": "DI0_TEST_KEY"}
    profile = Profile("dbt-manifest", "snowflake", "sqlglot-offline", execution, options)
    execution_port = build_execution_port(profile)
    return Engine(
        schema_port=build_schema_port(profile),
        dialect_port=build_dialect_port(profile),
        validation_port=build_validation_port(profile, execution_port),
        execution_port=execution_port,
    )


def test_same_query_identical_rows_across_adapters(server, monkeypatch):
    monkeypatch.setenv("DI0_TEST_KEY", "secret-token")
    sql = "SELECT customer_id, current_arr FROM analytics.dim_customers"

    via_metabase = _engine("metabase", server).query(sql)
    via_rows = _engine("http-rows", server).query(sql)

    assert via_metabase.columns == via_rows.columns == ("customer_id", "total_arr")
    assert via_metabase.rows == via_rows.rows == ((1, 1200), (2, 3400))


def test_row_only_adapter_refuses_authoring(server, monkeypatch, tmp_path):
    monkeypatch.setenv("DI0_TEST_KEY", "secret-token")
    (tmp_path / "q.sql").write_text("SELECT customer_id FROM analytics.dim_customers")
    spec_path = tmp_path / "dash.yml"
    spec_path.write_text(
        "name: D\ntabs:\n  - name: T\n    cards:\n      - title: c\n        query: q.sql\n"
    )

    engine = _engine("http-rows", server)
    assert engine.execution_port.supports_authoring is False
    with pytest.raises(AuthoringUnsupported):
        engine.author(DashboardSpec.from_file(spec_path), base_dir=tmp_path)
