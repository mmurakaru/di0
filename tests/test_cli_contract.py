"""Slice #57: the machine-readable output contract.

Every verb (schema/validate/query/check/author/reconcile/guard) can emit one JSON
envelope so an agent harness parses results without scraping prose, with stable
BSD-sysexits exit codes mapped from the failure class. Text output stays
byte-for-byte what it was before the flag existed.
"""

from __future__ import annotations

import json
from pathlib import Path

from di0 import cli, cliio
from di0.ports import QueryResult

REPO_ROOT = Path(__file__).parent.parent
FIXTURE_MANIFEST = REPO_ROOT / "tests" / "fixtures" / "manifest.json"
CORE = REPO_ROOT / "src" / "di0"
PYPROJECT = REPO_ROOT / "pyproject.toml"

ENVELOPE_KEYS = {"contract_version", "command", "ok", "data", "error", "warnings"}
ERROR_KEYS = {"code", "message", "suggestions", "detail"}


def _offline_profile(tmp_path: Path) -> str:
    """A noop-execution, offline-validation profile over the fixture manifest."""
    profile = tmp_path / "di0.profile.yml"
    profile.write_text(
        "schema_source: dbt-manifest\n"
        f"manifest_path: {FIXTURE_MANIFEST}\n"
        "dialect: snowflake\n"
        "validation: sqlglot-offline\n"
        "execution: noop\n"
    )
    return str(profile)


def _envelope(capsys) -> dict:
    return json.loads(capsys.readouterr().out)


# --- exit-code and http-code mapping (centralised in cliio) ------------------


def test_exit_code_constants_are_sysexits():
    assert cliio.EX_OK == 0
    assert cliio.EX_USAGE == 64
    assert cliio.EX_DATAERR == 65
    assert cliio.EX_UNAVAILABLE == 69
    assert cliio.EX_SOFTWARE == 70
    assert cliio.EX_CONFIG == 78


# --- envelope shape ----------------------------------------------------------


def test_envelope_shape_and_contract_version(tmp_path, capsys):
    profile = _offline_profile(tmp_path)
    assert cli.main(["--profile", profile, "schema", "--json"]) == 0
    env = _envelope(capsys)
    assert set(env) == ENVELOPE_KEYS
    assert env["contract_version"] == cliio.CONTRACT_VERSION == "0.1.0"
    assert env["command"] == "schema"
    assert env["ok"] is True
    assert env["error"] is None
    assert env["warnings"] == []
    assert "analytics" in env["data"]


def test_json_flag_equivalent_to_format_json(tmp_path, capsys):
    profile = _offline_profile(tmp_path)
    sql = "SELECT customer_id FROM analytics.dim_customers"
    cli.main(["--profile", profile, "validate", sql, "--json"])
    via_flag = _envelope(capsys)
    cli.main(["--profile", profile, "validate", sql, "--format", "json"])
    via_format = _envelope(capsys)
    assert via_flag == via_format


# --- schema ------------------------------------------------------------------


def test_schema_text_mode_is_raw_schema_not_envelope(tmp_path, capsys):
    profile = _offline_profile(tmp_path)
    assert cli.main(["--profile", profile, "schema"]) == 0
    out = capsys.readouterr().out
    assert "contract_version" not in out
    assert json.loads(out)["analytics"]["dim_customers"]  # the bare resolved schema


def test_schema_missing_profile_is_config_error(tmp_path, capsys):
    missing = str(tmp_path / "nope.yml")
    code = cli.main(["--profile", missing, "schema", "--json"])
    env = _envelope(capsys)
    assert code == cliio.EX_CONFIG
    assert env["ok"] is False
    assert env["data"] is None
    assert env["error"]["code"] == 404
    assert set(env["error"]) == ERROR_KEYS


def test_config_error_text_mode_writes_stderr_and_exits_config(tmp_path, capsys):
    missing = str(tmp_path / "nope.yml")
    code = cli.main(["--profile", missing, "schema"])
    cap = capsys.readouterr()
    assert code == cliio.EX_CONFIG
    assert cap.out == ""
    assert "ERROR" in cap.err


# --- validate ----------------------------------------------------------------


