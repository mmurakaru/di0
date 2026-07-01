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

from di0.adapters._sqlglot import to_sqlglot_dialect
from di0.ports import Schema, ValidationResult


def _prune_empty(schema: Schema) -> Schema:
    """Drop tables (and then namespaces) that have no columns.

    Real manifests contain models with no column-level contract; sqlglot's
    MappingSchema raises on a zero-column table. Such tables can't be column-checked
    anyway, so we omit them rather than crash the whole validation.
    """
    pruned: Schema = {}
    for namespace, tables in schema.items():
        kept = {table: cols for table, cols in tables.items() if cols}
        if kept:
            pruned[namespace] = kept
    return pruned


class SqlglotOfflineValidation:
    def __init__(self, dialect: str) -> None:
        self._dialect = to_sqlglot_dialect(dialect)

    def validate(self, sql: str, schema: Schema) -> ValidationResult:
        try:
            expression = sqlglot.parse_one(sql, read=self._dialect)
        except SqlglotError as error:
            return ValidationResult(ok=False, errors=(f"parse error: {error}",))

        mapping = MappingSchema(_prune_empty(schema), dialect=self._dialect)
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
