"""A shared, reusable contract suite for di0 adapters.

Any adapter author - first-party or third-party - runs these per-port checks to
prove an adapter satisfies the port it plugs into, and an agent-adapted adapter
re-runs them as a trust gate before the change is trusted. Each check speaks only
to the generic port protocols and to fixtures the caller supplies (a sample
schema, sample SQL, a resolved dashboard); it names no data store, dialect, or
tool, so the kit stays as agnostic as the core it guards.

Run it two ways: import a `check_*` function into a test and point it at your
adapter with your own fixtures, or drive `di0 conformance --adapter <reference>`
to import an adapter by reference and run every port check it is shaped for.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass

from di0.core import (
    CapabilityError,
    Engine,
    _validation_form,  # the same neutralization the core applies before validating
)
from di0.ports import (
    DEFAULT_CAPABILITIES,
    Capabilities,
    Deliverable,
    QueryResult,
    ValidationResult,
)

# A trivial statement every dialect parses, used by the CLI when it has no
# caller-supplied query to probe an adapter with.
DEFAULT_SAMPLE_SQL = "SELECT 1"


def check_schema_port(schema_port) -> dict:
    """SchemaPort: resolve() yields a nested namespace/table/column/type mapping of
    strings, and is idempotent across calls."""
    resolved = schema_port.resolve()
    assert isinstance(resolved, dict), "resolve() must return a mapping"
    for namespace, tables in resolved.items():
        assert isinstance(namespace, str), "namespace keys must be strings"
        assert isinstance(tables, dict), "each namespace must map to a table mapping"
        for table, columns in tables.items():
            assert isinstance(table, str), "table keys must be strings"
            assert isinstance(columns, dict), "each table must map to a column mapping"
            for column, column_type in columns.items():
                assert isinstance(column, str), "column keys must be strings"
                assert isinstance(column_type, str), "column types must be strings"
    assert schema_port.resolve() == resolved, "resolve() must be idempotent"
    return resolved


def check_dialect_port(dialect_port, sql: str) -> str:
    """DialectPort: compose() returns a non-empty string and is stable when re-run on
    already-composed SQL."""
    composed = dialect_port.compose(sql)
    assert isinstance(composed, str), "compose() must return a string"
    assert composed.strip(), "compose() must return non-empty SQL"
    assert dialect_port.compose(composed) == composed, (
        "compose() must be stable on already-composed SQL"
    )
    return composed


def check_validation_port(
    validation_port,
    schema: dict,
    *,
    valid_sql: str,
    invalid_sql: str,
    parameterized_sql: str,
) -> None:
    """ValidationPort: accepts a valid query against the schema, rejects an unknown
    table or column with at least one error, and accepts a parameterized query once
    the core neutralizes it."""
    accepted = validation_port.validate(valid_sql, schema)
    assert isinstance(accepted, ValidationResult), "validate() must return a ValidationResult"
    assert accepted.ok is True, "a valid query must be accepted"

    rejected = validation_port.validate(invalid_sql, schema)
    assert rejected.ok is False, "an unknown table or column must be rejected"
    assert rejected.errors, "a rejection must carry at least one error"

    # The core feeds the validator a neutralized form of a parameterized query, so
    # the tags a dashboard filter wires to survive validation; the port must accept it.
    neutralized = _validation_form(parameterized_sql)
    parameterized = validation_port.validate(neutralized, schema)
    assert parameterized.ok is True, "a neutralized parameterized query must be accepted"


def check_capabilities(capabilities) -> None:
    """A well-formed Capabilities descriptor: every field has the declared shape."""
    assert isinstance(capabilities, Capabilities), "capabilities must be a Capabilities"
    assert isinstance(capabilities.authors, bool), "authors must be a bool"
    assert capabilities.displays is None or isinstance(capabilities.displays, frozenset), (
        "displays must be None or a frozenset"
    )
    assert isinstance(capabilities.text_cards, bool), "text_cards must be a bool"
    assert isinstance(capabilities.parameters, bool), "parameters must be a bool"
    assert capabilities.grid_columns is None or isinstance(capabilities.grid_columns, int), (
        "grid_columns must be None or an int"
    )


def check_execution_port(execution_port, *, valid_sql: str, resolved_dashboard=None) -> None:
    """ExecutionPort: execute() returns a tuple-shaped QueryResult, supports_authoring
    is a bool, and the declared capabilities are well-formed. When the adapter authors
    and a resolved dashboard is supplied, the authoring capability is exercised too."""
    result = execution_port.execute(valid_sql)
    assert isinstance(result, QueryResult), "execute() must return a QueryResult"
    assert isinstance(result.columns, tuple), "QueryResult.columns must be a tuple"
    assert isinstance(result.rows, tuple), "QueryResult.rows must be a tuple"
    for row in result.rows:
        assert isinstance(row, tuple), "each row must be a tuple"

    assert isinstance(execution_port.supports_authoring, bool), "supports_authoring must be a bool"

    capabilities = getattr(execution_port, "capabilities", DEFAULT_CAPABILITIES)
    check_capabilities(capabilities)

    if execution_port.supports_authoring:
        assert capabilities.authors is True, (
            "an adapter that supports authoring must declare capabilities.authors=True"
        )
        if resolved_dashboard is not None:
            check_authoring(execution_port, resolved_dashboard)


def check_authoring(execution_port, resolved_dashboard) -> Deliverable:
    """The optional authoring capability: author() returns an identified Deliverable."""
    assert execution_port.supports_authoring is True, "adapter does not support authoring"
    capabilities = getattr(execution_port, "capabilities", DEFAULT_CAPABILITIES)
    assert capabilities.authors is True, "an authoring adapter must declare authors=True"
    deliverable = execution_port.author(resolved_dashboard)
    assert isinstance(deliverable, Deliverable), "author() must return a Deliverable"
    assert isinstance(deliverable.kind, str) and deliverable.kind, "a deliverable needs a kind"
    assert isinstance(deliverable.identifier, str) and deliverable.identifier, (
        "a deliverable needs an identifier"
    )
    return deliverable


class _EmptySchema:
    def resolve(self) -> dict:
        return {}


class _IdentityDialect:
    def compose(self, sql: str) -> str:
        return sql


class _AcceptingValidation:
    def validate(self, sql: str, schema: dict) -> ValidationResult:  # noqa: ARG002 - port stub
        return ValidationResult(ok=True)


class _AuthorSpy:
    """Wraps an execution adapter, recording whether author() is ever reached."""

    def __init__(self, execution_port, calls: list) -> None:
        self._execution_port = execution_port
        self._calls = calls

    def execute(self, sql: str) -> QueryResult:
        return self._execution_port.execute(sql)

    @property
    def supports_authoring(self) -> bool:
        return self._execution_port.supports_authoring

    @property
    def capabilities(self) -> Capabilities:
        return getattr(self._execution_port, "capabilities", DEFAULT_CAPABILITIES)

    def author(self, dashboard) -> Deliverable:
        self._calls.append(dashboard)
        return self._execution_port.author(dashboard)


def check_refuses_before_side_effect(execution_port, *, spec, base_dir) -> None:
    """The #66 trust gate: a spec exceeding the adapter's declared surface is refused
    before author() runs, so nothing is created against a target that cannot render it.

    Drives the real refuse-before-create path with permissive stub ports and a spy on
    author(); the spec must exceed the adapter's declared capabilities."""
    calls: list = []
    engine = Engine(
        schema_port=_EmptySchema(),
        dialect_port=_IdentityDialect(),
        validation_port=_AcceptingValidation(),
        execution_port=_AuthorSpy(execution_port, calls),
    )
    try:
        engine.author(spec, base_dir=base_dir)
    except CapabilityError:
        pass
    else:
        raise AssertionError("an over-reaching spec must be refused, not authored")
    assert not calls, "author() ran despite an over-reaching spec"


