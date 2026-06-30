"""DialectPort adapter: compose/normalize SQL for a target dialect via sqlglot.

The dialect is a parameter, not a fork - sqlglot transpiles across dialects, so
the same composition path serves any target named in the profile.
"""

from __future__ import annotations

import sqlglot

from di0.adapters._sqlglot import to_sqlglot_dialect


class SqlglotDialect:
    def __init__(self, dialect: str) -> None:
        self._dialect = to_sqlglot_dialect(dialect)

    def compose(self, sql: str) -> str:
        # Parse and re-render in the target dialect; this normalizes the SQL and
        # fails fast on a syntax error before validation/execution.
        expression = sqlglot.parse_one(sql, read=self._dialect)
        return expression.sql(dialect=self._dialect)
