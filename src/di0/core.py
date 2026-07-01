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


def reconcile(
    spec: ReconcileSpec,
    base_dir: Path | None,
    engine_factory: Callable[[Profile], Engine],
    combine_port: CombinePort,
) -> QueryResult:
    """Answer a cross-source question: run one validated query per source, then combine.

    Each query is validated and executed against its own source (reduced there);
    the combine SQL joins the fetched results locally through the CombinePort. The
    warehouses only fetch rows - the cross-source join never runs in any of them.
    """
    root = Path(base_dir) if base_dir is not None else Path.cwd()
    tables: dict[str, QueryResult] = {}
    for query in spec.queries:
        if query.source not in spec.sources:
            raise ValueError(
                f"reconcile query {query.name!r} names unknown source {query.source!r}"
            )
        engine = engine_factory(Profile.from_dict(spec.sources[query.source]))
        tables[query.name] = engine.query((root / query.query).read_text())
    combine_sql = (root / spec.combine).read_text()
    return combine_port.combine(tables, combine_sql)
