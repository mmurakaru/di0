"""SchemaPort adapter: resolve a schema from a drizzle-kit meta snapshot.

We read the JSON snapshot drizzle-kit emits (`drizzle/meta/*.json`) rather than
parsing TypeScript, so the adapter stays language-neutral - the same way the dbt
adapter reads `manifest.json`. Table namespaces come from `pgSchema(...)`; tables
with no schema fall back to the default namespace.
"""

from __future__ import annotations

import json
from pathlib import Path

from di0.ports import Schema


class DrizzleSnapshotSchema:
    def __init__(self, snapshot_path: str | Path, default_namespace: str = "public") -> None:
        self._snapshot_path = Path(snapshot_path)
        self._default_namespace = default_namespace

    def resolve(self) -> Schema:
        snapshot = json.loads(self._snapshot_path.read_text())
        schema: Schema = {}
        for table in snapshot.get("tables", {}).values():
            namespace = table.get("schema") or self._default_namespace
            columns = {
                name: column.get("type", "unknown")
                for name, column in table.get("columns", {}).items()
            }
            schema.setdefault(namespace, {})[table["name"]] = columns
        return schema
