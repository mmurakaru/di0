"""ExecutionPort adapter: run validated SQL through Lightdash's SQL runner, and
optionally author saved SQL charts and dashboards.

`execute` submits raw SQL to the v2 SQL-runner query path and fetches the rows;
it is the portable capability. `author` is the optional, Lightdash-specific
capability: it ensures a space, creates one saved SQL chart per query card, and
assembles a dashboard with native tabs and `sql_chart` / `markdown` / `heading`
tiles. When `replace` is set it upserts the dashboard by slug through the
content-as-code surface, so the URL stays stable across rebuilds.

The authoring surface is deliberately restrictive (see `capabilities`): Lightdash
SQL charts render only bar / line / pie / table, and its dashboard filters are
result-column post-filters with no `{{variable}}` templating - so specs asking for
other displays or dashboard parameters are refused by the core before any write.

Auth is a Personal Access Token sent as `Authorization: ApiKey <token>`, read from
an environment variable named by the profile, never stored in the profile.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.request
import uuid

from di0.deliverable import ResolvedDashboard
from di0.ports import Capabilities, Deliverable, QueryResult

DEFAULT_API_KEY_ENV = "DI0_LIGHTDASH_TOKEN"

# The key this adapter reads out of a spec's per-adapter `native` escape hatch.
_NATIVE_KEY = "lightdash"

# The neutral display vocabulary this adapter renders, mapped to Lightdash's
# `AllVizChartConfig` types. Anything outside these keys is refused upstream by
# the capability check, so a create never reaches an unmappable display.
_DISPLAY_TO_VIZ = {
    "bar": "vertical_bar",
    "line": "line",
    "pie": "pie",
    "table": "table",
}

# Lightdash lays dashboards out on a 36-column grid.
_GRID_COLUMNS = 36
# The neutral logical grid is 12 units wide; it scales x3 onto the 36-col grid.
_LOGICAL_SCALE = 3


def _adapter_native(native: dict | None) -> dict:
    """This adapter's slice of a spec's `native` mapping, or an empty dict."""
    return (native or {}).get(_NATIVE_KEY, {})


def _slugify(name: str) -> str:
    """A stable, URL-safe slug for a chart, dashboard, or space name."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "untitled"


def _grid_footprint(card) -> tuple[int, int]:
    """A card's (width, height) on the 36-column grid.

    Logical width/height are on the neutral 12-unit grid and scale x3; when unset,
    the absolute size_x/size_y (authored against a 24-unit grid) scale x1.5 so a
    half-width card stays half-width. Width is capped at the grid.
    """
    if card.width is not None:
        width = card.width * _LOGICAL_SCALE
    else:
        width = round(card.size_x * _GRID_COLUMNS / 24)
    if card.height is not None:
        height = card.height * _LOGICAL_SCALE
    else:
        height = round(card.size_y * _GRID_COLUMNS / 24)
    return min(max(width, 1), _GRID_COLUMNS), max(height, 1)


def _column_names(columns) -> tuple[str, ...]:
    """Ordered column names from Lightdash's SQL-result `columns` payload.

    Accepts either a list (of strings or `{reference|name}` objects) or a dict
    keyed by column reference, both of which the query API has used.
    """
    if not columns:
        return ()
    if isinstance(columns, dict):
        return tuple(columns.keys())
    names: list[str] = []
    for column in columns:
        if isinstance(column, str):
            names.append(column)
        elif isinstance(column, dict):
            names.append(column.get("reference") or column.get("name"))
    return tuple(name for name in names if name)


def _to_query_result(columns: tuple[str, ...], rows: list) -> QueryResult:
    """Project Lightdash's row dicts onto a positional QueryResult."""
    if rows and isinstance(rows[0], dict):
        if not columns:
            columns = tuple(rows[0].keys())
        projected = tuple(tuple(row.get(name) for name in columns) for row in rows)
    else:
        projected = tuple(tuple(row) for row in rows)
    return QueryResult(columns=columns, rows=projected)


