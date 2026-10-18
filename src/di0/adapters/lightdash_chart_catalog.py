"""The Lightdash chart catalog: the chart types the Lightdash adapter can author.

Limited to the displays `lightdash_execution._DISPLAY_TO_VIZ` maps. Purposes follow
the wording of the Lightdash visualization docs, which are not versioned.
"""

from __future__ import annotations

from di0.chart_classification import ChartOption

LIGHTDASH_CHART_CATALOG: tuple[ChartOption, ...] = (
    ChartOption(
        display="bar",
        title="Bar",
        purpose=(
            "Compares things between different groups, like the number of orders by product "
            "type, or tracks a number over time when there are few x-axis values."
        ),
        docs_url="https://docs.lightdash.com/visualizations/bar-chart",
    ),
    ChartOption(
        display="line",
        title="Line",
        purpose="Shows changes in a number over a short or long period of time.",
        docs_url="https://docs.lightdash.com/visualizations/line-chart",
    ),
    ChartOption(
        display="pie",
        title="Pie",
        purpose=(
            "Visualizes data that adds up to a meaningful whole, like the split of total "
            "revenue across product lines."
        ),
        docs_url="https://docs.lightdash.com/visualizations/pie-chart",
    ),
    ChartOption(
        display="table",
        title="Table",
        purpose=(
            "Good for looking at tabular data, or for lists of things like user IDs or "
            "transactions."
        ),
        docs_url="https://docs.lightdash.com/visualizations/table",
    ),
)