def check_combine_port(combine_port, *, tables: dict, sql: str) -> QueryResult:
    """CombinePort: combine() joins already-fetched result sets locally and returns a
    tuple-shaped QueryResult."""
    result = combine_port.combine(tables, sql)
    assert isinstance(result, QueryResult), "combine() must return a QueryResult"
    assert isinstance(result.columns, tuple), "combined columns must be a tuple"
    assert isinstance(result.rows, tuple), "combined rows must be a tuple"
    for row in result.rows:
        assert isinstance(row, tuple), "each combined row must be a tuple"
    return result


# --- CLI wrapper support -----------------------------------------------------


@dataclass(frozen=True)
class CheckOutcome:
    """The result of running one port's checks against an adapter (for the CLI)."""

    port: str
    passed: bool
    detail: str


def load_adapter(reference: str):
    """Import an adapter from a `module:attribute` (or dotted `module.attribute`)
    reference. The attribute is a class or a zero-argument factory; a callable is
    invoked to get the instance, so an author points the CLI straight at their adapter."""
    module_name, separator, attribute = reference.partition(":")
    if not separator:
        module_name, _, attribute = reference.rpartition(".")
    if not module_name or not attribute:
        raise ValueError(
            f"adapter reference {reference!r} must be 'module:attribute' or dotted"
        )
    target = getattr(importlib.import_module(module_name), attribute)
    return target() if callable(target) else target


def _smoke_combine(combine_port) -> None:
    probe = QueryResult(columns=("n",), rows=((1,), (2,)))
    check_combine_port(combine_port, tables={"probe": probe}, sql="SELECT n FROM probe")


def run_cli_checks(adapter, *, sql: str = DEFAULT_SAMPLE_SQL) -> list[CheckOutcome]:
    """Run every port check the adapter is shaped for, capturing each outcome.

    A port is recognised by the method that defines it, so the CLI can prove an
    ExecutionPort (and any other port resolvable from a sample query) without a full
    fixture set. A failed check is captured as a non-passing outcome, not raised."""
    plans = []
    if hasattr(adapter, "execute"):
        plans.append(("ExecutionPort", lambda: check_execution_port(adapter, valid_sql=sql)))
    if hasattr(adapter, "resolve"):
        plans.append(("SchemaPort", lambda: check_schema_port(adapter)))
    if hasattr(adapter, "compose"):
        plans.append(("DialectPort", lambda: check_dialect_port(adapter, sql)))
    if hasattr(adapter, "combine"):
        plans.append(("CombinePort", lambda: _smoke_combine(adapter)))
    if not plans:
        raise ValueError(
            "the object satisfies no known di0 port (no execute/resolve/compose/combine method)"
        )
    outcomes: list[CheckOutcome] = []
    for port, run in plans:
        try:
            run()
        except Exception as error:  # noqa: BLE001 - a failed check is a reported outcome
            outcomes.append(CheckOutcome(port, False, str(error) or error.__class__.__name__))
        else:
            outcomes.append(CheckOutcome(port, True, "contract satisfied"))
    return outcomes
