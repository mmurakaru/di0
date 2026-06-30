"""ExecutionPort adapter: run validated SQL through Metabase's dataset API.

Execution returns rows. Artifact authoring (cards, dashboards) is a separate,
optional capability added later; this adapter reports it does not author yet.

The API key is never stored in the profile - it is read from an environment
variable named by the profile (default `DI0_METABASE_API_KEY`).
"""

from __future__ import annotations

import json
import os
import urllib.request

from di0.ports import QueryResult

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
        payload = json.dumps(
            {
                "database": self._database_id,
                "type": "native",
                "native": {"query": sql},
            }
        ).encode()
        request = urllib.request.Request(
            f"{self._base_url}/api/dataset",
            data=payload,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "x-api-key": self._api_key(),
            },
        )
        with urllib.request.urlopen(request, timeout=self._timeout) as response:
            body = json.loads(response.read())
        return self._to_result(body)

    @property
    def supports_authoring(self) -> bool:
        return False

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
