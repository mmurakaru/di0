"""Chart classification: pick the chart type that best answers a dashboard question.

The chooser (a System One model behind the TypeSafe API) is replaced by a fake that
records the request and returns fixed answers, so these tests never reach the network.
"""

from __future__ import annotations

import json
import re
from types import SimpleNamespace

import pytest

from di0 import cli, registry
from di0.adapters.lightdash_chart_catalog import LIGHTDASH_CHART_CATALOG
from di0.adapters.lightdash_execution import _DISPLAY_TO_VIZ
from di0.adapters.metabase_chart_catalog import METABASE_CHART_CATALOG, METABASE_DOCS_VERSION
from di0.adapters.typesafe_chart_chooser import TYPESAFE_API_KEY_ENV, TypeSafeChartChooser
from di0.chart_classification import (
    ChartOption,
    ChartProbabilities,
    ChartQuestion,
    ResultColumn,
    classify_charts,
)
from di0.deliverable import NEUTRAL_DISPLAYS

CATALOG = (
    ChartOption("line", "Line", "Trend of a number over time.", "https://docs.example/line"),
    ChartOption("bar", "Bar", "A number grouped by a category.", "https://docs.example/bar"),
    ChartOption("scalar", "Number", "A single number.", "https://docs.example/number"),
    ChartOption("table", "Table", "Lists of records.", "https://docs.example/table"),
    ChartOption("pie", "Pie", "Parts of a whole.", "https://docs.example/pie"),
)


def _fixed_chooser(*answers: ChartProbabilities):
    def choose(questions, catalog):
        return list(answers)

    return choose


# --- classify_charts ----------------------------------------------------------


def test_classification_picks_the_most_probable_display_with_its_docs_link():
    chooser = _fixed_chooser(
        ChartProbabilities(
            {"line": 0.7, "bar": 0.2, "scalar": 0.05, "table": 0.04, "pie": 0.01}, 0.6
        )
    )

    [result] = classify_charts([ChartQuestion("Signups per week")], CATALOG, chooser)

    assert result.display == "line"
    assert result.probability == 0.7
    assert result.confidence == 0.6
    assert result.docs_url == "https://docs.example/line"


def test_classification_lists_the_next_three_displays_as_alternatives():
    chooser = _fixed_chooser(
        ChartProbabilities(
            {"line": 0.5, "bar": 0.3, "scalar": 0.1, "table": 0.06, "pie": 0.04}, 0.4
        )
    )

    [result] = classify_charts([ChartQuestion("Signups per week")], CATALOG, chooser)

    assert [(alt.display, alt.probability) for alt in result.alternatives] == [
        ("bar", 0.3),
        ("scalar", 0.1),
        ("table", 0.06),
    ]


def test_classification_keeps_the_order_of_many_questions():
    chooser = _fixed_chooser(
        ChartProbabilities({"scalar": 0.9, "line": 0.1}, 0.9),
        ChartProbabilities({"pie": 0.8, "bar": 0.2}, 0.7),
    )
    questions = [ChartQuestion("Total revenue"), ChartQuestion("Revenue share by plan")]

    results = classify_charts(questions, CATALOG, chooser)

    assert [(result.question, result.display) for result in results] == [
        ("Total revenue", "scalar"),
        ("Revenue share by plan", "pie"),
    ]


def test_classification_result_serializes_to_the_documented_json_shape():
    chooser = _fixed_chooser(ChartProbabilities({"bar": 0.75, "line": 0.25}, 0.5))

    [result] = classify_charts([ChartQuestion("Orders by country")], CATALOG, chooser)

    assert result.to_dict() == {
        "question": "Orders by country",
        "display": "bar",
        "probability": 0.75,
        "confidence": 0.5,
        "alternatives": [{"display": "line", "probability": 0.25}],
        "docs_url": "https://docs.example/bar",
    }