def test_validate_success_json(tmp_path, capsys):
    profile = _offline_profile(tmp_path)
    sql = "SELECT customer_id FROM analytics.dim_customers"
    code = cli.main(["--profile", profile, "validate", sql, "--json"])
    env = _envelope(capsys)
    assert code == cliio.EX_OK
    assert env["command"] == "validate"
    assert env["ok"] is True
    assert env["data"] == {"valid": True, "errors": []}
    assert env["error"] is None


def test_validate_failure_json(tmp_path, capsys):
    profile = _offline_profile(tmp_path)
    code = cli.main(
        ["--profile", profile, "validate", "SELECT nope FROM analytics.dim_customers", "--json"]
    )
    env = _envelope(capsys)
    assert code == cliio.EX_DATAERR
    assert env["ok"] is False
    assert env["data"]["valid"] is False
    assert env["data"]["errors"]
    assert env["error"]["code"] == 422
    assert env["error"]["message"]


def test_validate_failure_suggests_close_identifier(tmp_path, capsys):
    profile = _offline_profile(tmp_path)
    typo = "SELECT currnt_arr FROM analytics.dim_customers"  # near-miss on current_arr
    cli.main(["--profile", profile, "validate", typo, "--json"])
    env = _envelope(capsys)
    assert "current_arr" in env["error"]["suggestions"]


def test_validate_text_success_unchanged(tmp_path, capsys):
    profile = _offline_profile(tmp_path)
    code = cli.main(
        ["--profile", profile, "validate", "SELECT customer_id FROM analytics.dim_customers"]
    )
    cap = capsys.readouterr()
    assert code == cliio.EX_OK
    assert cap.out == "OK\n"
    assert cap.err == ""


def test_validate_text_failure_unchanged(tmp_path, capsys):
    profile = _offline_profile(tmp_path)
    code = cli.main(["--profile", profile, "validate", "SELECT nope FROM analytics.dim_customers"])
    cap = capsys.readouterr()
    assert code == cliio.EX_DATAERR
    assert cap.out == ""
    assert cap.err.startswith("INVALID: ")


# --- query -------------------------------------------------------------------


def test_query_success_json_noop(tmp_path, capsys):
    profile = _offline_profile(tmp_path)
    code = cli.main(
        ["--profile", profile, "query", "SELECT customer_id FROM analytics.dim_customers", "--json"]
    )
    env = _envelope(capsys)
    assert code == cliio.EX_OK
    assert env["ok"] is True
    assert env["command"] == "query"
    assert env["data"] == {"columns": [], "rows": []}  # noop execution returns no rows


def test_query_validation_failure_json(tmp_path, capsys):
    profile = _offline_profile(tmp_path)
    code = cli.main(
        ["--profile", profile, "query", "SELECT nope FROM analytics.dim_customers", "--json"]
    )
    env = _envelope(capsys)
    assert code == cliio.EX_DATAERR
    assert env["ok"] is False
    assert env["error"]["code"] == 422


def test_query_execution_error_is_unavailable(tmp_path, capsys, monkeypatch):
    profile = _offline_profile(tmp_path)

    class _BoomEngine:
        def query(self, sql):  # noqa: ARG002 - target failure regardless of input
            raise RuntimeError("target unreachable")

    monkeypatch.setattr(cli, "_build_engine", lambda profile: _BoomEngine())
    code = cli.main(["--profile", profile, "query", "SELECT 1", "--json"])
    env = _envelope(capsys)
    assert code == cliio.EX_UNAVAILABLE
    assert env["ok"] is False
    assert env["error"]["code"] == 502


def test_query_text_success_unchanged(tmp_path, capsys):
    profile = _offline_profile(tmp_path)
    code = cli.main(
        ["--profile", profile, "query", "SELECT customer_id FROM analytics.dim_customers"]
    )
    cap = capsys.readouterr()
    assert code == cliio.EX_OK
    assert cap.out == ""  # noop yields no columns/rows to print
    assert cap.err == ""


# --- check -------------------------------------------------------------------


def _queries_dir(tmp_path: Path, files: dict[str, str]) -> Path:
    queries = tmp_path / "queries"
    queries.mkdir()
    for name, sql in files.items():
        (queries / name).write_text(sql)
    return queries


