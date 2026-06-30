"""ExecutionPort adapter: a row-only execution backend.

This proves the output platform is swappable. It implements only `execute` -
validated SQL in, rows out - and deliberately does not author deliverables, so
`supports_authoring` is False and a deliverable request is refused upstream. Pick
it with `execution: http-rows`; the same `di0 query` flow runs unchanged.

The API key is read from an environment variable named by the profile, never
stored in the profile.
"""

from __future__ import annotations

import json
import os
import urllib.request

from di0.ports import QueryResult

DEFAULT_API_KEY_ENV = "DI0_ROWS_API_KEY"


class HttpRowsExecution:
    def __init__(
        self,
        base_url: str,
        api_key_env: str = DEFAULT_API_KEY_ENV,
        timeout: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key_env = api_key_env
        self._timeout = timeout

    def execute(self, sql: str) -> QueryResult:
        request = urllib.request.Request(
            f"{self._base_url}/rows",
            data=json.dumps({"sql": sql}).encode(),
            method="POST",
            headers={"Content-Type": "application/json", "x-api-key": self._api_key()},
        )
        with urllib.request.urlopen(request, timeout=self._timeout) as response:
            body = json.loads(response.read())
        return QueryResult(
            columns=tuple(body.get("columns", [])),
            rows=tuple(tuple(row) for row in body.get("rows", [])),
        )

    @property
    def supports_authoring(self) -> bool:
        return False

    def _api_key(self) -> str:
        key = os.environ.get(self._api_key_env)
        if not key:
            raise RuntimeError(
                f"API key not found in environment variable {self._api_key_env}"
            )
        return key
