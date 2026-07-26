"""Slice #58: a local-only, hash-chained provenance ledger.

Each di0 operation (validate/query/author) appends one JSON line recording what
ran, whether it validated, and the outcome - never credentials, row values, or
PII. Every entry carries the hash of the entry before it, so any edit, reorder,
or truncation of the file is detectable by re-walking the chain from the genesis
sentinel. Writes are wrapped so a ledger failure never fails the operation it
records; ``NullAudit`` offers the same interface for callers that want no ledger.

The ledger is a generic dict sink: it names no warehouse, dialect, or table, so
this module lives inside the guard-scanned core untouched.
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, runtime_checkable

from di0.ports import Schema, ValidationResult

# The prev_hash of the first entry: a fixed 64-char sentinel, so a genuine first
# record is distinguishable from a chain that has been truncated down to one line.
GENESIS_HASH = "0" * 64

# The one field whose value is a hash of everything else on the line; excluded
# when (re)computing that hash so the digest is over the record plus prev_hash.
_HASH_FIELD = "hash"


@runtime_checkable
class Audit(Protocol):
    """A sink that records one provenance entry per di0 operation."""

    def append(self, record: dict) -> None: ...


def _canonical(value: object) -> bytes:
    """Deterministic bytes for a value: sorted keys, no whitespace drift."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def schema_digest(schema: Schema | None) -> str:
    """A stable digest of the resolved schema - the schema itself is never stored."""
    return "sha256:" + _digest(schema or {})


def _di0_version() -> str:
    try:
        from importlib.metadata import version

        return version("di0")
    except Exception:  # noqa: BLE001 - a missing distribution must not break a write
        return "unknown"


def _contract_version() -> str:
    # Imported lazily: cliio imports core, and core imports this module.
    from di0.cliio import CONTRACT_VERSION

    return CONTRACT_VERSION


def build_record(
    *,
    event: str,
    original_sql: str,
    composed_sql: str,
    schema: Schema | None,
    validation: ValidationResult,
    target: str,
    outcome: dict | None = None,
) -> dict:
    """Assemble one provenance record - identifiers and counts only, no data.

    Captures the event, the original and composed SQL, a digest of the resolved
    schema, the validation verdict, the execution target's identifier, and the
    outcome (a row count or a deliverable id). It never carries credentials, row
    values, or PII.
    """
    return {
        "event": event,
        "timestamp": datetime.now(UTC).isoformat(),
        "original_sql": original_sql,
        "composed_sql": composed_sql,
        "schema_hash": schema_digest(schema),
        "validation": {"ok": bool(validation.ok), "errors": list(validation.errors)},
        "target": target,
        "outcome": outcome,
        "di0_version": _di0_version(),
        "contract_version": _contract_version(),
    }


class NullAudit:
    """A ledger that records nothing; the default so raw ``Engine(...)`` stays inert."""

    def append(self, record: dict) -> None:  # noqa: ARG002 - no-op sink
        return None


@dataclass
class AuditLedger:
    """A hash-chained JSONL ledger. Every write is best-effort and never fatal."""

    path: Path
    warn: bool = True  # emit a one-line stderr warning when a write is skipped

    def append(self, record: dict) -> None:
        """Chain and append one record; swallow any I/O error so callers never fail."""
        try:
            self._append(record)
        except Exception as error:  # noqa: BLE001 - a ledger write must never fail an operation
            if self.warn:
                print(f"di0: audit ledger write skipped ({error})", file=sys.stderr)

    def _append(self, record: dict) -> None:
        path = Path(self.path)
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = dict(record)
        entry["prev_hash"] = self._last_hash(path)
        entry[_HASH_FIELD] = _digest(entry)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True, default=str) + "\n")

    @staticmethod
    def _last_hash(path: Path) -> str:
        if not path.exists():
            return GENESIS_HASH
        last = GENESIS_HASH
        for line in path.read_text().splitlines():
            if line.strip():
                last = json.loads(line).get(_HASH_FIELD, last)
        return last


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    entries: int
    broken_at: int | None = None  # 1-indexed position of the first broken entry
    reason: str = ""


def verify(path: str | Path) -> VerifyResult:
    """Walk the chain and report OK or the first entry that fails to verify.

    An entry breaks the chain when its ``prev_hash`` does not match the previous
    entry's hash (reorder / truncation) or when its recomputed hash does not match
    its stored hash (edit). A missing or empty ledger is a trivially intact chain.
    """
    path = Path(path)
    if not path.exists():
        return VerifyResult(ok=True, entries=0)
    try:
        lines = path.read_text().splitlines()
    except OSError as error:
        return VerifyResult(ok=False, entries=0, reason=f"ledger unreadable ({error})")

    previous_hash = GENESIS_HASH
    entry_number = 0
    for line in lines:
        if not line.strip():
            continue
        entry_number += 1
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            return VerifyResult(False, entry_number, entry_number, "entry is not valid JSON")
        if entry.get("prev_hash") != previous_hash:
            return VerifyResult(
                False, entry_number, entry_number, "prev_hash does not chain to the previous entry"
            )
        body = {key: value for key, value in entry.items() if key != _HASH_FIELD}
        if _digest(body) != entry.get(_HASH_FIELD):
            return VerifyResult(
                False, entry_number, entry_number, "entry hash does not match its contents"
            )
        previous_hash = entry[_HASH_FIELD]
    return VerifyResult(ok=True, entries=entry_number)