def test_check_success_json(tmp_path, capsys):
    profile = _offline_profile(tmp_path)
    queries = _queries_dir(tmp_path, {"a.sql": "SELECT customer_id FROM analytics.dim_customers"})
    code = cli.main(["--profile", profile, "check", "--queries", str(queries), "--json"])
    env = _envelope(capsys)
    assert code == cliio.EX_OK
    assert env["ok"] is True
    assert env["data"]["ok_count"] == 1
    assert env["data"]["fail_count"] == 0
    assert env["data"]["files"][0]["valid"] is True
    assert set(env["data"]["files"][0]) == {"path", "valid", "errors"}


def test_check_drift_json(tmp_path, capsys):
    profile = _offline_profile(tmp_path)
    queries = _queries_dir(
        tmp_path,
        {
            "good.sql": "SELECT customer_id FROM analytics.dim_customers",
            "bad.sql": "SELECT nope FROM analytics.dim_customers",
        },
    )
    code = cli.main(["--profile", profile, "check", "--queries", str(queries), "--json"])
    env = _envelope(capsys)
    assert code == cliio.EX_DATAERR
    assert env["ok"] is False
    assert env["data"]["ok_count"] == 1
    assert env["data"]["fail_count"] == 1
    assert env["error"]["code"] == 422


def test_check_no_files_json(tmp_path, capsys):
    profile = _offline_profile(tmp_path)
    queries = tmp_path / "queries"
    queries.mkdir()
    code = cli.main(["--profile", profile, "check", "--queries", str(queries), "--json"])
    env = _envelope(capsys)
    assert code == cliio.EX_OK
    assert env["ok"] is True
    assert env["data"] == {"files": [], "ok_count": 0, "fail_count": 0}


def test_check_text_mode_unchanged(tmp_path, capsys):
    profile = _offline_profile(tmp_path)
    queries = _queries_dir(
        tmp_path,
        {
            "good.sql": "SELECT customer_id FROM analytics.dim_customers",
            "bad.sql": "SELECT nope FROM analytics.dim_customers",
        },
    )
    code = cli.main(["--profile", profile, "check", "--queries", str(queries)])
    cap = capsys.readouterr()
    assert code == cliio.EX_DATAERR
    assert "OK    " in cap.out
    assert "queries valid" in cap.out
    assert "DRIFT " in cap.err


# --- author ------------------------------------------------------------------


def _dashboard_spec(tmp_path: Path) -> str:
    (tmp_path / "q.sql").write_text("SELECT customer_id FROM analytics.dim_customers")
    spec = tmp_path / "dash.yml"
    spec.write_text(
        "name: Health\n"
        "collection_id: 42\n"
        "tabs:\n"
        "  - name: Main\n"
        "    cards:\n"
        "      - title: c\n"
        "        query: q.sql\n"
    )
    return str(spec)


def test_author_unsupported_json(tmp_path, capsys):
    profile = _offline_profile(tmp_path)  # noop execution cannot author
    spec = _dashboard_spec(tmp_path)
    code = cli.main(["--profile", profile, "author", spec, "--json"])
    env = _envelope(capsys)
    assert code == cliio.EX_UNAVAILABLE
    assert env["command"] == "author"
    assert env["ok"] is False
    assert env["error"]["code"] == 501


def test_author_unsupported_text_unchanged(tmp_path, capsys):
    profile = _offline_profile(tmp_path)
    spec = _dashboard_spec(tmp_path)
    code = cli.main(["--profile", profile, "author", spec])
    cap = capsys.readouterr()
    assert code == cliio.EX_UNAVAILABLE
    assert cap.err.startswith("ERROR: ")


def test_author_success_json(metabase_authoring, monkeypatch, tmp_path, capsys):
    base_url, _recorder = metabase_authoring
    monkeypatch.setenv("DI0_TEST_METABASE_KEY", "secret-token")
    profile = tmp_path / "di0.profile.yml"
    profile.write_text(
        "schema_source: dbt-manifest\n"
        f"manifest_path: {FIXTURE_MANIFEST}\n"
        "dialect: snowflake\n"
        "validation: sqlglot-offline\n"
        "execution: metabase\n"
        f"metabase_url: {base_url}\n"
        "metabase_database_id: 7\n"
        "metabase_api_key_env: DI0_TEST_METABASE_KEY\n"
    )
    spec = _dashboard_spec(tmp_path)
    code = cli.main(["--profile", str(profile), "author", spec, "--json"])
    env = _envelope(capsys)
    assert code == cliio.EX_OK
    assert env["ok"] is True
    assert env["data"]["kind"] == "dashboard"
    assert env["data"]["identifier"] == "42"
    assert env["data"]["detail"]["url"].endswith("/dashboard/42")


