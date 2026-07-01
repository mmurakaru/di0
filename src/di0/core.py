"""The validation loop - di0's actual IP.

resolve refs (SchemaPort) -> compose SQL (DialectPort) -> validate against the
schema (ValidationPort) -> only then execute (ExecutionPort).

The loop is warehouse-blind: it holds ports, never adapters, and never a single
physical table, column, or dialect literal.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from di0.deliverable import (
    DashboardSpec,
    ResolvedCard,
    ResolvedDashboard,
    ResolvedTab,
)
from di0.ports import (
    CombinePort,
    Deliverable,
    DialectPort,
    ExecutionPort,
    QueryResult,
    SchemaPort,
    ValidationPort,
    ValidationResult,
)
from di0.profile import Profile
from di0.reconcile import ReconcileSpec


class ValidationFailed(Exception):
    def __init__(self, result: ValidationResult) -> None:
        super().__init__("; ".join(result.errors) or "validation failed")
        self.result = result


class AuthoringUnsupported(Exception):
    """Raised when a deliverable is requested of a row-only execution adapter."""


@dataclass(frozen=True)
class Engine:
    schema_port: SchemaPort
    dialect_port: DialectPort
    validation_port: ValidationPort
    execution_port: ExecutionPort

    def validate(self, sql: str) -> ValidationResult:
        composed = self.dialect_port.compose(sql)
        schema = self.schema_port.resolve()
        return self.validation_port.validate(composed, schema)

    def query(self, sql: str) -> QueryResult:
        result = self.validate(sql)
        if not result.ok:
            raise ValidationFailed(result)
        composed = self.dialect_port.compose(sql)
        return self.execution_port.execute(composed)

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
        resolved_tabs: list[ResolvedTab] = []
        for tab in spec.tabs:
            resolved_cards: list[ResolvedCard] = []
            for card in tab.cards:
                if card.is_text:
                    composed = ""  # text cards carry no SQL and are not validated
                else:
                    sql = (root / card.query).read_text()
                    composed = self.dialect_port.compose(sql)
                    result = self.validation_port.validate(composed, schema)
                    if not result.ok:
                        raise ValidationFailed(result)
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
                    )
                )
            resolved_tabs.append(ResolvedTab(name=tab.name, cards=tuple(resolved_cards)))
        dashboard = ResolvedDashboard(
            name=spec.name,
            tabs=tuple(resolved_tabs),
            collection_id=spec.collection_id,
            replace=spec.replace,
            organize_by_tab=spec.organize_by_tab,
        )
        return self.execution_port.author(dashboard)

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
