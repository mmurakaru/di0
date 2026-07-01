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

    @property
    def is_text(self) -> bool:
        return bool(self.text) and not self.query


@dataclass(frozen=True)
class TabSpec:
    name: str
    cards: tuple[CardSpec, ...]


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
    )


@dataclass(frozen=True)
class DashboardSpec:
    name: str
    tabs: tuple[TabSpec, ...]
    collection_id: int | None = None

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
