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
