"""Compose SQL from a portable semantic reference.

The definitions come from an interchange artifact read at the edge by a SchemaPort
adapter; this module never reads a file, names a warehouse, or invents a metric. It
takes an already-parsed, neutral semantic model plus a reference (a metric name,
the dimensions to group by, and optional filters) and assembles the query. The
result is ordinary SQL that then flows through compose, validate, and execute like
any other query, so nothing here bypasses the validation loop.

Definitions are authored upstream; this module composes a query from them. It does
not compose or infer the definitions themselves.
"""

from __future__ import annotations

from dataclasses import dataclass

# Neutral dialect key; a target dialect falls back to it.
PORTABLE_DIALECT = "ANSI_SQL"


@dataclass(frozen=True)
class SemanticFieldDef:
    """A dimension: a named, labelled expression over one dataset."""

    name: str
    expression: str
    datatype: str = "unknown"


@dataclass(frozen=True)
class SemanticMetricDef:
    """A metric: one aggregate expression per dialect, plus the dataset it reads.

    ``expressions`` maps a dialect key to the expression string; ``dataset`` is the
    name of the dataset the expression aggregates over (resolved at parse time).
    """

    name: str
    expressions: dict[str, str]
    dataset: str = ""
    datatype: str = "unknown"
    description: str = ""

    def expression_for(self, dialect: str) -> str:
        return self.expressions.get(dialect) or self.expressions[PORTABLE_DIALECT]


@dataclass(frozen=True)
class SemanticDatasetDef:
    """A dataset: a physical source split into namespace and table, plus its fields."""

    name: str
    namespace: str
    table: str
    fields: tuple[SemanticFieldDef, ...] = ()

    def field(self, name: str) -> SemanticFieldDef | None:
        return next((f for f in self.fields if f.name == name), None)


@dataclass(frozen=True)
class SemanticModel:
    """A parsed, tool-neutral semantic model: datasets and the metrics over them."""

    name: str
    datasets: tuple[SemanticDatasetDef, ...] = ()
    metrics: tuple[SemanticMetricDef, ...] = ()

    def dataset(self, name: str) -> SemanticDatasetDef | None:
        return next((d for d in self.datasets if d.name == name), None)

    def metric(self, name: str) -> SemanticMetricDef | None:
        return next((m for m in self.metrics if m.name == name), None)

    def dataset_of_field(self, field_name: str) -> SemanticDatasetDef | None:
        return next((d for d in self.datasets if d.field(field_name) is not None), None)


@dataclass(frozen=True)
class MetricReference:
    """A request against the model: one metric, grouped by dimensions, filtered."""

    metric: str
    dimensions: tuple[str, ...] = ()
    filters: tuple[str, ...] = ()


class SemanticReferenceError(ValueError):
    """A reference names a metric, dimension, or dataset the model does not define."""


def _dataset_for(model: SemanticModel, metric: SemanticMetricDef, dimensions: tuple[str, ...]):
    """The single dataset a reference reads: the one holding its dimensions, or the
    dataset the metric aggregates over when no dimension is requested.

    Cross-dataset references (dimensions spread over more than one dataset) are out
    of scope for this foundation and raise, rather than emit a silent partial join.
    """
    if dimensions:
        owning = {name: model.dataset_of_field(name) for name in dimensions}
        missing = [name for name, ds in owning.items() if ds is None]
        if missing:
            raise SemanticReferenceError(f"unknown dimension(s): {', '.join(sorted(missing))}")
        names = {ds.name for ds in owning.values()}
        if len(names) > 1:
            raise SemanticReferenceError(
                "cross-dataset references are not supported by this foundation"
            )
        return owning[dimensions[0]]
    dataset = model.dataset(metric.dataset)
    if dataset is None:
        raise SemanticReferenceError(
            f"metric '{metric.name}' names no resolvable dataset; "
            "declare `dataset` on the metric or add a dimension"
        )
    return dataset


def compose_sql(
    model: SemanticModel,
    reference: MetricReference,
    dialect: str,
) -> str:
    """Assemble the SQL for a metric reference against the model, for one dialect.

    The dataset is aliased by its logical name so the interchange expressions, which
    qualify columns by dataset name, resolve against the physical table on
    validation. The output is a plain SELECT with the metric aggregated over the
    requested dimensions.
    """
    metric = model.metric(reference.metric)
    if metric is None:
        raise SemanticReferenceError(f"unknown metric: {reference.metric}")

    dataset = _dataset_for(model, metric, reference.dimensions)

    select_terms: list[str] = []
    group_terms: list[str] = []
    for name in reference.dimensions:
        field_def = dataset.field(name)
        if field_def is None:
            raise SemanticReferenceError(f"dataset '{dataset.name}' has no dimension '{name}'")
        select_terms.append(f"{field_def.expression} AS {field_def.name}")
        group_terms.append(field_def.expression)
    select_terms.append(f"{metric.expression_for(dialect)} AS {metric.name}")

    source = f"{dataset.namespace}.{dataset.table} AS {dataset.name}"
    sql = f"SELECT {', '.join(select_terms)} FROM {source}"
    if reference.filters:
        sql += " WHERE " + " AND ".join(reference.filters)
    if group_terms:
        sql += " GROUP BY " + ", ".join(group_terms)
    return sql
