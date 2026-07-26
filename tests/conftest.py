"""Shared test fixtures: HTTP server lifecycle and a fake Metabase authoring backend.

Every Engine in these tests is built the same way `di0.registry.build_engine`
already builds one in production - tests should call that directly rather than
re-deriving it. What genuinely needed sharing was the HTTP plumbing: four test
files each hand-rolled their own HTTPServer + thread lifecycle, and two of them
(test_dashboard_authoring.py, test_authoring_extras.py) duplicated ~90 lines of
near-identical request handling for the same fake Metabase authoring surface.
Both live here once.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest


@pytest.fixture(autouse=True)
def isolate_audit_ledger(tmp_path_factory, monkeypatch):
    """Keep the on-by-default provenance ledger out of the repo during tests.

    `build_engine` attaches a real ledger writing under `<DI0_WORKSPACE or cwd>`;
    point that at a throwaway temp dir so tests never write into the working tree.
    Tests that assert on the ledger location set `DI0_WORKSPACE` themselves, which
    overrides this default.
    """
    monkeypatch.setenv("DI0_WORKSPACE", str(tmp_path_factory.mktemp("di0-workspace")))


@pytest.fixture
def start_http_server():
    """Factory fixture: start_http_server(handler_cls) -> base_url.

    Starts an HTTPServer on a background thread; shuts it down automatically
    when the test ends.
    """
    started: list[tuple[HTTPServer, threading.Thread]] = []

    def _start(handler_cls: type[BaseHTTPRequestHandler]) -> str:
        server = HTTPServer(("127.0.0.1", 0), handler_cls)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        started.append((server, thread))
        host, port = server.server_address
        return f"http://{host}:{port}"

    yield _start
    for server, thread in started:
        server.shutdown()
        thread.join()


@dataclass
class AuthoringRecorder:
    """Records requests against the fake Metabase authoring backend below.

    Some fields are outputs (populated as requests arrive); `collections`,
    `collection_items`, and `existing_dashboard` are inputs a test seeds before
    calling `author()`, to control what the fake GET endpoints return.
    """

    cards: list[dict] = field(default_factory=list)
    dashboard: dict | None = None
    created_collections: list[dict] = field(default_factory=list)
    collections: list[dict] = field(default_factory=list)
    layout: dict | None = None
    layout_path: str | None = None
    updated_cards: list[tuple[str, dict]] = field(default_factory=list)
    collection_items: list[dict] = field(default_factory=list)
    existing_dashboard: dict = field(default_factory=dict)
    archived: list[tuple[str, dict]] = field(default_factory=list)


def metabase_authoring_handler(recorder: AuthoringRecorder) -> type[BaseHTTPRequestHandler]:
    """A fake Metabase backend covering card/dashboard/collection authoring.

    Shared by every test that exercises `MetabaseExecution.author()`.
    """

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: object) -> None:  # noqa: ARG002 - silence test server logging
            pass

        def _body(self) -> dict:
            length = int(self.headers.get("Content-Length", 0))
            return json.loads(self.rfile.read(length) or b"{}")

        def _send(self, obj: object) -> None:
            payload = json.dumps(obj).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self) -> None:  # noqa: N802 - http.server API
            if "/items" in self.path:
                self._send(recorder.collection_items)
            elif self.path.startswith("/api/dashboard/"):
                self._send(recorder.existing_dashboard)
            elif self.path == "/api/collection":
                self._send(recorder.collections)
            else:
                self._send([])

        def do_POST(self) -> None:  # noqa: N802 - http.server API
            body = self._body()
            if self.path == "/api/card":
                recorder.cards.append(body)
                self._send({"id": 900 + len(recorder.cards)})
            elif self.path == "/api/dashboard":
                recorder.dashboard = body
                self._send({"id": 42})
            elif self.path == "/api/collection":
                recorder.created_collections.append(body)
                self._send({"id": 700 + len(recorder.created_collections)})
            else:
                self._send({})

        def do_PUT(self) -> None:  # noqa: N802 - http.server API
            body = self._body()
            if "archived" in body:
                recorder.archived.append((self.path, body))
                self._send({"id": 0})
            elif self.path.startswith("/api/card/"):
                card_id = int(self.path.rsplit("/", 1)[-1])
                recorder.updated_cards.append((self.path, body))
                self._send({"id": card_id})  # in-place update keeps the card id
            else:
                recorder.layout = body
                recorder.layout_path = self.path
                self._send({"id": 42})

    return Handler


@pytest.fixture
def metabase_authoring(start_http_server):
    """A running fake Metabase authoring backend: yields (base_url, recorder)."""
    recorder = AuthoringRecorder()
    base_url = start_http_server(metabase_authoring_handler(recorder))
    return base_url, recorder


def _slug(text: str) -> str:
    """A crude slug, matching how the adapter slugifies names, for fake responses."""
    import re

    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "untitled"


@dataclass
class LightdashRecorder:
    """Records requests against the fake Lightdash backend below.

    Outputs are populated as requests arrive; `spaces`, `query_columns`, and
    `query_rows` are inputs a test seeds before calling `execute`/`author`, to
    control what the fake GET/query endpoints return.
    """

    charts: list[dict] = field(default_factory=list)
    created_spaces: list[dict] = field(default_factory=list)
    spaces: list[dict] = field(default_factory=list)
    dashboard: dict | None = None
    dashboard_path: str | None = None
    upserted_dashboard: dict | None = None
    upsert_path: str | None = None
    queries: list[dict] = field(default_factory=list)
    query_columns: list = field(default_factory=list)
    query_rows: list = field(default_factory=list)
    auth_header: str | None = None


def lightdash_handler(recorder: LightdashRecorder) -> type[BaseHTTPRequestHandler]:
    """A fake Lightdash backend covering the SQL-runner query and authoring surfaces.

    Every response follows Lightdash's `{ "results": ... }` envelope. Shared by
    every test that exercises `LightdashExecution`.
    """

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: object) -> None:  # noqa: ARG002 - silence test server logging
            pass

        def _body(self) -> dict:
            length = int(self.headers.get("Content-Length", 0))
            return json.loads(self.rfile.read(length) or b"{}")

        def _send(self, results: object) -> None:
            payload = json.dumps({"status": "ok", "results": results}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self) -> None:  # noqa: N802 - http.server API
            recorder.auth_header = self.headers.get("Authorization")
            if "/query/" in self.path:  # fetch SQL results (already "ready")
                self._send(
                    {
                        "status": "ready",
                        "columns": recorder.query_columns,
                        "rows": recorder.query_rows,
                    }
                )
            elif self.path.endswith("/spaces"):
                self._send(recorder.spaces)
            else:
                self._send([])

        def do_POST(self) -> None:  # noqa: N802 - http.server API
            recorder.auth_header = self.headers.get("Authorization")
            body = self._body()
            if self.path.endswith("/query/sql"):
                recorder.queries.append(body)
                self._send({"queryUuid": "query-1"})
            elif self.path.endswith("/sqlRunner/saved"):
                recorder.charts.append(body)
                number = len(recorder.charts)
                self._send({"savedSqlUuid": f"chart-{number}", "slug": body.get("slug")})
            elif self.path.endswith("/spaces"):
                recorder.created_spaces.append(body)
                name = body.get("name", "")
                number = len(recorder.created_spaces)
                self._send({"uuid": f"space-{number}", "slug": _slug(name), "name": name})
            elif "/code/dashboards/" in self.path:  # as-code slug upsert
                recorder.upserted_dashboard = body
                recorder.upsert_path = self.path
                self._send({"slug": self.path.rsplit("/", 1)[-1]})
            elif self.path.endswith("/dashboards"):
                recorder.dashboard = body
                recorder.dashboard_path = self.path
                self._send({"uuid": "dashboard-1", "slug": _slug(body.get("name", ""))})
            else:
                self._send({})

    return Handler


@pytest.fixture
def lightdash_backend(start_http_server):
    """A running fake Lightdash backend: yields (base_url, recorder)."""
    recorder = LightdashRecorder()
    base_url = start_http_server(lightdash_handler(recorder))
    return base_url, recorder
