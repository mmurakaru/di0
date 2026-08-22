"""SchemaPort adapter: resolve a schema from a portable semantic interchange file.

The artifact is a vendor-neutral semantic model - datasets, fields (dimensions),
metrics, and relationships - authored upstream and read here offline, the same way
the dbt adapter reads a compiled manifest. `resolve()` flattens datasets and fields
into the plain namespace/table/column/type schema the core validates against, so no
semantic shape leaks into the core. The metric and dimension definitions are offered
through `model()` for the resolver to compose SQL from; they never enter `Schema`.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from di0.ports import Schema
from di0.semantic import (
    PORTABLE_DIALECT,
    SemanticDatasetDef,
    SemanticFieldDef,
    SemanticMetricDef,
    SemanticModel,
)


def _split_source(source: str, default_namespace: str) -> tuple[str, str]:
    """Split a `db.schema.table`, `schema.table`, or `table` source into (namespace, table)."""
    parts = [p for p in str(source).split(".") if p]
    if len(parts) >= 3:
        return parts[-2], parts[-1]
    if len(parts) == 2:
        return parts[0], parts[1]
    if len(parts) == 1:
        return default_namespace, parts[0]
    raise ValueError("dataset `source` must name at least a table")


def _expression_map(node: dict) -> dict[str, str]:
    """Read an interchange `expression.dialects[]` block into a dialect->expression map."""
    expression = node.get("expression") or {}
    dialects = expression.get("dialects") or []
    out = {str(d["dialect"]): str(d["expression"]) for d in dialects if d.get("expression")}
    if PORTABLE_DIALECT not in out and out:
        # Keep a portable fallback so any target dialect resolves.
        out[PORTABLE_DIALECT] = next(iter(out.values()))
    return out


class OsiSemanticSchema:
    def __init__(self, model_path: str | Path, *, default_namespace: str = "public") -> None:
        self._model_path = Path(model_path)
        self._default_namespace = default_namespace
        self._parsed: SemanticModel | None = None

    def _load(self) -> SemanticModel:
        if self._parsed is not None:
            return self._parsed
        document = yaml.safe_load(self._model_path.read_text()) or {}
        models = document.get("semantic_model") or []
        if not models:
            raise ValueError(f"no semantic_model found in {self._model_path}")
        # Read the first semantic model in the artifact.
        raw = models[0]

        datasets: list[SemanticDatasetDef] = []
        for dataset in raw.get("datasets") or []:
            namespace, table = _split_source(dataset.get("source", ""), self._default_namespace)
            fields: list[SemanticFieldDef] = []
            for field_node in dataset.get("fields") or []:
                expressions = _expression_map(field_node)
                fields.append(
                    SemanticFieldDef(
                        name=str(field_node["name"]),
                        expression=expressions.get(PORTABLE_DIALECT, str(field_node["name"])),
                        datatype=str(field_node.get("datatype", "unknown")),
                    )
                )
            datasets.append(
                SemanticDatasetDef(
                    name=str(dataset["name"]),
                    namespace=namespace,
                    table=table,
                    fields=tuple(fields),
                )
            )

        metrics: list[SemanticMetricDef] = []
        for metric in raw.get("metrics") or []:
            expressions = _expression_map(metric)
            # Use the declared dataset; if absent, use the one the expression uniquely names.
            dataset = str(metric.get("dataset", "")) or _dataset_qualified_in(
                expressions, datasets
            )
            metrics.append(
                SemanticMetricDef(
                    name=str(metric["name"]),
                    expressions=expressions,
                    dataset=dataset,
                    datatype=str(metric.get("datatype", "unknown")),
                    description=str(metric.get("description", "")),
                )
            )

        self._parsed = SemanticModel(
            name=str(raw.get("name", "")),
            datasets=tuple(datasets),
            metrics=tuple(metrics),
        )
        return self._parsed

    def resolve(self) -> Schema:
        model = self._load()
        schema: Schema = {}
        for dataset in model.datasets:
            columns = {f.name: f.datatype for f in dataset.fields}
            schema.setdefault(dataset.namespace, {})[dataset.table] = columns
        return schema

    def model(self) -> SemanticModel:
        """The parsed, tool-neutral semantic model for the resolver to compose from."""
        return self._load()


def _dataset_qualified_in(
    expressions: dict[str, str], datasets: list[SemanticDatasetDef]
) -> str:
    """The dataset a metric's expression uniquely qualifies (e.g. `SUM(orders.amount)`
    -> `orders`). Empty when zero or more than one dataset is qualified, so an
    ambiguous metric must declare `dataset:` rather than be bound by a guess."""
    portable = expressions.get(PORTABLE_DIALECT, "")
    qualified = [d.name for d in datasets if f"{d.name}." in portable]
    return qualified[0] if len(qualified) == 1 else ""
