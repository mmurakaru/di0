"""The validation loop - di0's actual IP.

resolve refs (SchemaPort) -> compose SQL (DialectPort) -> validate against the
schema (ValidationPort) -> only then execute (ExecutionPort).

The loop is warehouse-blind: it holds ports, never adapters, and never a single
physical table, column, or dialect literal.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from di0.audit import Audit, NullAudit, build_record
from di0.deliverable import (
    DashboardSpec,
    ResolvedCard,
    ResolvedDashboard,
    ResolvedTab,
)
from di0.ports import (
    DEFAULT_CAPABILITIES,
    Capabilities,
    CombinePort,
    Deliverable,
    DialectPort,
    ExecutionPort,
    QueryResult,
    Schema,
    SchemaPort,
    ValidationPort,
    ValidationResult,
)
from di0.profile import Profile
from di0.reconcile import ReconcileSpec


def _validation_form(sql: str) -> str:
    """Neutralize template variables so a parameterized query still validates.

    Optional ``[[ ... ]]`` blocks are dropped and ``{{var}}`` placeholders become
    NULL, yielding SQL the validator can parse. The original text is authored, so
    the tags a dashboard filter wires to are preserved.
    """
    without_optional = re.sub(r"\[\[.*?\]\]", " ", sql, flags=re.DOTALL)
    return re.sub(r"\{\{[^}]+\}\}", "NULL", without_optional)


class ValidationFailed(Exception):
    def __init__(self, result: ValidationResult) -> None:
        super().__init__("; ".join(result.errors) or "validation failed")
        self.result = result


class AuthoringUnsupported(Exception):
    """Raised when a deliverable is requested of a row-only execution adapter."""


class CapabilityError(Exception):
    """Raised when a resolved dashboard exceeds the adapter's declared surface.

    Lists every unsupported item at once - each with the card it belongs to and
    what is unsupported - and is raised before any artifact is created, so the
    author never learns of one gap only to hit the next on the next run.
    """

    def __init__(self, unsupported: tuple[str, ...]) -> None:
        super().__init__(
            "the execution adapter cannot author this deliverable: "
            + "; ".join(unsupported)
        )
        self.unsupported = tuple(unsupported)


def _capability_gaps(dashboard: ResolvedDashboard, capabilities: Capabilities) -> list[str]:
    """Every way a resolved dashboard exceeds an adapter's authoring surface.

    Generic and target-blind: a card's display must be in `displays` (unless that
    is None, meaning any); text cards require `text_cards`; dashboard-level filters
    require `parameters`. Empty list means the whole spec is renderable.
    """
    gaps: list[str] = []
    for tab in dashboard.tabs:
        for card in tab.cards:
            if card.is_text:
                if not capabilities.text_cards:
                    label = card.title or card.text.splitlines()[0].strip()
                    gaps.append(f"card {label!r}: text cards are unsupported")
            elif capabilities.displays is not None and card.display not in capabilities.displays:
                gaps.append(f"card {card.title!r}: display {card.display!r} is unsupported")
    if dashboard.parameters and not capabilities.parameters:
        gaps.append("dashboard parameters are unsupported")
    return gaps


@dataclass(frozen=True)
class Engine:
    schema_port: SchemaPort
    dialect_port: DialectPort
    validation_port: ValidationPort
    execution_port: ExecutionPort
    # Off by default at the dataclass level: a raw ``Engine(...)`` records nothing,
    # so every existing construction is unaffected. The registry attaches a real
    # ledger for the CLI/normal path.
    audit: Audit = field(default_factory=NullAudit)

    def _resolve_and_validate(self, sql: str) -> tuple[str, Schema, ValidationResult]:
        """The shared, unlogged core of validate/query: compose, resolve, validate."""
        composed = self.dialect_port.compose(sql)
        schema = self.schema_port.resolve()
        return composed, schema, self.validation_port.validate(composed, schema)

    def _record(
        self,
        event: str,
        original_sql: str,
        composed_sql: str,
        schema: Schema | None,
        result: ValidationResult,
        outcome: dict | None = None,
    ) -> None:
        """Append one provenance entry. Never raises: provenance is not the operation."""
        if isinstance(self.audit, NullAudit):
            return  # the default sink does nothing; skip the record entirely
        try:
            self.audit.append(
                build_record(
                    event=event,
                    original_sql=original_sql,
                    composed_sql=composed_sql,
                    schema=schema,
                    validation=result,
                    target=type(self.execution_port).__name__,
                    outcome=outcome,
                )
            )
        except Exception:  # noqa: BLE001 - a ledger failure must never fail an operation
            pass

    def validate(self, sql: str) -> ValidationResult:
        composed, schema, result = self._resolve_and_validate(sql)
        self._record("validate", sql, composed, schema, result)
        return result

    def query(self, sql: str) -> QueryResult:
        # Runs the validation core directly (not the public validate) so a query
        # logs exactly one "query" entry, never a stray "validate" one too.
        composed, schema, result = self._resolve_and_validate(sql)
        if not result.ok:
            self._record("query", sql, composed, schema, result)
            raise ValidationFailed(result)
        output = self.execution_port.execute(composed)
        self._record("query", sql, composed, schema, result, outcome={"rows": len(output.rows)})
        return output

    def author(self, spec: DashboardSpec, base_dir: Path | None = None) -> Deliverable:
        """Validate every query in a dashboard spec, then author the artifact.

        Authoring is refused unless the execution adapter supports it, and no card
        is created unless every query in the spec is valid.
        """
        if not self.execution_port.supports_authoring:
            raise AuthoringUnsupported(
                "the configured execution adapter cannot author deliverables"
            )
        root = Path(base_dir) if base_dir is not None else Path.cwd()
        schema = self.schema_port.resolve()
        original_sqls: list[str] = []
        composed_sqls: list[str] = []
        resolved_tabs: list[ResolvedTab] = []
        for tab in spec.tabs:
            resolved_cards: list[ResolvedCard] = []
            for card in tab.cards:
                if card.is_text:
                    composed = ""  # text cards carry no SQL and are not validated
                elif "{{" in (sql := (root / card.query).read_text()):
                    # Parameterized card: validate a variable-free form, but author the
                    # query verbatim so Metabase keeps the tags the filters wire to.
                    result = self.validation_port.validate(
                        self.dialect_port.compose(_validation_form(sql)), schema
                    )
                    if not result.ok:
                        raise ValidationFailed(result)
                    composed = sql
                else:
                    composed = self.dialect_port.compose(sql)
                    result = self.validation_port.validate(composed, schema)
                    if not result.ok:
                        raise ValidationFailed(result)
                if not card.is_text:
                    original_sqls.append(sql)
                    composed_sqls.append(composed)
                resolved_cards.append(
                    ResolvedCard(
                        title=card.title,
                        sql=composed,
                        text=card.text,
                        display=card.display,
                        size_x=card.size_x,
                        size_y=card.size_y,
                        row=card.row,
                        col=card.col,
                        description=card.description,
                        x_label=card.x_label,
                        y_label=card.y_label,
                        viz=card.viz,
                        width=card.width,
                        height=card.height,
                        native=card.native,
                        params=card.params,
                        field_filters=card.field_filters,
                    )
                )
            resolved_tabs.append(ResolvedTab(name=tab.name, cards=tuple(resolved_cards)))
        dashboard = ResolvedDashboard(
            name=spec.name,
            tabs=tuple(resolved_tabs),
            collection_id=spec.collection_id,
            collection=spec.collection,
            replace=spec.replace,
            organize_by_tab=spec.organize_by_tab,
            own_collection=spec.own_collection,
            parameters=spec.parameters,
            native=spec.native,
        )
        # Refuse before creating anything: if the spec asks for more than the
        # adapter declares it can render, name every gap and stop here.
        capabilities = getattr(self.execution_port, "capabilities", DEFAULT_CAPABILITIES)
        gaps = _capability_gaps(dashboard, capabilities)
        if gaps:
            raise CapabilityError(tuple(gaps))
        deliverable = self.execution_port.author(dashboard)
        # One record for the whole authored deliverable: its queries validated, so
        # record an ok verdict and the artifact id as the outcome (never row data).
        self._record(
            "author",
            "\n".join(original_sqls),
            "\n".join(composed_sqls),
            schema,
            ValidationResult(ok=True),
            outcome={"kind": deliverable.kind, "identifier": deliverable.identifier},
        )
        return deliverable

    def validate_paths(self, paths: list[Path]) -> list[tuple[Path, ValidationResult]]:
        """Validate every SQL file against the schema, resolved once.

        A file that fails to parse or qualify yields an invalid result rather than
        raising, so a single bad query never hides the rest of the report.
        """
        schema = self.schema_port.resolve()
        results: list[tuple[Path, ValidationResult]] = []
        for path in paths:
            try:
                composed = self.dialect_port.compose(path.read_text())
                result = self.validation_port.validate(composed, schema)
            except Exception as error:  # noqa: BLE001 - report, do not abort the run
                result = ValidationResult(ok=False, errors=(str(error).strip(),))
            results.append((path, result))
        return results


def _distinct_keys(result: QueryResult, column: str | None) -> list:
    """Distinct, non-null values of a dependency column (case-insensitive match)."""
    if not column:
        raise ValueError("a dependent reconcile query must set `keys`")
    # Column casing varies by source (Snowflake upper-cases, Postgres lower-cases).
    by_lower = {c.lower(): c for c in result.columns}
    actual = by_lower.get(column.lower())
    if actual is None:
        raise ValueError(f"dependency has no key column {column!r} (has {result.columns})")
    index = result.columns.index(actual)
    seen: list = []
    unique: set = set()
    for row in result.rows:
        value = row[index]
        if value is None or value in unique:
            continue
        unique.add(value)
        seen.append(value)
    return seen


def _in_list(values: list) -> str:
    """A batch of key values as a SQL IN-list of literals ('NULL' when empty)."""
    if not values:
        return "NULL"

    def literal(value: object) -> str:
        if isinstance(value, (int, float)):
            return repr(value)
        return "'" + str(value).replace("'", "''") + "'"

    return ", ".join(literal(value) for value in values)


def _concat(results: list[QueryResult]) -> QueryResult:
    columns: tuple = ()
    rows: list = []
    for result in results:
        if result.columns:
            columns = result.columns
        rows.extend(result.rows)
    return QueryResult(columns=columns, rows=tuple(rows))


def _run_query(engine: Engine, template: str, query, keys: list) -> QueryResult:
    """Run a query, injecting keys - in chunks when a key set is too large for one IN-list."""
    if not query.depends_on:
        return engine.query(template)
    size = query.chunk if query.chunk and query.chunk > 0 else len(keys) or 1
    batches = [keys[i : i + size] for i in range(0, len(keys), size)] or [[]]
    return _concat([engine.query(template.replace("{keys}", _in_list(batch))) for batch in batches])


def reconcile(
    spec: ReconcileSpec,
    base_dir: Path | None,
    engine_factory: Callable[[Profile], Engine],
    combine_port: CombinePort,
) -> QueryResult:
    """Answer a cross-source question: run one validated query per source, then combine.

    Independent queries run first; a query with `depends_on` runs after that
    dependency and has its `{keys}` placeholder filled with the dependency's distinct
    key values - so a huge source is fetched only for the keys another source needs,
    not in full. The combine joins the fetched results locally through the CombinePort;
    the cross-source join never runs in any source warehouse.
    """
    root = Path(base_dir) if base_dir is not None else Path.cwd()
    tables: dict[str, QueryResult] = {}
    pending = list(spec.queries)
    for query in pending:
        if query.source not in spec.sources:
            raise ValueError(
                f"reconcile query {query.name!r} names unknown source {query.source!r}"
            )
    made_progress = True
    while pending and made_progress:
        made_progress = False
        for query in list(pending):
            if query.depends_on and query.depends_on not in tables:
                continue  # dependency not ready yet
            template = (root / query.query).read_text()
            keys = _distinct_keys(tables[query.depends_on], query.keys) if query.depends_on else []
            engine = engine_factory(Profile.from_dict(spec.sources[query.source]))
            tables[query.name] = _run_query(engine, template, query, keys)
            pending.remove(query)
            made_progress = True
    if pending:
        raise ValueError(
            "unresolved reconcile dependencies (missing or cyclic): "
            + ", ".join(q.name for q in pending)
        )
    combine_sql = (root / spec.combine).read_text()
    return combine_port.combine(tables, combine_sql)
