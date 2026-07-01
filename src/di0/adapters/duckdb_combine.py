"""CombinePort adapter: join fetched result sets locally with DuckDB.

Each source's already-reduced result set is registered as a local table, then a
raw combine SQL joins/aggregates them in-process. DuckDB is the in-process,
SQL-first engine, so the combine stays real SQL - no DataFrame DSL - consistent
with di0's core principle.
"""

from __future__ import annotations

import duckdb

from di0.ports import QueryResult


def _duck_type(values: list) -> str:
    resolved = "VARCHAR"
    for value in values:
        if value is None:
            continue
        if isinstance(value, bool):
            return "BOOLEAN"
        if isinstance(value, float):
            resolved = "DOUBLE"
        elif isinstance(value, int):
            resolved = "DOUBLE" if resolved == "DOUBLE" else "BIGINT"
        else:
            return "VARCHAR"
    return resolved


class DuckdbCombine:
    def combine(self, tables: dict[str, QueryResult], sql: str) -> QueryResult:
        connection = duckdb.connect()
        try:
            for name, result in tables.items():
                self._register(connection, name, result)
            cursor = connection.execute(sql)
            columns = tuple(description[0] for description in cursor.description)
            rows = tuple(tuple(row) for row in cursor.fetchall())
            return QueryResult(columns=columns, rows=rows)
        finally:
            connection.close()

    @staticmethod
    def _register(connection, name: str, result: QueryResult) -> None:
        columns = result.columns
        types = [
            _duck_type([row[index] for row in result.rows]) for index in range(len(columns))
        ]
        column_defs = ", ".join(
            f'"{col}" {type_}' for col, type_ in zip(columns, types, strict=True)
        )
        connection.execute(f'CREATE TABLE "{name}" ({column_defs})')
        if result.rows:
            placeholders = ", ".join("?" * len(columns))
            connection.executemany(
                f'INSERT INTO "{name}" VALUES ({placeholders})',
                [list(row) for row in result.rows],
            )
