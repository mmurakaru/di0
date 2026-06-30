"""ValidationPort adapter: prove a query against the live schema with EXPLAIN.

`EXPLAIN <query>` makes the warehouse parse and resolve every object and column
without executing the query - no compute cost - so an unknown table or column
errors here, before any card is created. This checks the *live* schema, so it
needs an execution connection rather than the offline manifest.

The query is run through any execution adapter that exposes `run_native`, so this
tier is not bound to a specific warehouse; the EXPLAIN keyword is accepted by
Snowflake, Postgres, and CockroachDB alike.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from di0.ports import Schema, ValidationResult


@runtime_checkable
class NativeRunner(Protocol):
    def run_native(self, sql: str) -> tuple[bool, str | None]:
        """Run a statement, returning (ok, error_message)."""
        ...


class ExplainValidation:
    def __init__(self, runner: NativeRunner) -> None:
        self._runner = runner

    def validate(self, sql: str, schema: Schema) -> ValidationResult:
        # The live schema is the source of truth here, so `schema` is unused.
        ok, error = self._runner.run_native(f"EXPLAIN {sql}")
        if ok:
            return ValidationResult(ok=True)
        return ValidationResult(ok=False, errors=(error or "EXPLAIN failed",))