class LightdashExecution:
    def __init__(
        self,
        base_url: str,
        project_uuid: str,
        api_key_env: str = DEFAULT_API_KEY_ENV,
        default_space: str | None = None,
        query_limit: int = 5000,
        chart_limit: int = 500,
        max_polls: int = 60,
        poll_interval: float = 0.5,
        timeout: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._project_uuid = project_uuid
        self._api_key_env = api_key_env
        self._default_space = default_space or None
        self._query_limit = query_limit
        self._chart_limit = chart_limit
        self._max_polls = max_polls
        self._poll_interval = poll_interval
        self._timeout = timeout

    def _project(self, suffix: str) -> str:
        return f"/api/v1/projects/{self._project_uuid}{suffix}"

    # --- execute ---------------------------------------------------------------

    def execute(self, sql: str) -> QueryResult:
        query_uuid = self._submit_sql(sql)
        columns: tuple[str, ...] = ()
        rows: list = []
        page = 1
        polls = 0
        while True:
            results = self._api(
                "GET",
                f"/api/v2/projects/{self._project_uuid}/query/{query_uuid}"
                f"?page={page}&pageSize={self._query_limit}",
            )
            status = results.get("status")
            if status == "error":
                raise RuntimeError(f"Lightdash SQL query failed: {results.get('error')}")
            if status not in (None, "ready"):
                polls += 1
                if polls > self._max_polls:
                    raise RuntimeError("Lightdash SQL query did not complete in time")
                time.sleep(self._poll_interval)
                continue
            page_columns = _column_names(results.get("columns"))
            if page_columns:
                columns = page_columns
            rows.extend(results.get("rows") or [])
            next_page = results.get("nextPage")
            if not next_page:
                break
            page = next_page
        return _to_query_result(columns, rows)

    def _submit_sql(self, sql: str) -> str:
        results = self._api(
            "POST",
            f"/api/v2/projects/{self._project_uuid}/query/sql",
            {"sql": sql, "limit": self._query_limit},
        )
        return results["queryUuid"]

    # --- authoring surface -----------------------------------------------------

    @property
    def supports_authoring(self) -> bool:
        return True

    @property
    def capabilities(self) -> Capabilities:
        # Deliberately restrictive: SQL charts render only these four displays, and
        # Lightdash has no {{variable}} SQL templating, so dashboard parameters are
        # unsupported. The core refuses anything beyond this before any write.
        return Capabilities(
            authors=True,
            displays=frozenset(_DISPLAY_TO_VIZ),
            text_cards=True,
            parameters=False,
            grid_columns=_GRID_COLUMNS,
        )

    def ensure_space(self, name: str) -> dict:
        """Find a space by name, or create it. Returns the space (uuid + slug)."""
        for space in self._api("GET", self._project("/spaces")):
            if space.get("name") == name:
                return space
        return self._api(
            "POST",
            self._project("/spaces"),
            {"name": name, "parentSpaceUuid": None, "access": []},
        )

    def author(self, dashboard: ResolvedDashboard) -> Deliverable:
        # Opinionated safe default: author into a chosen space, never an implicit one.
        # Prefer the spec's collection name, then the profile default; refuse if none.
        space_name = dashboard.collection or self._default_space
        if not space_name:
            raise ValueError(
                "refusing to author without a space: set a space "
                "(spec `collection` or profile `lightdash_space`)"
            )
        space = self.ensure_space(space_name)
        space_uuid = space["uuid"]

        tabs: list[dict] = []
        tiles: list[dict] = []
        chart_uuids: list[str] = []
        for tab_index, tab in enumerate(dashboard.tabs):
            tab_uuid = str(uuid.uuid4())
            tabs.append({"uuid": tab_uuid, "name": tab.name, "order": tab_index})
            auto_y = 0
            for card in tab.cards:
                width, height = _grid_footprint(card)
                column = card.col if card.col is not None else 0
                row = card.row if card.row is not None else auto_y
                if card.is_text:
                    tile_type, properties = _text_tile(card)
                else:
                    chart = self._create_chart(card, space_uuid)
                    chart_uuids.append(chart["savedSqlUuid"])
                    tile_type = "sql_chart"
                    properties = {
                        "savedSqlUuid": chart["savedSqlUuid"],
                        "chartName": card.title,
                        "chartSlug": chart["slug"],
                    }
                tiles.append(
                    {
                        "uuid": str(uuid.uuid4()),
                        "type": tile_type,
                        "x": column,
                        "y": row,
                        "w": width,
                        "h": height,
                        "tabUuid": tab_uuid,
                        "properties": properties,
                    }
                )
                if card.row is None:
                    auto_y = row + height

        identifier, extra = self._write_dashboard(dashboard, space, tabs, tiles)
        return Deliverable(
            kind="dashboard",
            identifier=str(identifier),
            detail={
                "url": f"{self._base_url}/projects/{self._project_uuid}"
                f"/dashboards/{identifier}/view",
                "space_uuid": space_uuid,
                "chart_uuids": chart_uuids,
                "tabs": [tab.name for tab in dashboard.tabs],
                "replaced": dashboard.replace,
                **extra,
            },
        )

    def _create_chart(self, card, space_uuid: str) -> dict:
        slug = _slugify(card.title)
        # Defaults first, then the native escape hatch, then raw `viz` (viz wins);
        # `type` is pinned to the mapped display so the escape hatch can't unset it.
        config = {
            "fieldConfig": {},
            "display": {},
            **_adapter_native(card.native),
            **card.viz,
            "type": _DISPLAY_TO_VIZ.get(card.display, "table"),
        }
        payload = {
            "name": card.title,
            "description": card.description or None,
            "sql": card.sql,
            "limit": self._chart_limit,
            "config": config,
            "spaceUuid": space_uuid,
            "slug": slug,
        }
        results = self._api("POST", self._project("/sqlRunner/saved"), payload)
        return {
            "savedSqlUuid": results["savedSqlUuid"],
            "slug": results.get("slug") or slug,
        }

    def _write_dashboard(
        self, dashboard: ResolvedDashboard, space: dict, tabs: list[dict], tiles: list[dict]
    ) -> tuple[str, dict]:
        """Create the dashboard, or upsert it by slug when `replace` is set.

        Dashboard-level `native` can add extra fields; the computed tabs and tiles
        always win so authoring is never disturbed.
        """
        base = {**_adapter_native(dashboard.native), "name": dashboard.name}
        slug = _slugify(dashboard.name)
        if dashboard.replace:
            results = self._api(
                "POST",
                self._project(f"/code/dashboards/{slug}"),
                {
                    **base,
                    "tabs": tabs,
                    "tiles": tiles,
                    "spaceSlug": space.get("slug") or slug,
                    "skipSpaceCreate": True,
                },
            )
            identifier = results.get("slug") or results.get("uuid") or slug
            return identifier, {"slug": slug}
        results = self._api(
            "POST",
            self._project("/dashboards"),
            {**base, "tabs": tabs, "tiles": tiles, "spaceUuid": space["uuid"]},
        )
        return results.get("uuid") or slug, {"slug": results.get("slug") or slug}

    # --- HTTP ------------------------------------------------------------------

    def _api(self, method: str, path: str, payload: dict | None = None):
        """Issue a request and unwrap Lightdash's `{ "results": ... }` envelope."""
        headers = self._auth_header()
        data = None
        if payload is not None:
            data = json.dumps(payload).encode()
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"{self._base_url}{path}", data=data, method=method, headers=headers
        )
        with urllib.request.urlopen(request, timeout=self._timeout) as response:
            body = json.loads(response.read() or b"{}")
        if isinstance(body, dict) and "results" in body:
            return body["results"]
        return body

    def _auth_header(self) -> dict[str, str]:
        return {"Authorization": f"ApiKey {self._credential()}"}

    def _credential(self) -> str:
        value = os.environ.get(self._api_key_env)
        if not value:
            raise RuntimeError(
                f"Lightdash token not found in environment variable {self._api_key_env}"
            )
        return value


def _text_tile(card) -> tuple[str, dict]:
    """A heading or markdown tile for a text card, keyed off its neutral display."""
    native = _adapter_native(card.native)
    if card.display == "heading":
        return "heading", {"text": card.text, "showDivider": False, **native}
    return "markdown", {"content": card.text, "title": card.title, "hideFrame": False, **native}
