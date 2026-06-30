"""The four ports that define di0's agnostic core.

A port is an abstraction the core depends on; an adapter is a concrete driver
plugged into it. The core names no warehouse, no dialect, and no physical table
or column - all of that is resolved or injected through these ports at the edges.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

# A resolved schema: namespace -> table -> column -> type.
# Deliberately a plain nested mapping so no adapter shape leaks into the core.
Schema = dict[str, dict[str, dict[str, str]]]


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class QueryResult:
    columns: tuple[str, ...] = ()
    rows: tuple[tuple[object, ...], ...] = ()


@dataclass(frozen=True)
class Deliverable:
    """An authored artifact (e.g. a dashboard) identified by the execution target."""

    kind: str
    identifier: str
    detail: dict[str, object] = field(default_factory=dict)


@runtime_checkable
class SchemaPort(Protocol):
    """Resolve tables, columns, joins, and metrics from a schema source."""

    def resolve(self) -> Schema: ...


@runtime_checkable
class DialectPort(Protocol):
    """Render / normalize SQL for a target dialect."""

    def compose(self, sql: str) -> str: ...


@runtime_checkable
class ValidationPort(Protocol):
    """Prove a query against the resolved schema before it is allowed to run."""

    def validate(self, sql: str, schema: Schema) -> ValidationResult: ...


@runtime_checkable
class ExecutionPort(Protocol):
    """Run validated SQL and return rows.

    `execute` is portable across every adapter. `author` is an optional,
    BI-tool-specific capability; adapters that cannot author deliverables
    simply do not implement it (see `supports_authoring`).
    """

    def execute(self, sql: str) -> QueryResult: ...

    @property
    def supports_authoring(self) -> bool: ...
