"""ExecutionPort adapter: run validated SQL through Metabase's dataset API, and
optionally author cards and multi-tab dashboards.

`execute` returns rows and is the portable capability. `author` creates BI
artifacts and is the optional, Metabase-specific capability.

The API key is never stored in the profile - it is read from an environment
variable named by the profile (default `DI0_METABASE_API_KEY`).
"""

from __future__ import annotations

import json
import os
import urllib.request

from di0.deliverable import ResolvedDashboard
from di0.ports import Deliverable, QueryResult

DEFAULT_API_KEY_ENV = "DI0_METABASE_API_KEY"


class MetabaseExecution:
    def __init__(
        self,
        base_url: str,
        database_id: int,
        api_key_env: str = DEFAULT_API_KEY_ENV,
        timeout: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._database_id = database_id
        self._api_key_env = api_key_env
        self._timeout = timeout

    def execute(self, sql: str) -> QueryResult:
        body = self._request(
            "POST",
            "/api/dataset",
            {"database": self._database_id, "type": "native", "native": {"query": sql}},
        )
        return self._to_result(body)

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
        request = urllib.request.Request(
            f"{self._base_url}{path}",
            data=json.dumps(payload).encode(),
            method=method,
            headers={"Content-Type": "application/json", "x-api-key": self._api_key()},
        )
        with urllib.request.urlopen(request, timeout=self._timeout) as response:
            return json.loads(response.read())

    def _api_key(self) -> str:
        key = os.environ.get(self._api_key_env)
        if not key:
            raise RuntimeError(
                f"Metabase API key not found in environment variable {self._api_key_env}"
            )
        return key

    @staticmethod
    def _to_result(body: dict) -> QueryResult:
        data = body.get("data", {})
        columns = tuple(col.get("name", "") for col in data.get("cols", []))
        rows = tuple(tuple(row) for row in data.get("rows", []))
        return QueryResult(columns=columns, rows=rows)
