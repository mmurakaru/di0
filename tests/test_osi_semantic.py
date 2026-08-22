"""The portable semantic foundation: read an interchange artifact, compose a metric
reference into SQL, and prove that SQL against the resolved schema offline.

This exercises the whole new path end to end without a warehouse: the OSI SchemaPort
adapter, the resolver, and the existing dialect + offline validator. Rendering the
same SQL through a BI authoring target is the existing ExecutionPort adapters' job,
covered by their own tests - one definition, any target.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from di0.adapters.osi_schema import OsiSemanticSchema
from di0.adapters.sqlglot_dialect import SqlglotDialect
from di0.adapters.sqlglot_validation import SqlglotOfflineValidation
from di0.semantic import (
    MetricReference,
    SemanticDatasetDef,
    SemanticFieldDef,
    SemanticMetricDef,
    SemanticModel,
    SemanticReferenceError,
    compose_sql,
)
from di0.testing.conformance import check_schema_port

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "semantic" / "semantic_model.yaml"
DIALECT = "snowflake"


def _schema_port() -> OsiSemanticSchema:
    return OsiSemanticSchema(EXAMPLE)


def test_resolve_passes_schema_conformance_and_flattens_datasets() -> None:
    schema = check_schema_port(_schema_port())
    assert schema["analytics"]["orders"]["amount"] == "Decimal"
    assert set(schema["analytics"]["orders"]) == {"order_id", "amount", "order_date", "status"}


def test_metric_reference_compiles_and_validates() -> None:
    port = _schema_port()
    reference = MetricReference(metric="total_revenue", dimensions=("order_date",))

    sql = compose_sql(port.model(), reference, dialect=DIALECT)
    composed = SqlglotDialect(DIALECT).compose(sql)
    result = SqlglotOfflineValidation(DIALECT).validate(composed, port.resolve())

    assert result.ok, result.errors
    assert "GROUP BY" in composed.upper()


def test_metric_only_reference_has_no_group_by() -> None:
    port = _schema_port()
    reference = MetricReference(metric="order_count")

    sql = compose_sql(port.model(), reference, dialect=DIALECT)
    composed = SqlglotDialect(DIALECT).compose(sql)
    result = SqlglotOfflineValidation(DIALECT).validate(composed, port.resolve())

    assert result.ok, result.errors
    assert "GROUP BY" not in composed.upper()


def test_filter_is_carried_into_the_query() -> None:
    port = _schema_port()
    reference = MetricReference(
        metric="total_revenue",
        dimensions=("status",),
        filters=("orders.amount > 0",),
    )

    sql = compose_sql(port.model(), reference, dialect=DIALECT)
    composed = SqlglotDialect(DIALECT).compose(sql)
    result = SqlglotOfflineValidation(DIALECT).validate(composed, port.resolve())

    assert result.ok, result.errors
    assert "WHERE" in composed.upper()


def test_unknown_metric_is_rejected() -> None:
    port = _schema_port()
    with pytest.raises(SemanticReferenceError):
        compose_sql(port.model(), MetricReference(metric="not_a_metric"), dialect=DIALECT)


def test_unknown_dimension_is_rejected() -> None:
    port = _schema_port()
    with pytest.raises(SemanticReferenceError):
        compose_sql(
            port.model(),
            MetricReference(metric="total_revenue", dimensions=("nope",)),
            dialect=DIALECT,
        )


def _model_with(metric: SemanticMetricDef) -> SemanticModel:
    dataset = SemanticDatasetDef(
        name="orders",
        namespace="analytics",
        table="orders",
        fields=(SemanticFieldDef(name="amount", expression="amount", datatype="Decimal"),),
    )
    return SemanticModel(name="m", datasets=(dataset,), metrics=(metric,))


def test_metric_binds_via_explicit_dataset_not_expression_scan() -> None:
    # Expression names no dataset, so binding must come from the declared dataset.
    metric = SemanticMetricDef(
        name="revenue",
        expressions={"ANSI_SQL": "SUM(amount)"},
        dataset="orders",
    )
    sql = compose_sql(_model_with(metric), MetricReference(metric="revenue"), dialect=DIALECT)
    assert "analytics.orders AS orders" in sql


def test_metric_without_dataset_or_dimension_is_rejected() -> None:
    metric = SemanticMetricDef(name="revenue", expressions={"ANSI_SQL": "SUM(amount)"}, dataset="")
    with pytest.raises(SemanticReferenceError, match="declare `dataset`"):
        compose_sql(_model_with(metric), MetricReference(metric="revenue"), dialect=DIALECT)