def test_classification_refuses_a_display_outside_the_catalog():
    chooser = _fixed_chooser(ChartProbabilities({"sankey": 1.0}, 1.0))

    with pytest.raises(ValueError, match="Chart chooser returned display 'sankey'"):
        classify_charts([ChartQuestion("Flow between stages")], CATALOG, chooser)


def test_classification_refuses_a_missing_answer():
    chooser = _fixed_chooser()

    with pytest.raises(ValueError, match="Chart chooser returned 0 answers for 1 questions"):
        classify_charts([ChartQuestion("Orders by country")], CATALOG, chooser)


def test_classification_needs_at_least_one_question():
    with pytest.raises(ValueError, match="Chart classification needs at least one question"):
        classify_charts([], CATALOG, _fixed_chooser())


def test_chart_question_reads_result_columns_and_row_count_from_a_mapping():
    question = ChartQuestion.from_mapping(
        {
            "question": "Signups per week",
            "result_columns": [{"name": "week", "data_type": "time"}],
            "row_count": 52,
        }
    )

    assert question == ChartQuestion("Signups per week", (ResultColumn("week", "time"),), 52)


def test_chart_question_without_question_text_is_refused():
    with pytest.raises(ValueError, match="Chart question needs a non-empty 'question'"):
        ChartQuestion.from_mapping({"result_columns": []})


# --- backend chart catalogs ---------------------------------------------------


@pytest.mark.parametrize("catalog", [METABASE_CHART_CATALOG, LIGHTDASH_CHART_CATALOG])
def test_catalog_displays_are_unique_and_every_entry_is_documented(catalog):
    displays = [option.display for option in catalog]

    assert len(displays) == len(set(displays))
    for option in catalog:
        assert option.title and option.purpose
        assert option.docs_url.startswith("https://")


def test_metabase_catalog_links_pin_one_docs_version():
    for option in METABASE_CHART_CATALOG:
        assert f"/docs/{METABASE_DOCS_VERSION}/" in option.docs_url, option.display


def test_metabase_catalog_covers_every_neutral_chart_display():
    # pivot renders only for query-builder questions, never for di0's native SQL cards.
    chart_displays = set(NEUTRAL_DISPLAYS) - {"heading", "text", "pivot"}

    assert chart_displays <= {option.display for option in METABASE_CHART_CATALOG}


def test_lightdash_catalog_offers_only_displays_the_adapter_can_render():
    assert {option.display for option in LIGHTDASH_CHART_CATALOG} == set(_DISPLAY_TO_VIZ)


# --- TypeSafe chart chooser ---------------------------------------------------


class _FakeTypeSafeClient:
    """Records each system_one request and answers every question with `bar`."""

    def __init__(self):
        self.requests = []

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def system_one(self, state, questions):
        self.requests.append({"state": state, "questions": questions})
        answers = {
            question_id: SimpleNamespace(
                choice="bar", confidence=0.8, probabilities={"bar": 0.9, "line": 0.1}
            )
            for question_id in questions
        }
        return SimpleNamespace(answers=answers)


def test_typesafe_chooser_asks_every_chart_question_in_one_request():
    client = _FakeTypeSafeClient()
    chooser = TypeSafeChartChooser(client_factory=lambda: client)
    questions = [
        ChartQuestion("Orders by country", (ResultColumn("country", "category"),), 40),
        ChartQuestion("Total revenue"),
    ]

    answers = chooser(questions, CATALOG)

    [request] = client.requests
    assert request["state"] == {
        "charts": [
            {
                "question": "Orders by country",
                "result_columns": [{"name": "country", "data_type": "category"}],
                "row_count": 40,
            },
            {"question": "Total revenue"},
        ]
    }
    assert len(request["questions"]) == 2
    assert answers == [ChartProbabilities({"bar": 0.9, "line": 0.1}, 0.8)] * 2


def test_typesafe_chooser_offers_the_catalog_as_choice_criteria():
    client = _FakeTypeSafeClient()
    chooser = TypeSafeChartChooser(client_factory=lambda: client)

    chooser([ChartQuestion("Orders by country")], CATALOG)

    [choice] = client.requests[0]["questions"].values()
    expected = {option.display: f"{option.title}: {option.purpose}" for option in CATALOG}
    assert choice.criteria == expected
    assert "`charts[0].question`" in choice.instructions


