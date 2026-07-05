"""ExecutionPort adapter: run validated SQL through Metabase's dataset API, and
optionally author cards and multi-tab dashboards.

`execute` returns rows and is the portable capability. `author` creates BI
artifacts and is the optional, Metabase-specific capability.

Metabase documents two auth schemes; both are supported and selected by the
profile (`auth`):

- `api-key` (default, recommended): the `x-api-key` header.
- `session`: the `X-Metabase-Session` header, for deployments without API keys.

Either way the credential is read from an environment variable named by the
profile, never stored in the profile.
"""

from __future__ import annotations

import csv
import io
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from di0.deliverable import ResolvedDashboard
from di0.ports import Deliverable, QueryResult

DEFAULT_API_KEY_ENV = "DI0_METABASE_API_KEY"
DEFAULT_SESSION_ENV = "DI0_METABASE_SESSION"


@dataclass(frozen=True)
class PlannedCard:
    """Where a card lands on the grid, and whether it reuses an existing card."""

    row: int
    col: int
    size_x: int
    size_y: int
    reuse_card_id: int | None = None  # update this existing card in place; None = create new
    text_visualization_settings: dict | None = None  # set only for text (non-query) cards


@dataclass(frozen=True)
class PlannedTab:
    id: int  # a reused existing id, or a negative placeholder for a brand-new tab
    name: str
    cards: tuple[PlannedCard, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class DashboardPlan:
    """The shape of a dashboard rebuild, computed without touching the network."""

    tabs: tuple[PlannedTab, ...]
    archive_card_ids: frozenset[int]


def _existing_card_ids(dashboard: dict | None) -> dict[str, int]:
    """Map a dashboard's current query-card titles to their ids, for in-place reuse.

    Metabase nests each card under its dashcard, so the title -> id map lets a
    rebuild update matching cards in place (stable card ids) rather than churn.
    """
    if not dashboard:
        return {}
    mapping: dict[str, int] = {}
    for dashcard in dashboard.get("dashcards") or dashboard.get("ordered_cards") or []:
        card_id = dashcard.get("card_id")
        name = (dashcard.get("card") or {}).get("name")
        if card_id and name:
            mapping[name] = card_id
    return mapping


def _all_existing_card_ids(dashboard: dict | None) -> set[int]:
    """Every card id a dashboard currently references, named or not (for archival)."""
    if not dashboard:
        return set()
    return {
        dashcard["card_id"]
        for dashcard in dashboard.get("dashcards") or dashboard.get("ordered_cards") or []
        if dashcard.get("card_id")
    }


def _plan_dashboard(dashboard: ResolvedDashboard, existing: dict | None) -> DashboardPlan:
    """Compute tab/card placement and reuse from plain data - no I/O.

    A tab or card matched in `existing` (by name/title) reuses its id, so the
    dashboard URL, tab anchors, and card references stay stable across rebuilds;
    anything new gets a negative placeholder id, which Metabase resolves within
    the same request. A card's real id (for a create) is only known once it is
    written, so `reuse_card_id` is `None` there - the caller fills it in.
    """
    existing_tab_ids = (
        {t.get("name"): t.get("id") for t in (existing.get("tabs") or [])} if existing else {}
    )
    existing_cards = _existing_card_ids(existing)

    planned_tabs: list[PlannedTab] = []
    reused_card_ids: set[int] = set()
    for tab_index, tab in enumerate(dashboard.tabs):
        tab_id = existing_tab_ids.get(tab.name, -(tab_index + 1))
        planned_cards: list[PlannedCard] = []
        auto_row = 0
        for card in tab.cards:
            row = card.row if card.row is not None else auto_row
            col = card.col if card.col is not None else 0
            if card.is_text:
                # Virtual text card: no /api/card. Metabase needs a virtual_card
                # scaffold ('text' body or 'heading') alongside the markdown.
                kind = card.display if card.display in ("text", "heading") else "text"
                planned_cards.append(
                    PlannedCard(
                        row=row,
                        col=col,
                        size_x=card.size_x,
                        size_y=card.size_y,
                        text_visualization_settings={
                            "virtual_card": {"display": kind},
                            "text": card.text,
                            **card.viz,
                        },
                    )
                )
            else:
                reuse_id = existing_cards.get(card.title)
                if reuse_id is not None:
                    reused_card_ids.add(reuse_id)
                planned_cards.append(
                    PlannedCard(
                        row=row, col=col, size_x=card.size_x, size_y=card.size_y,
                        reuse_card_id=reuse_id,
                    )
                )
            # Auto-stack only advances when placement is implicit.
            if card.row is None:
                auto_row = row + card.size_y
        planned_tabs.append(PlannedTab(id=tab_id, name=tab.name, cards=tuple(planned_cards)))

    archive_ids = _all_existing_card_ids(existing) - reused_card_ids
    return DashboardPlan(tabs=tuple(planned_tabs), archive_card_ids=frozenset(archive_ids))


def _coerce(value: str):
    """CSV values are strings; recover ints/floats/None so combines can aggregate."""
    if value == "":
        return None
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def _axis_settings(x_label: str, y_label: str) -> dict:
    """Map readable axis labels onto Metabase visualization settings."""
    settings: dict = {}
    if x_label:
        settings["graph.x_axis.title_text"] = x_label
    if y_label:
        settings["graph.y_axis.title_text"] = y_label
    return settings


class MetabaseExecution:
    def __init__(
        self,
        base_url: str,
        database_id: int,
        auth: str = "api-key",
        api_key_env: str = DEFAULT_API_KEY_ENV,
        session_env: str = DEFAULT_SESSION_ENV,
        default_collection_id: int | None = None,
        timeout: float = 30.0,
    ) -> None:
        if auth not in ("api-key", "session"):
            raise ValueError(f"unknown metabase auth: {auth!r} (use 'api-key' or 'session')")
        self._base_url = base_url.rstrip("/")
        self._database_id = database_id
        self._auth = auth
        self._api_key_env = api_key_env
        self._session_env = session_env
        self._default_collection_id = default_collection_id
        self._timeout = timeout

    def execute(self, sql: str) -> QueryResult:
        # Fetch via the CSV export endpoint: /api/dataset silently caps native
        # queries at 2000 rows, which would corrupt cross-source reconcile.
        query = {"database": self._database_id, "type": "native", "native": {"query": sql}}
        data = urllib.parse.urlencode({"query": json.dumps(query)}).encode()
        request = urllib.request.Request(
            f"{self._base_url}/api/dataset/csv",
            data=data,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded", **self._auth_header()},
        )
        with urllib.request.urlopen(request, timeout=self._timeout) as response:
            text = response.read().decode()
        rows = list(csv.reader(io.StringIO(text)))
        if not rows:
            return QueryResult()
        columns = tuple(rows[0])
        return QueryResult(
            columns=columns,
            rows=tuple(tuple(_coerce(value) for value in row) for row in rows[1:]),
        )

    def run_native(self, sql: str) -> tuple[bool, str | None]:
        """Run a native statement, reporting success or the warehouse error.

        Used by the EXPLAIN validation tier. A failed query surfaces as an error
        field or a failed status in the dataset response (or an HTTP error body).
        """
        payload = {"database": self._database_id, "type": "native", "native": {"query": sql}}
        try:
            body = self._request("POST", "/api/dataset", payload)
        except urllib.error.HTTPError as error:
            return False, self._error_text(json.loads(error.read() or b"{}"))
        if body.get("status") == "failed" or body.get("error"):
            return False, self._error_text(body)
        return True, None

    @property
    def supports_authoring(self) -> bool:
        return True

    def ensure_collection(self, name: str, parent_id: int | None = None) -> int:
        """Find a collection by name under a parent, or create it. Returns its id."""
        for collection in self._get("/api/collection"):
            if collection.get("name") != name:
                continue
            location = (collection.get("location") or "").rstrip("/")
            under_parent = parent_id is None or location.endswith(f"/{parent_id}")
            if under_parent:
                return collection["id"]
        payload: dict = {"name": name}
        if parent_id is not None:
            payload["parent_id"] = parent_id
        return self._request("POST", "/api/collection", payload)["id"]

    def author(self, dashboard: ResolvedDashboard) -> Deliverable:
        # Opinionated safe default: author into a chosen collection, never the shared
        # root. Prefer the spec's collection, else the profile default; refuse if neither.
        parent_collection = (
            dashboard.collection_id
            if dashboard.collection_id is not None
            else self._default_collection_id
        )
        if parent_collection is None:
            raise ValueError(
                "refusing to author into the shared root: set a collection "
                "(spec `collection_id` or profile `metabase_collection`)"
            )
        # Optionally give the deliverable its own sub-collection so the parent stays
        # clean: the dashboard and every card land here rather than beside siblings.
        home_collection = parent_collection
        if dashboard.own_collection:
            sub_name = (
                dashboard.own_collection
                if isinstance(dashboard.own_collection, str)
                else dashboard.name
            )
            home_collection = self.ensure_collection(sub_name, parent_id=parent_collection)
        # Replace = update in place: reuse a same-name dashboard's id, its tab ids
        # (matched by name), and its cards' ids (matched by title) so the dashboard
        # URL, tab anchors, and card-level references stay stable across rebuilds.
        # Cards no longer referenced after the rebuild are archived (see below).
        existing = None
        if dashboard.replace:
            existing = self._find_existing(dashboard.name, home_collection)
        plan = _plan_dashboard(dashboard, existing)

        tabs: list[dict] = []
        dashcards: list[dict] = []
        card_ids: list[int] = []
        for tab, planned_tab in zip(dashboard.tabs, plan.tabs, strict=True):
            tabs.append({"id": planned_tab.id, "name": planned_tab.name})
            # Optionally file this tab's cards into a per-tab sub-collection so the
            # collection stays navigable; the dashboard stays in the parent.
            card_collection = home_collection
            if dashboard.organize_by_tab:
                card_collection = self.ensure_collection(tab.name, parent_id=home_collection)
            for card, planned_card in zip(tab.cards, planned_tab.cards, strict=True):
                dashcard: dict = {
                    "id": -(len(dashcards) + 1),
                    "dashboard_tab_id": planned_tab.id,
                    "row": planned_card.row,
                    "col": planned_card.col,
                    "size_x": planned_card.size_x,
                    "size_y": planned_card.size_y,
                }
                if card.is_text:
                    dashcard["card_id"] = None
                    dashcard["visualization_settings"] = planned_card.text_visualization_settings
                else:
                    card_id = self._write_card(card, card_collection, planned_card.reuse_card_id)
                    card_ids.append(card_id)
                    dashcard["card_id"] = card_id
                dashcards.append(dashcard)

        if existing:
            dashboard_id = existing["id"]
        else:
            dashboard_id = self._request(
                "POST",
                "/api/dashboard",
                {"name": dashboard.name, "collection_id": home_collection},
            )["id"]
        self._request(
            "PUT",
            f"/api/dashboard/{dashboard_id}",
            {"tabs": tabs, "dashcards": dashcards},
        )
        if existing:
            self._archive_cards(plan.archive_card_ids)
        return Deliverable(
            kind="dashboard",
            identifier=str(dashboard_id),
            detail={
                "url": f"{self._base_url}/dashboard/{dashboard_id}",
                "card_ids": card_ids,
                "tabs": [tab.name for tab in dashboard.tabs],
                "collection_id": home_collection,
            },
        )

    def _find_existing(self, name: str, collection_id: int) -> dict | None:
        """Return the full same-name (non-archived) dashboard in the collection, or None.

        Lets an iteration update the prior deliverable in place - reusing its id so
        the dashboard URL is stable - instead of archiving and recreating it.
        """
        items = self._get(f"/api/collection/{collection_id}/items?models=dashboard")
        for item in items:
            if item.get("name") == name and not item.get("archived"):
                return self._get_one(f"/api/dashboard/{item['id']}")
        return None

    def _archive_cards(self, card_ids: frozenset[int]) -> None:
        """Archive the dashboard's prior query cards that this run did not reuse."""
        for card_id in card_ids:
            self._request("PUT", f"/api/card/{card_id}", {"archived": True})

    def _write_card(self, card, collection_id: int | None, card_id: int | None = None) -> int:
        """Create a card, or update the given one in place (reusing its id)."""
        # Axis-label shorthands first, then raw viz pass-through wins on conflict.
        visualization_settings = {**_axis_settings(card.x_label, card.y_label), **card.viz}
        payload: dict = {
            "name": card.title,
            "display": card.display,
            "visualization_settings": visualization_settings,
            "dataset_query": {
                "database": self._database_id,
                "type": "native",
                "native": {"query": card.sql},
            },
        }
        if card.description:
            payload["description"] = card.description
        if collection_id is not None:
            payload["collection_id"] = collection_id
        if card_id is not None:
            return self._request("PUT", f"/api/card/{card_id}", payload)["id"]
        return self._request("POST", "/api/card", payload)["id"]

    def _request(self, method: str, path: str, payload: dict) -> dict:
        headers = {"Content-Type": "application/json", **self._auth_header()}
        request = urllib.request.Request(
            f"{self._base_url}{path}",
            data=json.dumps(payload).encode(),
            method=method,
            headers=headers,
        )
        with urllib.request.urlopen(request, timeout=self._timeout) as response:
            return json.loads(response.read())

    def _get(self, path: str) -> list:
        body = self._get_one(path)
        return body.get("data", body) if isinstance(body, dict) else body

    def _get_one(self, path: str) -> dict:
        request = urllib.request.Request(
            f"{self._base_url}{path}", method="GET", headers=self._auth_header()
        )
        with urllib.request.urlopen(request, timeout=self._timeout) as response:
            return json.loads(response.read())

    def _auth_header(self) -> dict[str, str]:
        if self._auth == "session":
            return {"X-Metabase-Session": self._credential(self._session_env)}
        return {"x-api-key": self._credential(self._api_key_env)}

    def _credential(self, env_var: str) -> str:
        value = os.environ.get(env_var)
        if not value:
            raise RuntimeError(f"Metabase credential not found in environment variable {env_var}")
        return value

    @staticmethod
    def _error_text(body: dict) -> str:
        error = body.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or error)
        return str(error or body.get("status") or "query failed")
