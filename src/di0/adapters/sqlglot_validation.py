"""ValidationPort adapter: prove a query offline against the resolved schema.

This is the offline precompiler - it qualifies every column against the schema
derived from the manifest and fails on any unknown table or column, with no
warehouse connection. A column rename upstream therefore breaks here, not at 2am.
"""

from __future__ import annotations

import sqlglot
from sqlglot.errors import OptimizeError, SqlglotError
from sqlglot.optimizer.qualify import qualify
from sqlglot.schema import MappingSchema

from di0.ports import Schema, ValidationResult


class SqlglotOfflineValidation:
    def __init__(self, dialect: str) -> None:
        self._dialect = dialect

    def validate(self, sql: str, schema: Schema) -> ValidationResult:
        try:
            expression = sqlglot.parse_one(sql, read=self._dialect)
        except SqlglotError as error:
            return ValidationResult(ok=False, errors=(f"parse error: {error}",))

        mapping = MappingSchema(schema, dialect=self._dialect)
        try:
            qualify(
                expression,
                dialect=self._dialect,
                schema=mapping,
                validate_qualify_columns=True,
            )
        except OptimizeError as error:
            return ValidationResult(ok=False, errors=(str(error).strip(),))
        return ValidationResult(ok=True)
