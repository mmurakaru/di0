---
name: classify-chart
description: Pick the chart type that best answers each question on a dashboard. Use before you author a dashboard card, once for every card.
---

# classify-chart

Asks a model to pick, for each question, the chart type from the profile backend's chart catalog that best answers it.
Needs `TYPESAFE_API_KEY` in `.env` (copy `.env.example`).

## How

```bash
uv run --env-file .env di0 classify-chart --json --question "<what the chart must answer>"
uv run --env-file .env di0 classify-chart --json --input charts.json   # many charts, one request
```

`charts.json` is a list of `{"question": ..., "result_columns": [{"name": ..., "data_type": ...}], "row_count": ...}`.
Add `result_columns` and `row_count` when you have validated the query: the result shape often decides the chart.

## Rule

Use the returned `display` as the card's `display`.
If `probability` is below 0.5, show the user the top choice and its `alternatives`, and ask which to use.
