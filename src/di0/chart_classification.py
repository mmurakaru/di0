"""Chart classification: pick the chart type that best answers a dashboard question.

A chart chooser (a model behind an adapter) returns a probability for every chart
type in a backend's chart catalog; `classify_charts` turns those probabilities into
the chosen display, its runner-up alternatives, and the docs link for the choice.
Backend-neutral: catalogs and choosers live in adapters, wired by the registry.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

# How many runner-up displays a classification reports after the chosen one.
ALTERNATIVE_DISPLAY_COUNT = 3


@dataclass(frozen=True)
class ChartOption:
    """One chart type a dashboard backend can render, with its when-to-use text and docs link."""

    display: str
    title: str
    purpose: str
    docs_url: str


@dataclass(frozen=True)
class ResultColumn:
    """One column of a query result: its name and a plain data type (time, category, number)."""

    name: str
    data_type: str


@dataclass(frozen=True)
class ChartQuestion:
    """The question a dashboard chart must answer, plus the query result shape when known."""

    question: str
    result_columns: tuple[ResultColumn, ...] = ()
    row_count: int | None = None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> ChartQuestion:
        """Read a chart question from parsed JSON (question, result_columns, row_count)."""
        question = str(raw.get("question") or "").strip()
        if not question:
            raise ValueError(f"Chart question needs a non-empty 'question': {dict(raw)!r}")
        columns = tuple(
            ResultColumn(str(column["name"]), str(column["data_type"]))
            for column in raw.get("result_columns") or ()
        )
        row_count = raw.get("row_count")
        return cls(question, columns, None if row_count is None else int(row_count))


@dataclass(frozen=True)
class ChartProbabilities:
    """A chart chooser's answer to one question: a probability per display, and its confidence."""

    probabilities: Mapping[str, float]
    confidence: float


# Answers every question in one call, in question order, over the given catalog.
ChartChooser = Callable[[Sequence[ChartQuestion], Sequence[ChartOption]], list[ChartProbabilities]]


@dataclass(frozen=True)
class ChartAlternative:
    """A runner-up chart type and its probability."""

    display: str
    probability: float


@dataclass(frozen=True)
class ChartClassification:
    """The chart type chosen for one dashboard question, with runner-ups and the docs link."""

    question: str
    display: str
    probability: float
    confidence: float
    docs_url: str
    alternatives: tuple[ChartAlternative, ...] = field(default=())

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "display": self.display,
            "probability": self.probability,
            "confidence": self.confidence,
            "alternatives": [
                {"display": alternative.display, "probability": alternative.probability}
                for alternative in self.alternatives
            ],
            "docs_url": self.docs_url,
        }


def classify_charts(
    questions: Sequence[ChartQuestion],
    catalog: Sequence[ChartOption],
    chooser: ChartChooser,
) -> list[ChartClassification]:
    """Classify each dashboard question to the most probable chart type in the catalog."""
    if not questions:
        raise ValueError("Chart classification needs at least one question")
    answers = chooser(questions, catalog)
    if len(answers) != len(questions):
        raise ValueError(
            f"Chart chooser returned {len(answers)} answers for {len(questions)} questions"
        )
    options_by_display = {option.display: option for option in catalog}
    return [
        _classification_from_answer(question, answer, options_by_display)
        for question, answer in zip(questions, answers, strict=True)
    ]


def _classification_from_answer(
    question: ChartQuestion,
    answer: ChartProbabilities,
    options_by_display: Mapping[str, ChartOption],
) -> ChartClassification:
    ranked = sorted(answer.probabilities.items(), key=lambda item: item[1], reverse=True)
    for display, _ in ranked:
        if display not in options_by_display:
            raise ValueError(f"Chart chooser returned display {display!r} outside the catalog")
    display, probability = ranked[0]
    alternatives = tuple(
        ChartAlternative(alternative_display, alternative_probability)
        for alternative_display, alternative_probability in ranked[
            1 : 1 + ALTERNATIVE_DISPLAY_COUNT
        ]
    )
    return ChartClassification(
        question=question.question,
        display=display,
        probability=probability,
        confidence=answer.confidence,
        docs_url=options_by_display[display].docs_url,
        alternatives=alternatives,
    )
