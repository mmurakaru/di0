"""Slice #59: policy-as-validation.

A policy is an optional, opt-in ValidationPort composed on top of the base
validator. Schema validity is proven first; only then is the policy checked. A
violation is a *denial* (ok=False, denied=True) - distinct from an ordinary
schema-invalidity - which the CLI surfaces as HTTP 403 / exit 77. With no policy
configured the engine is byte-for-byte the base validator, so nothing regresses.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from di0 import cli, cliio
from di0.adapters.policy_validation import Policy, PolicyValidation, load_policy
from di0.adapters.sqlglot_validation import SqlglotOfflineValidation
from di0.core import ValidationFailed
from di0.ports import Schema, ValidationResult
from di0.profile import Profile
from di0.registry import build_engine, build_validation_port

REPO_ROOT = Path(__file__).parent.parent
FIXTURE_MANIFEST = REPO_ROOT / "tests" / "fixtures" / "manifest.json"

SCHEMA: Schema = {
    "analytics": {
        "dim_customers": {
            "customer_id": "integer",
            "plan_name": "varchar",
            "current_arr": "number",
            "is_internal_account": "boolean",
        },
        "fct_subscription_revenue": {
            "customer_id": "integer",
            "revenue_month": "date",
            "arr": "number",
        },
    }
}


# --- policy loading ----------------------------------------------------------


def _policy_file(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "policy.yml"
    path.write_text(body)
    return path


def test_load_policy_reads_all_three_rules(tmp_path):
    path = _policy_file(
        tmp_path,
        "deny_columns:\n  - is_internal_account\n  - dim_customers.current_arr\n"
        "require_aggregation:\n  - fct_subscription_revenue\n"
        "row_limit: 1000\n",
    )
    policy = load_policy(path)
    assert policy.deny_columns == ("is_internal_account", "dim_customers.current_arr")
    assert policy.require_aggregation == ("fct_subscription_revenue",)
    assert policy.row_limit == 1000


def test_load_policy_empty_is_all_off(tmp_path):
    policy = load_policy(_policy_file(tmp_path, ""))
    assert policy == Policy()


# --- composite: base runs first ----------------------------------------------


class _RecordingBase:
    """A fake base ValidationPort that records its calls and returns a canned result."""

    def __init__(self, result: ValidationResult) -> None:
        self._result = result
        self.calls: list[str] = []

    def validate(self, sql: str, schema: Schema) -> ValidationResult:  # noqa: ARG002
        self.calls.append(sql)
        return self._result


def test_composite_runs_base_first_and_returns_base_failure_unchanged():
    # The SQL would violate the policy, but base validity fails first, so the base
    # result is returned verbatim (denied stays False) and the policy never runs.
    base_error = ValidationResult(ok=False, errors=("schema: no such column 'nope'",))
    base = _RecordingBase(base_error)
    policy = Policy(deny_columns=("is_internal_account",))
    composite = PolicyValidation(base, policy, dialect="snowflake")

    result = composite.validate(
        "SELECT is_internal_account FROM analytics.dim_customers", SCHEMA
    )

    assert base.calls == ["SELECT is_internal_account FROM analytics.dim_customers"]
    assert result is base_error
    assert result.ok is False
    assert result.denied is False


def test_composite_passes_through_base_ok_when_no_violation():
    base = _RecordingBase(ValidationResult(ok=True))
    composite = PolicyValidation(base, Policy(deny_columns=("ssn",)), dialect="snowflake")
    result = composite.validate("SELECT customer_id FROM analytics.dim_customers", SCHEMA)
    assert result.ok is True
    assert result.denied is False


# --- deny_columns ------------------------------------------------------------


def _offline_composite(policy: Policy) -> PolicyValidation:
    return PolicyValidation(SqlglotOfflineValidation("snowflake"), policy, dialect="snowflake")


def test_denylisted_column_is_denied_with_rule_named():
    composite = _offline_composite(Policy(deny_columns=("is_internal_account",)))
    result = composite.validate(
        "SELECT customer_id FROM analytics.dim_customers WHERE is_internal_account = FALSE",
        SCHEMA,
    )
    assert result.ok is False
    assert result.denied is True
    assert any("is_internal_account" in error for error in result.errors)


def test_qualified_deny_matches_qualified_reference():
    composite = _offline_composite(Policy(deny_columns=("dim_customers.current_arr",)))
    result = composite.validate(
        "SELECT dim_customers.current_arr FROM analytics.dim_customers", SCHEMA
    )
    assert result.denied is True


def test_non_denied_column_passes():
    composite = _offline_composite(Policy(deny_columns=("is_internal_account",)))
    result = composite.validate(
        "SELECT customer_id, current_arr FROM analytics.dim_customers", SCHEMA
    )
    assert result.ok is True
    assert result.denied is False


# --- require_aggregation -----------------------------------------------------


def test_require_aggregation_denies_ungrouped_query():
    composite = _offline_composite(Policy(require_aggregation=("fct_subscription_revenue",)))
    result = composite.validate(
        "SELECT customer_id, arr FROM analytics.fct_subscription_revenue", SCHEMA
    )
    assert result.ok is False
    assert result.denied is True
    assert any("aggregation" in error for error in result.errors)


def test_require_aggregation_allows_group_by():
    composite = _offline_composite(Policy(require_aggregation=("fct_subscription_revenue",)))
    result = composite.validate(
        "SELECT customer_id, SUM(arr) AS total FROM analytics.fct_subscription_revenue "
        "GROUP BY customer_id",
        SCHEMA,
    )
    assert result.ok is True
    assert result.denied is False


def test_require_aggregation_allows_bare_aggregate_function():
    composite = _offline_composite(Policy(require_aggregation=("fct_subscription_revenue",)))
    result = composite.validate(
        "SELECT SUM(arr) FROM analytics.fct_subscription_revenue", SCHEMA
    )
    assert result.ok is True


def test_require_aggregation_ignores_untouched_table():
    composite = _offline_composite(Policy(require_aggregation=("fct_subscription_revenue",)))
    result = composite.validate("SELECT customer_id FROM analytics.dim_customers", SCHEMA)
    assert result.ok is True


# --- row_limit ---------------------------------------------------------------


def test_row_limit_denies_missing_limit():
    composite = _offline_composite(Policy(row_limit=100))
    result = composite.validate("SELECT customer_id FROM analytics.dim_customers", SCHEMA)
    assert result.denied is True
    assert any("LIMIT" in error for error in result.errors)


def test_row_limit_denies_exceeding_limit():
    composite = _offline_composite(Policy(row_limit=100))
    result = composite.validate(
        "SELECT customer_id FROM analytics.dim_customers LIMIT 500", SCHEMA
    )
    assert result.denied is True


def test_row_limit_allows_within_limit():
    composite = _offline_composite(Policy(row_limit=100))
    result = composite.validate(
        "SELECT customer_id FROM analytics.dim_customers LIMIT 50", SCHEMA
    )
    assert result.ok is True
    assert result.denied is False


# --- schema-invalidity is never a policy matter ------------------------------


def test_schema_invalid_query_is_ordinary_error_not_a_denial():
    # An unknown column is a plain validation error; the policy (which would also
    # deny the query on row_limit) must never run once base validity fails.
    composite = _offline_composite(Policy(deny_columns=("nope",), row_limit=100))
    result = composite.validate("SELECT nope FROM analytics.dim_customers", SCHEMA)
    assert result.ok is False
    assert result.denied is False
    assert not any("policy" in error for error in result.errors)


# --- registry wiring ---------------------------------------------------------


def _profile(tmp_path: Path, policy_path: Path | None = None) -> Profile:
    options: dict[str, object] = {"manifest_path": str(FIXTURE_MANIFEST)}
    if policy_path is not None:
        options["policy"] = str(policy_path)
    return Profile(
        schema_source="dbt-manifest",
        dialect="snowflake",
        validation="sqlglot-offline",
        execution="noop",
        options=options,
    )


def test_no_policy_key_returns_base_validator_unwrapped(tmp_path):
    port = build_validation_port(_profile(tmp_path))
    assert isinstance(port, SqlglotOfflineValidation)
    assert not isinstance(port, PolicyValidation)


def test_policy_key_wraps_base_in_composite(tmp_path):
    policy_path = _policy_file(tmp_path, "deny_columns:\n  - is_internal_account\n")
    port = build_validation_port(_profile(tmp_path, policy_path))
    assert isinstance(port, PolicyValidation)


def test_no_policy_engine_is_unchanged(tmp_path):
    # A query that a policy would deny (no LIMIT, denied column) still passes when
    # no policy is configured - the no-op guarantee.
    engine = build_engine(_profile(tmp_path))
    result = engine.validate(
        "SELECT customer_id FROM analytics.dim_customers WHERE is_internal_account = FALSE"
    )
    assert result.ok is True
    assert result.denied is False


def test_policy_engine_denies_through_the_loop(tmp_path):
    policy_path = _policy_file(tmp_path, "deny_columns:\n  - is_internal_account\n")
    engine = build_engine(_profile(tmp_path, policy_path))
    result = engine.validate(
        "SELECT customer_id FROM analytics.dim_customers WHERE is_internal_account = FALSE"
    )
    assert result.ok is False
    assert result.denied is True


def test_policy_engine_query_raises_validation_failed_carrying_denial(tmp_path):
    policy_path = _policy_file(tmp_path, "row_limit: 10\n")
    engine = build_engine(_profile(tmp_path, policy_path))
    with pytest.raises(ValidationFailed) as caught:
        engine.query("SELECT customer_id FROM analytics.dim_customers")
    assert caught.value.result.denied is True


# --- cliio classification: denial -> 403 / 77, plain invalid -> 422 / 65 -----


def test_classify_denial_maps_to_forbidden_noperm():
    failure = cliio.classify(
        ValidationFailed(ValidationResult(ok=False, errors=("policy: x",), denied=True))
    )
    assert failure.exit_code == cliio.EX_NOPERM == 77
    assert failure.error["code"] == cliio.HTTP_FORBIDDEN == 403


def test_classify_plain_invalid_maps_to_unprocessable_dataerr():
    failure = cliio.classify(
        ValidationFailed(ValidationResult(ok=False, errors=("bad column",)))
    )
    assert failure.exit_code == cliio.EX_DATAERR == 65
    assert failure.error["code"] == cliio.HTTP_UNPROCESSABLE == 422


# --- cli end-to-end: validate ------------------------------------------------


def _cli_profile(tmp_path: Path, policy_body: str) -> str:
    policy_path = _policy_file(tmp_path, policy_body)
    profile = tmp_path / "di0.profile.yml"
    profile.write_text(
        "schema_source: dbt-manifest\n"
        f"manifest_path: {FIXTURE_MANIFEST}\n"
        "dialect: snowflake\n"
        "validation: sqlglot-offline\n"
        "execution: noop\n"
        f"policy: {policy_path}\n"
    )
    return str(profile)


def test_cli_validate_denial_json_is_403_and_77(tmp_path, capsys):
    profile = _cli_profile(tmp_path, "deny_columns:\n  - is_internal_account\n")
    sql = "SELECT customer_id FROM analytics.dim_customers WHERE is_internal_account = FALSE"
    code = cli.main(["--profile", profile, "validate", sql, "--json"])
    env = json.loads(capsys.readouterr().out)
    assert code == cliio.EX_NOPERM == 77
    assert env["ok"] is False
    assert env["error"]["code"] == 403
    assert env["data"]["valid"] is False
    assert env["data"]["errors"]


def test_cli_validate_denial_text_is_77_and_denied_prefix(tmp_path, capsys):
    profile = _cli_profile(tmp_path, "row_limit: 10\n")
    sql = "SELECT customer_id FROM analytics.dim_customers"
    code = cli.main(["--profile", profile, "validate", sql])
    cap = capsys.readouterr()
    assert code == cliio.EX_NOPERM
    assert cap.out == ""
    assert cap.err.startswith("DENIED: ")


def test_cli_validate_plain_invalid_stays_422_and_65(tmp_path, capsys):
    # Same policy profile, but a schema-invalid query: still an ordinary 422 / 65,
    # not a policy denial.
    profile = _cli_profile(tmp_path, "deny_columns:\n  - is_internal_account\n")
    code = cli.main(
        ["--profile", profile, "validate", "SELECT nope FROM analytics.dim_customers", "--json"]
    )
    env = json.loads(capsys.readouterr().out)
    assert code == cliio.EX_DATAERR == 65
    assert env["error"]["code"] == 422


def test_cli_validate_plain_invalid_text_stays_invalid_prefix(tmp_path, capsys):
    profile = _cli_profile(tmp_path, "deny_columns:\n  - is_internal_account\n")
    code = cli.main(["--profile", profile, "validate", "SELECT nope FROM analytics.dim_customers"])
    cap = capsys.readouterr()
    assert code == cliio.EX_DATAERR
    assert cap.err.startswith("INVALID: ")
