"""SchemaPort adapter: resolve a schema from a dbt manifest.json.

The manifest is dbt's contract - it already encodes every model, column, and
type. We read it; we never hand-maintain a schema mirror.
"""

from __future__ import annotations

import json
from pathlib import Path

from di0.ports import Schema


class DbtManifestSchema:
    def __init__(self, manifest_path: str | Path) -> None:
        self._manifest_path = Path(manifest_path)

    def resolve(self) -> Schema:
        manifest = json.loads(self._manifest_path.read_text())
        schema: Schema = {}
        for node in manifest.get("nodes", {}).values():
            if node.get("resource_type") != "model":
                continue
            namespace = node["schema"]
            table = node["name"]
            columns = {
                name: (meta.get("data_type") or "unknown")
                for name, meta in node.get("columns", {}).items()
            }
            schema.setdefault(namespace, {})[table] = columns
        return schema
