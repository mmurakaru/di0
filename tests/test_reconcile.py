"""Cross-source reconcile: fetch reduced results per source, combine locally in DuckDB.

The combine is raw SQL over the fetched result sets - the join never runs in any
source warehouse. Sources only fetch rows.
"""

from __future__ import annotations

from di0 import core
from di0.adapters.duckdb_combine import DuckdbCombine
from di0.ports import QueryResult
from di0.reconcile import ReconcileSpec


def test_duckdb_combine_joins_two_result_sets():
    usage = QueryResult(
        columns=("component", "url"),
        rows=(("hero", "/pricing"), ("hero", "/product"), ("cta", "/product")),
    )
    traffic = QueryResult(
        columns=("url", "pageviews"),
        rows=(("/pricing", 52000), ("/product", 31000)),
    )
    sql = """
        SELECT u.component,
               COUNT(DISTINCT u.url)        AS pages,
               COALESCE(SUM(t.pageviews),0) AS traffic
        FROM usage u
        LEFT JOIN traffic t ON t.url = u.url
        GROUP BY u.component
        ORDER BY traffic DESC
    """
    out = DuckdbCombine().combine({"usage": usage, "traffic": traffic}, sql)
    assert out.columns == ("component", "pages", "traffic")
    by_component = {row[0]: (row[1], row[2]) for row in out.rows}
    assert by_component["hero"] == (2, 83000)  # /pricing 52k + /product 31k
    assert by_component["cta"] == (1, 31000)


class _FakeEngine:
    def __init__(self, result: QueryResult) -> None:
        self._result = result

    def query(self, sql: str) -> QueryResult:  # noqa: ARG002 - canned result
        return self._result


def test_reconcile_runs_per_source_then_combines(tmp_path):
    (tmp_path / "usage.sql").write_text("select 1")  # content irrelevant (fake engine)
    (tmp_path / "traffic.sql").write_text("select 1")
    (tmp_path / "combine.sql").write_text(
        "SELECT u.component, SUM(t.pageviews) AS traffic "
        "FROM usage u JOIN traffic t ON t.url = u.url GROUP BY u.component"
    )
    spec_path = tmp_path / "spec.yml"
    spec_path.write_text(
        "sources:\n"
        "  strapi: {schema_source: s, dialect: postgres, validation: v, execution: e}\n"
        "  warehouse: {schema_source: s, dialect: snowflake, validation: v, execution: e}\n"
        "queries:\n"
        "  - {name: usage, source: strapi, query: usage.sql}\n"
        "  - {name: traffic, source: warehouse, query: traffic.sql}\n"
        "combine: combine.sql\n"
    )
    results = iter(
        [
            QueryResult(columns=("component", "url"), rows=(("hero", "/p"),)),
            QueryResult(columns=("url", "pageviews"), rows=(("/p", 100),)),
        ]
    )

    def factory(_profile):
        return _FakeEngine(next(results))

    out = core.reconcile(
        ReconcileSpec.from_file(spec_path), tmp_path, factory, DuckdbCombine()
    )
    assert out.columns == ("component", "traffic")
    assert out.rows == (("hero", 100),)


def test_reconcile_rejects_unknown_source(tmp_path):
    (tmp_path / "q.sql").write_text("select 1")
    (tmp_path / "combine.sql").write_text("SELECT 1")
    spec_path = tmp_path / "spec.yml"
    spec_path.write_text(
        "sources:\n"
        "  known: {schema_source: s, dialect: d, validation: v, execution: e}\n"
        "queries:\n"
        "  - {name: a, source: missing, query: q.sql}\n"
        "combine: combine.sql\n"
    )
    import pytest

    with pytest.raises(ValueError, match="unknown source"):
        core.reconcile(
            ReconcileSpec.from_file(spec_path), tmp_path, lambda p: None, DuckdbCombine()
        )
