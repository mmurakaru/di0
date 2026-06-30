"""ExecutionPort adapter: a no-op execution target.

Used when di0 should resolve, compose, and validate but not run anything - the
default for offline build-time checking. It returns no rows and cannot author.
"""

from __future__ import annotations

from di0.ports import QueryResult


class NoopExecution:
    def execute(self, sql: str) -> QueryResult:  # noqa: ARG002 - port signature
        return QueryResult()

    @property
    def supports_authoring(self) -> bool:
        return False
