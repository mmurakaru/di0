"""ExecutionPort adapter: run validated SQL through Metabase's dataset API, and
optionally author cards and multi-tab dashboards.

`execute` returns rows and is the portable capability. `author` creates BI
artifacts and is the optional, Metabase-specific capability.

Metabase documents two auth schemes; both are supported and selected by the
profile (`auth`):

- `api-key` (default, recommended): the `x-api-key` header.
- `session`: the `X-Metabase-Session` header, for deployments without API keys.

Either way the credential is read from an environment variable named by the
profile, never stored in the profile.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from di0.deliverable import ResolvedDashboard
from di0.ports import Deliverable, QueryResult

DEFAULT_API_KEY_ENV = "DI0_METABASE_API_KEY"
DEFAULT_SESSION_ENV = "DI0_METABASE_SESSION"


class MetabaseExecution:
    def __init__(
        self,
        base_url: str,
        database_id: int,
        auth: str = "api-key",
        api_key_env: str = DEFAULT_API_KEY_ENV,
        session_env: str = DEFAULT_SESSION_ENV,
        timeout: float = 30.0,
    ) -> None:
        if auth not in ("api-key", "session"):
            raise ValueError(f"unknown metabase auth: {auth!r} (use 'api-key' or 'session')")
        self._base_url = base_url.rstrip("/")
        self._database_id = database_id
        self._auth = auth
        self._api_key_env = api_key_env
        self._session_env = session_env
        self._timeout = timeout

    def execute(self, sql: str) -> QueryResult:
        body = self._request(
            "POST",
            "/api/dataset",
            {"database": self._database_id, "type": "native", "native": {"query": sql}},
        )
        return self._to_result(body)

    def run_native(self, sql: str) -> tuple[bool, str | None]:
        """Run a native statement, reporting success or the warehouse error.

        Used by the EXPLAIN validation tier. A failed query surfaces as an error
        field or a failed status in the dataset response (or an HTTP error body).
        """
        payload = {"database": self._database_id, "type": "native", "native": {"query": sql}}
        try:
            body = self._request("POST", "/api/dataset", payload)
        except urllib.error.HTTPError as error:
            return False, self._error_text(json.loads(error.read() or b"{}"))
        if body.get("status") == "failed" or body.get("error"):
            return False, self._error_text(body)
        return True, None

    @property
    def supports_authoring(self) -> bool:
        return True

    def author(self, dashboard: ResolvedDashboard) -> Deliverable:
        tabs: list[dict] = []
        dashcards: list[dict] = []
        card_ids: list[int] = []
        for tab_index, tab in enumerate(dashboard.tabs):
            tab_id = -(tab_index + 1)
            tabs.append({"id": tab_id, "name": tab.name})
            row = 0
            for card in tab.cards:
                card_id = self._create_card(card.title, card.sql, card.display)
                card_ids.append(card_id)
                dashcards.append(
                    {
                        "id": -(len(dashcards) + 1),
                        "card_id": card_id,
                        "dashboard_tab_id": tab_id,
                        "row": row,
                        "col": 0,
                        "size_x": card.size_x,
                        "size_y": card.size_y,
                    }
                )
                row += card.size_y

        created = self._request("POST", "/api/dashboard", {"name": dashboard.name})
        dashboard_id = created["id"]
        self._request(
            "PUT",
            f"/api/dashboard/{dashboard_id}",
            {"tabs": tabs, "dashcards": dashcards},
        )
        return Deliverable(
            kind="dashboard",
            identifier=str(dashboard_id),
            detail={
                "url": f"{self._base_url}/dashboard/{dashboard_id}",
                "card_ids": card_ids,
                "tabs": [tab.name for tab in dashboard.tabs],
            },
        )

    def _create_card(self, name: str, sql: str, display: str) -> int:
        body = self._request(
            "POST",
            "/api/card",
            {
                "name": name,
                "display": display,
                "visualization_settings": {},
                "dataset_query": {
                    "database": self._database_id,
                    "type": "native",
                    "native": {"query": sql},
                },
            },
        )
        return body["id"]

    def _request(self, method: str, path: str, payload: dict) -> dict:
        headers = {"Content-Type": "application/json", **self._auth_header()}
        request = urllib.request.Request(
            f"{self._base_url}{path}",
            data=json.dumps(payload).encode(),
            method=method,
            headers=headers,
        )
        with urllib.request.urlopen(request, timeout=self._timeout) as response:
            return json.loads(response.read())

    def _auth_header(self) -> dict[str, str]:
        if self._auth == "session":
            return {"X-Metabase-Session": self._credential(self._session_env)}
        return {"x-api-key": self._credential(self._api_key_env)}

    def _credential(self, env_var: str) -> str:
        value = os.environ.get(env_var)
        if not value:
            raise RuntimeError(f"Metabase credential not found in environment variable {env_var}")
        return value

    @staticmethod
    def _error_text(body: dict) -> str:
        error = body.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or error)
        return str(error or body.get("status") or "query failed")

    @staticmethod
    def _to_result(body: dict) -> QueryResult:
        data = body.get("data", {})
        columns = tuple(col.get("name", "") for col in data.get("cols", []))
        rows = tuple(tuple(row) for row in data.get("rows", []))
        return QueryResult(columns=columns, rows=rows)
