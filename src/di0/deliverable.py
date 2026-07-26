"""Deliverable specs: a versioned description of a dashboard built from queries.

A spec names tabs and the cards on each tab. A card is either query-backed (its
SQL is resolved and validated before authoring) or a text card (markdown, no
query). Visualization settings pass through raw to the execution adapter, with a
few ergonomic shorthands, so the spec is not a lossy DSL over the BI tool.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

# The portable display vocabulary. A spec's `display` is intentionally NOT validated
# against this - adapters keep accepting any native display string - so this is
# documentation plus a set an adapter can map a neutral name from.
NEUTRAL_DISPLAYS = (
    "bar",
    "line",
    "area",
    "pie",
    "table",
    "scalar",
    "pivot",
    "row",
    "funnel",
    "combo",
    "heading",
    "text",
)


@dataclass(frozen=True)
class CardSpec:
    title: str = ""
    query: str = ""
    text: str = ""  # markdown; when set (and no query) this is a text card
    display: str = "table"
    size_x: int = 12
    size_y: int = 8
    row: int | None = None  # explicit grid placement; None = auto-stack
    col: int | None = None
    description: str = ""
    x_label: str = ""
    y_label: str = ""
    viz: dict = field(default_factory=dict)  # raw visualization_settings pass-through
    # Logical relative sizing on a 12-unit grid; an adapter scales it to its own grid.
    # When unset, the absolute size_x/size_y above are used as-is.
    width: int | None = None
    height: int | None = None
    # Raw, per-adapter escape hatch: {adapter_name: {...}} passed straight through by
    # that adapter and merged under `viz` (viz wins). Never portable across BI tools.
    native: dict = field(default_factory=dict)
    params: dict = field(default_factory=dict)  # dashboard-parameter slug -> query variable name
    # query variable name -> {field_id, widget_type} to author it as a native Field Filter
    # (a `{{var}}` bound to a real column) instead of a raw variable; enables multi-value filters.
    # NOTE: the neutral filter IR is deferred to the Lightdash adapter slice (#55); these
    # fields stay adapter-shaped for now.
    field_filters: dict = field(default_factory=dict)

    @property
    def is_text(self) -> bool:
        return bool(self.text) and not self.query


@dataclass(frozen=True)
class TabSpec:
    name: str
    cards: tuple[CardSpec, ...]


def _optional_int(value: object) -> int | None:
    return int(value) if value is not None else None


def _card_from(card: dict) -> CardSpec:
    return CardSpec(
        title=card.get("title", ""),
        query=card.get("query", ""),
        text=card.get("text", ""),
        display=card.get("display", "table"),
        size_x=int(card.get("size_x", 12)),
        size_y=int(card.get("size_y", 8)),
        row=card.get("row"),
        col=card.get("col"),
        description=card.get("description", ""),
        x_label=card.get("x_label", ""),
        y_label=card.get("y_label", ""),
        viz=dict(card.get("viz", {})),
        width=_optional_int(card.get("width")),
        height=_optional_int(card.get("height")),
        native=dict(card.get("native", {})),
        params=dict(card.get("params", {})),
        field_filters=dict(card.get("field_filters", {})),
    )


@dataclass(frozen=True)
class DashboardSpec:
    name: str
    tabs: tuple[TabSpec, ...]
    collection_id: int | None = None
    # A collection name/path, resolved to an id by the adapter when `collection_id`
    # is unset. `collection_id` takes precedence when both are given.
    collection: str = ""
    replace: bool = False  # update an existing same-name dashboard in place (stable URL)
    organize_by_tab: bool = False  # file each tab's cards into a per-tab sub-collection
    own_collection: bool | str = False  # nest dashboard + cards in a sub-collection (name, or True)
    parameters: tuple[dict, ...] = ()  # dashboard-level filter widgets wired to card variables
    # Raw, per-adapter escape hatch at the dashboard level; see CardSpec.native.
    native: dict = field(default_factory=dict)

    @classmethod
    def from_file(cls, path: str | Path) -> DashboardSpec:
        data = yaml.safe_load(Path(path).read_text()) or {}
        tabs = tuple(
            TabSpec(
                name=tab["name"],
                cards=tuple(_card_from(card) for card in tab.get("cards", [])),
            )
            for tab in data.get("tabs", [])
        )
        collection_id = data.get("collection_id")
        return cls(
            name=data["name"],
            tabs=tabs,
            collection_id=int(collection_id) if collection_id is not None else None,
            collection=str(data.get("collection", "")),
            replace=bool(data.get("replace", False)),
            organize_by_tab=bool(data.get("organize_by_tab", False)),
            own_collection=data.get("own_collection", False),
            parameters=tuple(data.get("parameters", []) or []),
            native=dict(data.get("native", {})),
        )


@dataclass(frozen=True)
class ResolvedCard:
    title: str
    sql: str = ""
    text: str = ""
    display: str = "table"
    size_x: int = 12
    size_y: int = 8
    row: int | None = None
    col: int | None = None
    description: str = ""
    x_label: str = ""
    y_label: str = ""
    viz: dict = field(default_factory=dict)
    width: int | None = None
    height: int | None = None
    native: dict = field(default_factory=dict)
    params: dict = field(default_factory=dict)
    field_filters: dict = field(default_factory=dict)

    @property
    def is_text(self) -> bool:
        return bool(self.text) and not self.sql


@dataclass(frozen=True)
class ResolvedTab:
    name: str
    cards: tuple[ResolvedCard, ...]


@dataclass(frozen=True)
class ResolvedDashboard:
    name: str
    tabs: tuple[ResolvedTab, ...] = field(default_factory=tuple)
    collection_id: int | None = None
    collection: str = ""
    replace: bool = False
    organize_by_tab: bool = False
    own_collection: bool | str = False
    parameters: tuple[dict, ...] = ()
    native: dict = field(default_factory=dict)
