"""Deliverable specs: a versioned description of a dashboard built from queries.

A spec names tabs and the queries pinned to each tab. The engine resolves each
query's SQL and validates it before any artifact is authored, so a deliverable is
reproducible from source and can never reference a column that does not exist.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass(frozen=True)
class CardSpec:
    title: str
    query: str
    display: str = "table"
    size_x: int = 12
    size_y: int = 8
    description: str = ""
    x_label: str = ""
    y_label: str = ""


@dataclass(frozen=True)
class TabSpec:
    name: str
    cards: tuple[CardSpec, ...]


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
                cards=tuple(
                    CardSpec(
                        title=card["title"],
                        query=card["query"],
                        display=card.get("display", "table"),
                        size_x=int(card.get("size_x", 12)),
                        size_y=int(card.get("size_y", 8)),
                        description=card.get("description", ""),
                        x_label=card.get("x_label", ""),
                        y_label=card.get("y_label", ""),
                    )
                    for card in tab.get("cards", [])
                ),
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
    sql: str
    display: str
    size_x: int
    size_y: int
    description: str = ""
    x_label: str = ""
    y_label: str = ""


@dataclass(frozen=True)
class ResolvedTab:
    name: str
    cards: tuple[ResolvedCard, ...]


@dataclass(frozen=True)
class ResolvedDashboard:
    name: str
    tabs: tuple[ResolvedTab, ...] = field(default_factory=tuple)
    collection_id: int | None = None
