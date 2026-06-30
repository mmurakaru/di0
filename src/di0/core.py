"""The validation loop - di0's actual IP.

resolve refs (SchemaPort) -> compose SQL (DialectPort) -> validate against the
schema (ValidationPort) -> only then execute (ExecutionPort).

The loop is warehouse-blind: it holds ports, never adapters, and never a single
physical table, column, or dialect literal.
"""

from __future__ import annotations

from dataclasses import dataclass

from di0.ports import (
    DialectPort,
    ExecutionPort,
    QueryResult,
    SchemaPort,
    ValidationPort,
    ValidationResult,
)


class ValidationFailed(Exception):
    def __init__(self, result: ValidationResult) -> None:
        super().__init__("; ".join(result.errors) or "validation failed")
        self.result = result


@dataclass(frozen=True)
class Engine:
    schema_port: SchemaPort
    dialect_port: DialectPort
    validation_port: ValidationPort
    execution_port: ExecutionPort

    def validate(self, sql: str) -> ValidationResult:
        composed = self.dialect_port.compose(sql)
        schema = self.schema_port.resolve()
        return self.validation_port.validate(composed, schema)

    def query(self, sql: str) -> QueryResult:
        result = self.validate(sql)
        if not result.ok:
            raise ValidationFailed(result)
        composed = self.dialect_port.compose(sql)
        return self.execution_port.execute(composed)
