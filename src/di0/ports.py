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

    `execute` is portable across every adapter. Authoring deliverables is an
    optional, BI-tool-specific capability declared by `supports_authoring` and
    implemented through the `AuthoringPort` capability below.
    """

    def execute(self, sql: str) -> QueryResult: ...

    @property
    def supports_authoring(self) -> bool: ...


@runtime_checkable
class CombinePort(Protocol):
    """Combine result sets fetched from several sources into one, locally.

    The cross-source join happens in di0's own process (not in any warehouse),
    over the already-fetched rows, expressed as raw SQL - so reconcile keeps di0's
    'real SQL, no DSL' invariant across sources.
    """

    def combine(self, tables: dict[str, QueryResult], sql: str) -> QueryResult: ...


@runtime_checkable
class AuthoringPort(Protocol):
    """Optional capability: author a BI artifact from validated, resolved queries.

    The argument is a resolved deliverable (validated SQL plus layout); the return
    value identifies the created artifact. Only BI execution adapters implement
    this; row-only adapters do not.
    """

    def author(self, dashboard: object) -> Deliverable: ...
