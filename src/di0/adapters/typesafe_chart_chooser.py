"""The TypeSafe chart chooser: asks a System One model which chart answers each question.

All chart questions go in one request: the state holds every question with its
result shape, and each question is a Choice over the backend's chart catalog. The
`typesafe-sdk` package is optional (`di0[classify]`), so it is imported lazily.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from typing import Any

from di0.chart_classification import ChartOption, ChartProbabilities, ChartQuestion

# The environment variable the TypeSafe SDK reads the API key from.
TYPESAFE_API_KEY_ENV = "TYPESAFE_API_KEY"


class TypeSafeChartChooser:
    """Chart chooser backed by the TypeSafe System One API (default model: jev-latest)."""

    def __init__(self, client_factory: Callable[[], Any] | None = None) -> None:
        self._client_factory = client_factory or _default_typesafe_client_factory()

    def __call__(
        self, questions: Sequence[ChartQuestion], catalog: Sequence[ChartOption]
    ) -> list[ChartProbabilities]:
        from typesafe_sdk import Choice

        criteria = {option.display: f"{option.title}: {option.purpose}" for option in catalog}
        typesafe_questions = {
            f"chart_{index}": Choice(instructions=_chart_instructions(index), criteria=criteria)
            for index in range(len(questions))
        }
        state = {"charts": [_chart_state(question) for question in questions]}
        with self._client_factory() as client:
            response = client.system_one(state=state, questions=typesafe_questions)
        return [
            ChartProbabilities(
                probabilities=dict(response.answers[question_id].probabilities),
                confidence=response.answers[question_id].confidence,
            )
            for question_id in typesafe_questions
        ]


def _default_typesafe_client_factory() -> Callable[[], Any]:
    if not os.environ.get(TYPESAFE_API_KEY_ENV):
        raise ValueError(
            f"Chart classification needs {TYPESAFE_API_KEY_ENV}: copy .env.example to .env, "
            "set the key, and run di0 with `uv run --env-file .env`"
        )
    try:
        from typesafe_sdk import TypeSafeClient
    except ImportError as error:
        raise ValueError(
            "Chart classification needs the typesafe-sdk package: "
            "install the classify extra (`pip install 'di0[classify]'`)"
        ) from error
    return TypeSafeClient


def _chart_instructions(index: int) -> str:
    return (
        f"Which chart type best answers the dashboard question in `charts[{index}].question`? "
        f"When `charts[{index}].result_columns` or `charts[{index}].row_count` is present, it "
        "describes the query result the chart will show: pick a chart type that fits that shape."
    )


def _chart_state(question: ChartQuestion) -> dict[str, Any]:
    chart: dict[str, Any] = {"question": question.question}
    if question.result_columns:
        chart["result_columns"] = [
            {"name": column.name, "data_type": column.data_type}
            for column in question.result_columns
        ]
    if question.row_count is not None:
        chart["row_count"] = question.row_count
    return chart