def test_typesafe_chooser_without_an_api_key_names_the_env_var(monkeypatch):
    monkeypatch.delenv(TYPESAFE_API_KEY_ENV, raising=False)

    with pytest.raises(ValueError, match=f"Chart classification needs {TYPESAFE_API_KEY_ENV}"):
        TypeSafeChartChooser()


# --- di0 classify-chart -------------------------------------------------------


def _profile(tmp_path, execution: str) -> str:
    profile = tmp_path / "di0.profile.yml"
    lines = [
        "schema_source: dbt-manifest",
        "manifest_path: unused.json",
        "dialect: snowflake",
        "validation: sqlglot-offline",
        f"execution: {execution}",
    ]
    if execution == "metabase":
        lines += ["metabase_url: http://metabase.invalid", "metabase_database_id: 1"]
    profile.write_text("\n".join(lines) + "\n")
    return str(profile)


@pytest.fixture
def fake_chooser(monkeypatch):
    """Route the CLI to a chooser that answers `scalar` and records what it got."""
    seen = {}

    def choose(questions, catalog):
        seen["catalog"] = catalog
        seen["questions"] = list(questions)
        return [ChartProbabilities({"scalar": 0.9, "table": 0.1}, 0.85) for _ in questions]

    monkeypatch.setattr(registry, "build_chart_chooser", lambda: choose)
    return seen


def test_classify_chart_command_prints_one_classification_per_question(
    tmp_path, capsys, fake_chooser
):
    exit_code = cli.main(
        [
            "--profile",
            _profile(tmp_path, "metabase"),
            "classify-chart",
            "--json",
            "--question",
            "Total revenue",
            "--question",
            "Active users today",
        ]
    )

    envelope = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert [item["display"] for item in envelope["data"]["classifications"]] == ["scalar"] * 2
    assert fake_chooser["catalog"] == METABASE_CHART_CATALOG


def test_classify_chart_command_reads_questions_with_result_shape_from_a_file(
    tmp_path, capsys, fake_chooser
):
    input_path = tmp_path / "questions.json"
    input_path.write_text(
        json.dumps(
            [
                {
                    "question": "Total revenue",
                    "result_columns": [{"name": "revenue", "data_type": "number"}],
                }
            ]
        )
    )

    exit_code = cli.main(
        ["--profile", _profile(tmp_path, "metabase"), "classify-chart", "--input", str(input_path)]
    )

    assert exit_code == 0
    assert fake_chooser["questions"] == [
        ChartQuestion("Total revenue", (ResultColumn("revenue", "number"),))
    ]
    assert re.search(r"scalar\s+0\.90\s+Total revenue", capsys.readouterr().out)


def test_classify_chart_command_refuses_a_backend_without_a_chart_catalog(
    tmp_path, capsys, fake_chooser
):
    exit_code = cli.main(
        ["--profile", _profile(tmp_path, "noop"), "classify-chart", "--json", "--question", "x"]
    )

    envelope = json.loads(capsys.readouterr().out)
    assert exit_code == 78
    assert "has no chart catalog" in envelope["error"]["message"]


def test_classify_chart_command_needs_a_question(tmp_path, capsys, fake_chooser):
    exit_code = cli.main(["--profile", _profile(tmp_path, "metabase"), "classify-chart"])

    assert exit_code == 78
    assert "Chart classification needs at least one question" in capsys.readouterr().err


def test_classify_chart_command_without_an_api_key_is_a_config_error(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv(TYPESAFE_API_KEY_ENV, raising=False)

    exit_code = cli.main(
        ["--profile", _profile(tmp_path, "metabase"), "classify-chart", "--question", "x"]
    )

    assert exit_code == 78
    assert TYPESAFE_API_KEY_ENV in capsys.readouterr().err
