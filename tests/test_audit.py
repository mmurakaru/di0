"""Slice #58: the on-by-default, local-only, hash-chained provenance ledger.

`append` builds a verifiable chain; `verify` passes on an intact ledger and
pinpoints the first break on edit/reorder/truncation; a record carries the
expected fields and never a credential or row value (counts only); a ledger
pointed at an unwritable path never raises and never breaks query/author;
`build_engine` attaches a ledger by default and `audit: false` disables it; and
`di0 audit verify` reports intact vs tampered with the right exit code.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from di0 import cli, cliio
from di0.audit import GENESIS_HASH, AuditLedger, NullAudit, verify
from di0.core import Engine
from di0.deliverable import DashboardSpec
from di0.ports import Deliverable, QueryResult
from di0.profile import Profile

FIXTURE_MANIFEST = str(Path(__file__).parent / "fixtures" / "manifest.json")
SAMPLE_SQL = "SELECT customer_id FROM analytics.dim_customers"
LEDGER_NAME = "audit-ledger.jsonl"


def _offline_profile(options: dict | None = None) -> Profile:
    return Profile(
        schema_source="dbt-manifest",
        dialect="snowflake",
        validation="sqlglot-offline",
        execution="noop",
        options={"manifest_path": FIXTURE_MANIFEST, **(options or {})},
    )


class _RowsExecution:
    """A fake row-only execution adapter that returns secret-looking values."""

    supports_authoring = False

    def execute(self, sql: str) -> QueryResult:  # noqa: ARG002 - canned rows
        return QueryResult(
            columns=("secret_token", "amount"),
            rows=(("s3cr3t-alpha", 4242), ("hunter2-bravo", 7)),
        )


class _AuthoringExecution:
    """A fake authoring adapter: never touches the network, always succeeds."""

    supports_authoring = True

    def execute(self, sql: str) -> QueryResult:  # noqa: ARG002 - port signature
        return QueryResult()

    def author(self, dashboard: object) -> Deliverable:  # noqa: ARG002 - canned artifact
        return Deliverable(kind="dashboard", identifier="99", detail={"url": "http://x/dashboard/99"})


def _engine_with(execution: object, audit: object) -> Engine:
    """A real offline engine (schema/dialect/validation) with ports swapped in."""
    from di0.registry import build_engine

    base = build_engine(_offline_profile())
    return dataclasses.replace(base, execution_port=execution, audit=audit)


# --- append / verify: the hash chain -----------------------------------------


def test_append_builds_a_verifiable_chain(tmp_path):
    path = tmp_path / LEDGER_NAME
    ledger = AuditLedger(path)
    for index in range(3):
        ledger.append({"event": "validate", "n": index})
    lines = path.read_text().splitlines()
    assert len(lines) == 3
    first, second, third = (json.loads(line) for line in lines)
    assert first["prev_hash"] == GENESIS_HASH
    assert second["prev_hash"] == first["hash"]
    assert third["prev_hash"] == second["hash"]
    result = verify(path)
    assert result.ok
    assert result.entries == 3
    assert result.broken_at is None


def test_verify_on_missing_ledger_is_ok_and_empty(tmp_path):
    result = verify(tmp_path / "does-not-exist.jsonl")
    assert result.ok
    assert result.entries == 0


def test_verify_detects_edited_middle_record(tmp_path):
    path = tmp_path / LEDGER_NAME
    ledger = AuditLedger(path)
    for index in range(4):
        ledger.append({"event": "query", "n": index})
    lines = path.read_text().splitlines()
    entry = json.loads(lines[1])
    entry["n"] = 999  # tamper the content, leave hash/prev_hash untouched
    lines[1] = json.dumps(entry, sort_keys=True)
    path.write_text("\n".join(lines) + "\n")
    result = verify(path)
    assert not result.ok
    assert result.broken_at == 2  # 1-indexed position of the first break
    assert result.reason


def test_verify_detects_removed_record(tmp_path):
    path = tmp_path / LEDGER_NAME
    ledger = AuditLedger(path)
    for index in range(4):
        ledger.append({"event": "query", "n": index})
    lines = path.read_text().splitlines()
    del lines[1]  # a truncation/reorder breaks the chain at the next entry
    path.write_text("\n".join(lines) + "\n")
    result = verify(path)
    assert not result.ok
    assert result.broken_at == 2


def test_null_audit_writes_nothing(tmp_path):
    NullAudit().append({"event": "validate"})  # no error, no file, no output
    assert list(tmp_path.iterdir()) == []


# --- record shape: fields present, secrets/rows absent -----------------------


def test_record_has_expected_fields_and_never_row_values(tmp_path):
    path = tmp_path / LEDGER_NAME
    engine = _engine_with(_RowsExecution(), AuditLedger(path))
    engine.query(SAMPLE_SQL)
    record = json.loads(path.read_text().splitlines()[-1])
    for key in (
        "event",
        "timestamp",
        "original_sql",
        "composed_sql",
        "schema_hash",
        "validation",
        "target",
        "outcome",
        "di0_version",
        "contract_version",
        "prev_hash",
        "hash",
    ):
        assert key in record, key
    assert record["event"] == "query"
    assert record["outcome"] == {"rows": 2}  # a COUNT, never the values
    assert record["validation"] == {"ok": True, "errors": []}
    assert record["contract_version"] == cliio.CONTRACT_VERSION
    # The schema is digested, not embedded.
    assert record["schema_hash"].startswith("sha256:")
    assert "dim_customers" not in record["schema_hash"]
    # No row value / credential leaks anywhere in the serialized entry.
    blob = json.dumps(record)
    assert "s3cr3t-alpha" not in blob
    assert "hunter2-bravo" not in blob
    assert "4242" not in blob


def test_query_logs_exactly_one_record_no_double_log(tmp_path):
    path = tmp_path / LEDGER_NAME
    engine = _engine_with(_RowsExecution(), AuditLedger(path))
    engine.query(SAMPLE_SQL)
    entries = [line for line in path.read_text().splitlines() if line.strip()]
    assert len(entries) == 1
    assert json.loads(entries[0])["event"] == "query"  # not a stray "validate"


def test_validate_and_author_events_are_recorded(tmp_path):
    path = tmp_path / LEDGER_NAME
    ledger = AuditLedger(path)
    _engine_with(_RowsExecution(), ledger).validate(SAMPLE_SQL)
    (tmp_path / "q.sql").write_text(SAMPLE_SQL)
    spec_path = tmp_path / "dash.yml"
    spec_path.write_text(
        "name: Health\ncollection_id: 1\ntabs:\n  - name: Main\n"
        "    cards:\n      - title: c\n        query: q.sql\n"
    )
    spec = DashboardSpec.from_file(spec_path)
    _engine_with(_AuthoringExecution(), ledger).author(spec, base_dir=tmp_path)
    events = [json.loads(line)["event"] for line in path.read_text().splitlines()]
    assert events == ["validate", "author"]
    author_record = json.loads(path.read_text().splitlines()[-1])
    assert author_record["outcome"] == {"kind": "dashboard", "identifier": "99"}
    assert verify(path).ok


# --- non-fatal: an unwritable ledger never breaks the operation --------------


def _unwritable_path(tmp_path: Path) -> Path:
    blocker = tmp_path / "blocker"
    blocker.write_text("this is a file, not a directory")
    return blocker / "sub" / LEDGER_NAME  # mkdir under a file raises -> swallowed


def test_unwritable_ledger_never_raises_or_breaks_query(tmp_path):
    bad = _unwritable_path(tmp_path)
    engine = _engine_with(_RowsExecution(), AuditLedger(bad, warn=False))
    result = engine.query(SAMPLE_SQL)  # must not raise
    assert len(result.rows) == 2
    assert not bad.exists()


def test_unwritable_ledger_never_raises_or_breaks_author(tmp_path):
    bad = _unwritable_path(tmp_path)
    (tmp_path / "q.sql").write_text(SAMPLE_SQL)
    spec_path = tmp_path / "dash.yml"
    spec_path.write_text(
        "name: Health\ncollection_id: 1\ntabs:\n  - name: Main\n"
        "    cards:\n      - title: c\n        query: q.sql\n"
    )
    spec = DashboardSpec.from_file(spec_path)
    engine = _engine_with(_AuthoringExecution(), AuditLedger(bad, warn=False))
    deliverable = engine.author(spec, base_dir=tmp_path)  # must not raise
    assert deliverable.identifier == "99"
    assert not bad.exists()


def test_ledger_write_failure_emits_one_line_warning(tmp_path, capsys):
    AuditLedger(_unwritable_path(tmp_path)).append({"event": "validate"})
    err = capsys.readouterr().err
    assert err.count("\n") == 1  # exactly one line
    assert "audit" in err.lower()


# --- registry wiring: on by default, disable with audit: false ---------------


def test_build_engine_attaches_ledger_by_default(tmp_path, monkeypatch):
    from di0.registry import build_engine

    monkeypatch.setenv("DI0_WORKSPACE", str(tmp_path))
    engine = build_engine(_offline_profile())
    assert isinstance(engine.audit, AuditLedger)
    engine.validate(SAMPLE_SQL)
    ledger_file = tmp_path / ".di0" / "audit" / "audit.jsonl"
    assert ledger_file.exists()
    assert verify(ledger_file).ok


def test_audit_false_disables_the_ledger(tmp_path):
    from di0.registry import build_engine

    engine = build_engine(_offline_profile({"audit": False}))
    assert isinstance(engine.audit, NullAudit)


def test_audit_path_profile_key_overrides_default(tmp_path):
    from di0.registry import build_engine

    custom = tmp_path / "ledgers" / "provenance.jsonl"
    engine = build_engine(_offline_profile({"audit_path": str(custom)}))
    engine.validate(SAMPLE_SQL)
    assert custom.exists()
    assert verify(custom).ok


def test_raw_engine_construction_defaults_to_null_audit():
    from di0.registry import build_engine

    base = build_engine(_offline_profile())
    raw = Engine(
        schema_port=base.schema_port,
        dialect_port=base.dialect_port,
        validation_port=base.validation_port,
        execution_port=base.execution_port,
    )
    assert isinstance(raw.audit, NullAudit)
    assert raw.validate(SAMPLE_SQL).ok  # unaffected


# --- CLI: di0 audit verify ---------------------------------------------------


def _fill_ledger(path: Path, count: int = 3) -> AuditLedger:
    ledger = AuditLedger(path)
    for index in range(count):
        ledger.append({"event": "validate", "n": index})
    return ledger


def test_audit_is_a_contract_command():
    assert "audit" in cli._CONTRACT_COMMANDS


def test_cli_audit_verify_intact_text(tmp_path, capsys):
    path = tmp_path / LEDGER_NAME
    _fill_ledger(path)
    code = cli.main(["audit", "verify", "--path", str(path)])
    assert code == cliio.EX_OK
    assert "OK" in capsys.readouterr().out


def test_cli_audit_verify_intact_json(tmp_path, capsys):
    path = tmp_path / LEDGER_NAME
    _fill_ledger(path)
    code = cli.main(["audit", "verify", "--path", str(path), "--json"])
    env = json.loads(capsys.readouterr().out)
    assert code == cliio.EX_OK
    assert env["command"] == "audit"
    assert env["ok"] is True
    assert env["data"]["entries"] == 3
    assert env["data"]["broken_at"] is None


def test_cli_audit_verify_tampered_json(tmp_path, capsys):
    path = tmp_path / LEDGER_NAME
    _fill_ledger(path)
    lines = path.read_text().splitlines()
    entry = json.loads(lines[1])
    entry["n"] = 999
    lines[1] = json.dumps(entry, sort_keys=True)
    path.write_text("\n".join(lines) + "\n")
    code = cli.main(["audit", "verify", "--path", str(path), "--json"])
    env = json.loads(capsys.readouterr().out)
    assert code == cliio.EX_DATAERR
    assert env["ok"] is False
    assert env["data"]["broken_at"] == 2
    assert env["error"]["code"] == 422


def test_cli_audit_verify_tampered_text(tmp_path, capsys):
    path = tmp_path / LEDGER_NAME
    _fill_ledger(path)
    lines = path.read_text().splitlines()
    entry = json.loads(lines[0])
    entry["n"] = -1
    lines[0] = json.dumps(entry, sort_keys=True)
    path.write_text("\n".join(lines) + "\n")
    code = cli.main(["audit", "verify", "--path", str(path)])
    assert code == cliio.EX_DATAERR
    assert "BROKEN" in capsys.readouterr().err
