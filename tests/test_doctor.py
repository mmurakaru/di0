"""Slice #61: `di0 doctor` self-diagnoses a workspace's setup.

doctor runs a sequence of checks over a profile - it wires up, resolves a schema,
finds required credential env vars, round-trips a trivial validation, and (with
--probe) reaches the execution target. Each check reports pass/fail with a fix
hint. It honours the #57 contract: a json envelope listing every check, and
sysexit exit codes (EX_OK / EX_CONFIG / EX_UNAVAILABLE).
"""

from __future__ import annotations

import json
from pathlib import Path

from di0 import cli, cliio, doctor
from di0.ports import ValidationResult

REPO_ROOT = Path(__file__).parent.parent
FIXTURE_MANIFEST = REPO_ROOT / "tests" / "fixtures" / "manifest.json"
EXAMPLES_PROFILE = REPO_ROOT / "examples" / "di0.profile.yml"

ENVELOPE_KEYS = {"contract_version", "command", "ok", "data", "error", "warnings"}
ERROR_KEYS = {"code", "message", "suggestions", "detail"}
CHECK_KEYS = {"name", "passed", "detail", "hint"}


def _offline_profile(tmp_path: Path, extra: str = "") -> str:
    """A noop-execution, offline-validation profile over the fixture manifest."""
    profile = tmp_path / "di0.profile.yml"
    profile.write_text(
        "schema_source: dbt-manifest\n"
        f"manifest_path: {FIXTURE_MANIFEST}\n"
        "dialect: snowflake\n"
        "validation: sqlglot-offline\n"
        "execution: noop\n" + extra
    )
    return str(profile)


def _envelope(capsys) -> dict:
    return json.loads(capsys.readouterr().out)


def _check(report: doctor.Report, name: str) -> doctor.Check:
    return next(check for check in report.checks if check.name == name)


# --- healthy profile ---------------------------------------------------------


def test_healthy_profile_passes_all_checks(tmp_path):
    report = doctor.run_checks(_offline_profile(tmp_path))
    assert report.ok is True
    assert report.exit_category is None
    names = [check.name for check in report.checks]
    assert names == ["profile", "schema", "credentials", "validation"]
    assert all(check.passed for check in report.checks)


def test_cli_doctor_healthy_exits_ok_text(tmp_path, capsys):
    code = cli.main(["--profile", _offline_profile(tmp_path), "doctor"])
    out = capsys.readouterr().out
    assert code == cliio.EX_OK
    assert "PASS" in out
    assert "FAIL" not in out


def test_cli_doctor_accepts_profile_after_subcommand(monkeypatch, capsys):
    # First-run ergonomics: `di0 doctor --profile X` (flag after the verb) works,
    # and the committed example profile is healthy out of the box.
    monkeypatch.chdir(REPO_ROOT)
    code = cli.main(["doctor", "--profile", str(EXAMPLES_PROFILE)])
    capsys.readouterr()
    assert code == cliio.EX_OK


# --- config problems (EX_CONFIG) ---------------------------------------------


def test_missing_profile_is_config(tmp_path, capsys):
    missing = str(tmp_path / "nope.yml")
    code = cli.main(["--profile", missing, "doctor", "--json"])
    env = _envelope(capsys)
    assert code == cliio.EX_CONFIG
    assert env["ok"] is False
    assert env["error"] is not None
    # the one check that ran (profile) failed and carries a fix hint
    assert env["data"]["checks"][0]["name"] == "profile"
    assert env["data"]["checks"][0]["passed"] is False
    assert env["data"]["checks"][0]["hint"]


def test_broken_profile_is_config(tmp_path, capsys):
    profile = tmp_path / "di0.profile.yml"
    profile.write_text(
        "schema_source: no-such-source\n"
        "dialect: snowflake\n"
        "validation: sqlglot-offline\n"
        "execution: noop\n"
    )
    code = cli.main(["--profile", str(profile), "doctor"])
    cap = capsys.readouterr()
    assert code == cliio.EX_CONFIG
    assert "FAIL" in cap.out