# --- reconcile ---------------------------------------------------------------


def test_reconcile_unknown_source_is_dataerr(tmp_path, capsys):
    (tmp_path / "a.sql").write_text("SELECT 1")
    (tmp_path / "combine.sql").write_text("SELECT 1")
    spec = tmp_path / "spec.yml"
    spec.write_text(
        "sources:\n"
        "  known: {schema_source: s, dialect: d, validation: v, execution: e}\n"
        "queries:\n"
        "  - name: t\n"
        "    source: missing\n"
        "    query: a.sql\n"
        "combine: combine.sql\n"
    )
    code = cli.main(["reconcile", str(spec), "--json"])
    env = _envelope(capsys)
    assert code == cliio.EX_DATAERR
    assert env["command"] == "reconcile"
    assert env["ok"] is False
    assert env["error"]["code"] == 422


def test_reconcile_success_json(tmp_path, capsys, monkeypatch):
    (tmp_path / "usage.sql").write_text("SELECT 1")
    (tmp_path / "combine.sql").write_text("SELECT 1")
    spec = tmp_path / "spec.yml"
    spec.write_text(
        "sources:\n"
        "  s: {schema_source: x, dialect: d, validation: v, execution: e}\n"
        "queries:\n"
        "  - name: usage\n"
        "    source: s\n"
        "    query: usage.sql\n"
        "combine: combine.sql\n"
    )

    class _FakeEngine:
        def query(self, sql):  # noqa: ARG002 - canned rows
            return QueryResult(columns=("c",), rows=((1,),))

    class _FakeCombine:
        def combine(self, tables, sql):  # noqa: ARG002 - canned combine
            return QueryResult(columns=("component", "traffic"), rows=(("hero", 83000),))

    monkeypatch.setattr(cli, "build_engine", lambda profile: _FakeEngine())
    monkeypatch.setattr(cli, "build_combine_port", lambda: _FakeCombine())
    code = cli.main(["reconcile", str(spec), "--json"])
    env = _envelope(capsys)
    assert code == cliio.EX_OK
    assert env["ok"] is True
    assert env["data"]["columns"] == ["component", "traffic"]
    assert env["data"]["rows"] == [["hero", 83000]]


# --- guard -------------------------------------------------------------------


def test_guard_success_json(capsys):
    code = cli.main(["guard", "--path", str(CORE), "--pyproject", str(PYPROJECT), "--json"])
    env = _envelope(capsys)
    assert code == cliio.EX_OK
    assert env["ok"] is True
    assert env["data"] == {"violations": []}
    assert env["error"] is None


def test_guard_violation_json(tmp_path, capsys):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "leak"\ndependencies = ["psycopg[binary]>=3"]\n')
    code = cli.main(["guard", "--path", str(CORE), "--pyproject", str(pyproject), "--json"])
    env = _envelope(capsys)
    assert code == cliio.EX_DATAERR
    assert env["ok"] is False
    assert env["data"]["violations"]
    assert set(env["data"]["violations"][0]) == {"file", "line", "literal", "reason"}
    assert env["error"]["code"] == 422


# --- usage / internal failure classes ----------------------------------------


def test_usage_error_exits_ex_usage(capsys):
    code = cli.main(["validate"])  # missing required positional
    assert code == cliio.EX_USAGE


def test_usage_error_json_envelope(capsys):
    code = cli.main(["validate", "--json"])  # missing positional, json requested
    assert code == cliio.EX_USAGE
    env = json.loads(capsys.readouterr().out)
    assert env["command"] == "validate"
    assert env["ok"] is False
    assert env["error"]["code"] == 400


def test_unexpected_internal_error_exits_ex_software(tmp_path, capsys, monkeypatch):
    profile = _offline_profile(tmp_path)

    def _boom(profile):  # noqa: ARG001 - explode before any handled failure class
        raise RuntimeError("kaboom")

    monkeypatch.setattr(cli, "_build_engine", _boom)
    code = cli.main(["--profile", profile, "schema", "--json"])
    env = _envelope(capsys)
    assert code == cliio.EX_SOFTWARE
    assert env["ok"] is False
    assert env["error"]["code"] == 500
