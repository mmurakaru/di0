"""The Metabase chart catalog: every chart type di0 can author, with when-to-use text.

Purposes follow the wording of Metabase's visualization docs, and every link pins
one docs version, so a stale entry is visible. To refresh: bump the version in every
link, then re-read the changed pages. Source of the identifiers: the `identifier` of
each definition registered in Metabase's `frontend/src/metabase/visualizations/register.ts`.

Left out on purpose: `list` (hidden from the visualization picker) and `pivot`
(Metabase renders pivot tables only for query-builder questions, and di0 authors
native SQL cards).
"""

from __future__ import annotations

from di0.chart_classification import ChartOption

# The Metabase docs version every link below pins.
METABASE_DOCS_VERSION = "v0.65"

METABASE_CHART_CATALOG: tuple[ChartOption, ...] = (
    ChartOption(
        display="line",
        title="Line",
        purpose=(
            "Best for displaying the trend of a number over time, especially when you have "
            "lots of x-axis values."
        ),
        docs_url="https://www.metabase.com/docs/v0.65/questions/visualizations/line-bar-and-area-charts#line-charts",
    ),
    ChartOption(
        display="bar",
        title="Bar",
        purpose=(
            "Great for displaying a number grouped by a category, like the number of users "
            "by country, or a smaller number of values over time."
        ),
        docs_url="https://www.metabase.com/docs/v0.65/questions/visualizations/line-bar-and-area-charts#bar-charts",
    ),
    ChartOption(
        display="area",
        title="Area",
        purpose=(
            "Useful when comparing the proportions of two metrics over time. Stack the areas "
            "to show how much each series contributes to a total."
        ),
        docs_url="https://www.metabase.com/docs/v0.65/questions/visualizations/line-bar-and-area-charts#area-charts",
    ),
    ChartOption(
        display="combo",
        title="Combo",
        purpose=(
            "Combines bars and lines (or areas) on the same chart. Use it to plot two metrics "
            "with very different ranges, like order count against total revenue."
        ),
        docs_url="https://www.metabase.com/docs/v0.65/questions/visualizations/line-bar-and-area-charts#combo-charts",
    ),
    ChartOption(
        display="row",
        title="Row",
        purpose=(
            "Good for visualizing data grouped by a column that has a lot of possible values, "
            "like a vendor or product title. Bars show in descending order of size."
        ),
        docs_url="https://www.metabase.com/docs/v0.65/questions/visualizations/visualizing-results#row-charts",
    ),
    ChartOption(
        display="pie",
        title="Pie",
        purpose=(
            "Breaks out a metric by a single dimension as part of a whole, especially when the "
            "number of possible breakouts is small, like accounts by plan."
        ),
        docs_url="https://www.metabase.com/docs/v0.65/questions/visualizations/pie-or-donut-chart",
    ),
    ChartOption(
        display="scalar",
        title="Number",
        purpose="For displaying a single number, nice and big.",
        docs_url="https://www.metabase.com/docs/v0.65/questions/visualizations/numbers",
    ),
    ChartOption(
        display="smartscalar",
        title="Trend",
        purpose=(
            "Displays how a single number has changed between two time periods. Needs a single "
            "number grouped by a time field."
        ),
        docs_url="https://www.metabase.com/docs/v0.65/questions/visualizations/trend",
    ),
    ChartOption(
        display="progress",
        title="Progress",
        purpose=(
            "For comparing a single number to a goal value that you set, like tracking a KPI "
            "toward its target."
        ),
        docs_url="https://www.metabase.com/docs/v0.65/questions/visualizations/progress-bar",
    ),
    ChartOption(
        display="gauge",
        title="Gauge",
        purpose=(
            "Shows a single number in the context of a set of colored ranges that you specify, "
            "for metrics with distinct thresholds."
        ),
        docs_url="https://www.metabase.com/docs/v0.65/questions/visualizations/gauge",
    ),
    ChartOption(
        display="table",
        title="Table",
        purpose="Good for looking at tabular data, or for lists of things like users or orders.",
        docs_url="https://www.metabase.com/docs/v0.65/questions/visualizations/table",
    ),
    ChartOption(
        display="object",
        title="Detail",
        purpose="Shows a single result record (row) in an easy-to-read, two-column display.",
        docs_url="https://www.metabase.com/docs/v0.65/questions/visualizations/detail",
    ),
    ChartOption(
        display="funnel",
        title="Funnel",
        purpose=(
            "Shows values broken out by sequential steps, and the percent decrease between each "
            "step, like how many customers reach each step of a checkout flow."
        ),
        docs_url="https://www.metabase.com/docs/v0.65/questions/visualizations/funnel",
    ),
    ChartOption(
        display="waterfall",
        title="Waterfall",
        purpose=(
            "A kind of bar chart for results with both positive and negative values: shows how a "
            "starting value changes through increases and decreases to a final total."
        ),
        docs_url="https://www.metabase.com/docs/v0.65/questions/visualizations/waterfall-chart",
    ),
    ChartOption(
        display="scatter",
        title="Scatter",
        purpose=(
            "Visualizes the correlation between two numeric variables. A bubble size column adds "
            "a third value."
        ),
        docs_url="https://www.metabase.com/docs/v0.65/questions/visualizations/scatterplot-or-bubble-chart",
    ),
    ChartOption(
        display="boxplot",
        title="Box plot",
        purpose=(
            "Shows the distribution of numeric data across groups: the median, quartiles, and "
            "outliers for each group."
        ),
        docs_url="https://www.metabase.com/docs/v0.65/questions/visualizations/box-plot",
    ),
    ChartOption(
        display="sankey",
        title="Sankey",
        purpose=(
            "Shows how data flows through multi-dimensional steps, from a source column to a "
            "target column, sized by a value."
        ),
        docs_url="https://www.metabase.com/docs/v0.65/questions/visualizations/sankey",
    ),
    ChartOption(
        display="treemap",
        title="Treemap",
        purpose=(
            "Displays hierarchical data as nested rectangles sized by a metric, to break a total "
            "down across one or two nested categories."
        ),
        docs_url="https://www.metabase.com/docs/v0.65/questions/visualizations/treemap",
    ),
    ChartOption(
        display="map",
        title="Map",
        purpose=(
            "Puts data on a map: individual points by latitude and longitude, or values broken "
            "out by region, like countries or states."
        ),
        docs_url="https://www.metabase.com/docs/v0.65/questions/visualizations/map",
    ),
)