def test_missing_credential_env_var_is_reported(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("DI0_DOCTOR_TEST_KEY", raising=False)
    # An execution target that names a credential env var but still wires up and
    # resolves a schema offline - only the credential check should fail.
    profile = tmp_path / "di0.profile.yml"
    profile.write_text(
        "schema_source: dbt-manifest\n"
        f"manifest_path: {FIXTURE_MANIFEST}\n"
        "dialect: snowflake\n"
        "validation: sqlglot-offline\n"
        "execution: metabase\n"
        "metabase_url: http://127.0.0.1:1\n"
        "metabase_database_id: 1\n"
        "metabase_api_key_env: DI0_DOCTOR_TEST_KEY\n"
    )
    report = doctor.run_checks(str(profile))
    credentials = _check(report, "credentials")
    assert credentials.passed is False
    assert "DI0_DOCTOR_TEST_KEY" in credentials.detail
    assert credentials.hint
    assert report.exit_category == doctor.CATEGORY_CONFIG

    code = cli.main(["--profile", str(profile), "doctor", "--json"])
    env = _envelope(capsys)
    assert code == cliio.EX_CONFIG
    reported = next(c for c in env["data"]["checks"] if c["name"] == "credentials")
    assert reported["passed"] is False
    assert "DI0_DOCTOR_TEST_KEY" in reported["detail"]


def test_credential_env_var_set_passes(tmp_path, monkeypatch):
    monkeypatch.setenv("DI0_DOCTOR_TEST_KEY", "secret-token")
    profile = tmp_path / "di0.profile.yml"
    profile.write_text(
        "schema_source: dbt-manifest\n"
        f"manifest_path: {FIXTURE_MANIFEST}\n"
        "dialect: snowflake\n"
        "validation: sqlglot-offline\n"
        "execution: metabase\n"
        "metabase_url: http://127.0.0.1:1\n"
        "metabase_database_id: 1\n"
        "metabase_api_key_env: DI0_DOCTOR_TEST_KEY\n"
    )
    report = doctor.run_checks(str(profile))
    assert _check(report, "credentials").passed is True
    assert report.exit_category is None


# --- unreachable schema / target (EX_UNAVAILABLE) ----------------------------


def test_unreachable_schema_is_unavailable(tmp_path, capsys):
    profile = tmp_path / "di0.profile.yml"
    profile.write_text(
        "schema_source: dbt-manifest\n"
        f"manifest_path: {tmp_path / 'gone.json'}\n"
        "dialect: snowflake\n"
        "validation: sqlglot-offline\n"
        "execution: noop\n"
    )
    report = doctor.run_checks(str(profile))
    schema = _check(report, "schema")
    assert schema.passed is False
    assert schema.category == doctor.CATEGORY_UNAVAILABLE
    assert report.exit_category == doctor.CATEGORY_UNAVAILABLE

    code = cli.main(["--profile", str(profile), "doctor", "--json"])
    env = _envelope(capsys)
    assert code == cliio.EX_UNAVAILABLE
    assert env["ok"] is False


# --- --probe (execution connectivity) ----------------------------------------


def test_probe_adds_connectivity_check_and_passes_for_noop(tmp_path):
    report = doctor.run_checks(_offline_profile(tmp_path), probe=True)
    names = [check.name for check in report.checks]
    assert "connectivity" in names
    assert _check(report, "connectivity").passed is True
    assert report.exit_category is None


def test_no_probe_omits_connectivity_check(tmp_path):
    report = doctor.run_checks(_offline_profile(tmp_path))
    assert "connectivity" not in [check.name for check in report.checks]


def test_probe_unreachable_target_is_unavailable(tmp_path, monkeypatch):
    profile = tmp_path / "di0.profile.yml"
    profile.write_text(
        "schema_source: dbt-manifest\n"
        f"manifest_path: {FIXTURE_MANIFEST}\n"
        "dialect: snowflake\n"
        "validation: sqlglot-offline\n"
        "execution: noop\n"
    )

    class _SchemaPort:
        def resolve(self):
            return {"ns": {"t": {"c": "int"}}}

    class _Engine:
        schema_port = _SchemaPort()

        def validate(self, sql):  # noqa: ARG002 - trivial round-trip is fine
            return ValidationResult(ok=True)

        def query(self, sql):  # noqa: ARG002 - target is down regardless of input
            raise RuntimeError("connection refused")

    monkeypatch.setattr(doctor, "build_engine", lambda profile: _Engine())
    report = doctor.run_checks(str(profile), probe=True)
    connectivity = _check(report, "connectivity")
    assert connectivity.passed is False
    assert connectivity.category == doctor.CATEGORY_UNAVAILABLE
    assert report.exit_category == doctor.CATEGORY_UNAVAILABLE


# --- json contract shape ------------------------------------------------------


def test_json_envelope_shape_success(tmp_path, capsys):
    code = cli.main(["--profile", _offline_profile(tmp_path), "doctor", "--json"])
    env = _envelope(capsys)
    assert code == cliio.EX_OK
    assert set(env) == ENVELOPE_KEYS
    assert env["command"] == "doctor"
    assert env["ok"] is True
    assert env["error"] is None
    assert env["data"]["checks"]
    for check in env["data"]["checks"]:
        assert set(check) == CHECK_KEYS


def test_json_envelope_shape_failure(tmp_path, capsys):
    missing = str(tmp_path / "nope.yml")
    code = cli.main(["--profile", missing, "doctor", "--json"])
    env = _envelope(capsys)
    assert code == cliio.EX_CONFIG
    assert env["ok"] is False
    assert set(env["error"]) == ERROR_KEYS
    assert env["data"]["checks"]
