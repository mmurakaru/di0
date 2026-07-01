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


class _LoggingEngine:
    def __init__(self, result: QueryResult, log: list) -> None:
        self._result = result
        self._log = log

    def query(self, sql: str) -> QueryResult:
        self._log.append(sql)
        return self._result


def test_reconcile_dependent_query_injects_keys(tmp_path):
    (tmp_path / "a.sql").write_text("select 1")
    (tmp_path / "b.sql").write_text("SELECT id, amount FROM big WHERE id IN ({keys})")
    (tmp_path / "combine.sql").write_text(
        "SELECT a.k AS k, SUM(b.amount) AS amount "
        "FROM (SELECT DISTINCT k FROM a) a JOIN b ON b.id = a.k GROUP BY a.k"
    )
    spec_path = tmp_path / "spec.yml"
    spec_path.write_text(  # dependent 'b' listed BEFORE its dependency 'a' on purpose
        "sources:\n"
        "  s1: {schema_source: A, dialect: d, validation: v, execution: e}\n"
        "  s2: {schema_source: B, dialect: d, validation: v, execution: e}\n"
        "queries:\n"
        "  - {name: b, source: s2, query: b.sql, depends_on: a, keys: k}\n"
        "  - {name: a, source: s1, query: a.sql}\n"
        "combine: combine.sql\n"
    )
    logs: dict[str, list] = {}
    results = {
        "A": QueryResult(columns=("k",), rows=(("x1",), ("x2",), ("x1",))),  # dup x1
        "B": QueryResult(columns=("id", "amount"), rows=(("x1", 5), ("x2", 7))),
    }

    def factory(profile):
        logs.setdefault(profile.schema_source, [])
        return _LoggingEngine(results[profile.schema_source], logs[profile.schema_source])

    out = core.reconcile(ReconcileSpec.from_file(spec_path), tmp_path, factory, DuckdbCombine())

    b_sql = logs["B"][0]
    assert "IN ('x1', 'x2')" in b_sql  # distinct keys injected, order preserved
    assert "{keys}" not in b_sql
    assert {r[0]: r[1] for r in out.rows} == {"x1": 5, "x2": 7}


def test_reconcile_dependent_keys_are_case_insensitive(tmp_path):
    (tmp_path / "a.sql").write_text("select 1")
    (tmp_path / "b.sql").write_text("SELECT id FROM big WHERE id IN ({keys})")
    (tmp_path / "combine.sql").write_text("SELECT COUNT(*) AS n FROM b")
    spec_path = tmp_path / "spec.yml"
    spec_path.write_text(
        "sources:\n"
        "  s1: {schema_source: A, dialect: d, validation: v, execution: e}\n"
        "  s2: {schema_source: B, dialect: d, validation: v, execution: e}\n"
        "queries:\n"
        "  - {name: a, source: s1, query: a.sql}\n"
        "  - {name: b, source: s2, query: b.sql, depends_on: a, keys: customer_id}\n"
        "combine: combine.sql\n"
    )
    logs: dict[str, list] = {}
    results = {
        "A": QueryResult(columns=("CUSTOMER_ID",), rows=(("x1",), ("x2",))),  # upper-cased
        "B": QueryResult(columns=("id",), rows=(("x1",),)),
    }

    def factory(profile):
        logs.setdefault(profile.schema_source, [])
        return _LoggingEngine(results[profile.schema_source], logs[profile.schema_source])

    core.reconcile(ReconcileSpec.from_file(spec_path), tmp_path, factory, DuckdbCombine())
    assert "IN ('x1', 'x2')" in logs["B"][0]  # matched CUSTOMER_ID despite lowercase `keys`


def test_reconcile_dependent_chunks_large_key_sets(tmp_path):
    (tmp_path / "a.sql").write_text("select 1")
    (tmp_path / "b.sql").write_text("SELECT id FROM big WHERE id IN ({keys})")
    (tmp_path / "combine.sql").write_text("SELECT COUNT(*) AS n FROM b")
    spec_path = tmp_path / "spec.yml"
    spec_path.write_text(
        "sources:\n"
        "  s1: {schema_source: A, dialect: d, validation: v, execution: e}\n"
        "  s2: {schema_source: B, dialect: d, validation: v, execution: e}\n"
        "queries:\n"
        "  - {name: a, source: s1, query: a.sql}\n"
        "  - {name: b, source: s2, query: b.sql, depends_on: a, keys: id, chunk: 2}\n"
        "combine: combine.sql\n"
    )
    logs: dict[str, list] = {}
    results = {
        "A": QueryResult(columns=("id",), rows=(("k1",), ("k2",), ("k3",), ("k4",), ("k5",))),
        "B": QueryResult(columns=("id",), rows=(("k1",),)),  # each batch returns 1 row
    }

    def factory(profile):
        logs.setdefault(profile.schema_source, [])
        return _LoggingEngine(results[profile.schema_source], logs[profile.schema_source])

    out = core.reconcile(ReconcileSpec.from_file(spec_path), tmp_path, factory, DuckdbCombine())
    # 5 keys, chunk 2 -> 3 batches -> 3 executions of the dependent query
    assert len(logs["B"]) == 3
    assert "IN ('k1', 'k2')" in logs["B"][0]
    assert "IN ('k5')" in logs["B"][2]
    # results concatenated: 3 batches x 1 row each
    assert out.rows == ((3,),)


def test_reconcile_unresolved_dependency_raises(tmp_path):
    (tmp_path / "b.sql").write_text("SELECT 1 WHERE 1 IN ({keys})")
    (tmp_path / "combine.sql").write_text("SELECT 1 AS x")
    spec_path = tmp_path / "spec.yml"
    spec_path.write_text(
        "sources:\n  s: {schema_source: A, dialect: d, validation: v, execution: e}\n"
        "queries:\n  - {name: b, source: s, query: b.sql, depends_on: missing, keys: k}\n"
        "combine: combine.sql\n"
    )
    import pytest

    with pytest.raises(ValueError, match="unresolved"):
        core.reconcile(
            ReconcileSpec.from_file(spec_path), tmp_path, lambda p: None, DuckdbCombine()
        )


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
