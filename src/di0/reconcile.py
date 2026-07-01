"""Reconcile spec: a cross-source question expressed as per-source queries + a combine.

Each named source is a full profile (its own schema/dialect/validation/execution).
Each query runs against one source (validated + executed there); the combine SQL
joins the fetched results locally. The single-source profile is just the one-source
case of this.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class ReconcileQuery:
    name: str  # the table name the combine SQL refers to
    source: str  # which named source to run against
    query: str  # path to the .sql file
    depends_on: str | None = None  # run after this query; inject its keys
    keys: str | None = None  # the dependency column whose values fill the SQL's {keys}


@dataclass(frozen=True)
class ReconcileSpec:
    # name -> profile mapping (schema/dialect/validation/execution + options)
    sources: dict[str, dict]
    queries: tuple[ReconcileQuery, ...]
    combine: str  # path to the combine .sql file

    @classmethod
    def from_file(cls, path: str | Path) -> ReconcileSpec:
        data = yaml.safe_load(Path(path).read_text()) or {}
        queries = tuple(
            ReconcileQuery(
                name=q["name"],
                source=q["source"],
                query=q["query"],
                depends_on=q.get("depends_on"),
                keys=q.get("keys"),
            )
            for q in data.get("queries", [])
        )
        return cls(
            sources={name: dict(cfg) for name, cfg in data.get("sources", {}).items()},
            queries=queries,
            combine=data["combine"],
        )
