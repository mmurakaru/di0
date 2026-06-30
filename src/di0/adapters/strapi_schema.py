"""SchemaPort adapter: resolve a schema from Strapi content-type schema.json files.

Strapi v5 stores each relation in a generated link table named
`<source_table>_<attribute>_lnk` with `<source_singular>_id` and
`<target_singular>_id` columns. We derive those by Strapi's naming convention,
and let a committed information_schema dump confirm/override them when present so
the names are verified rather than guessed.
"""

from __future__ import annotations

import json
from pathlib import Path

from di0.ports import Schema

# Strapi-managed columns present on every collection table.
_MANAGED_COLUMNS = {
    "id": "integer",
    "document_id": "varchar",
    "created_at": "timestamp",
    "updated_at": "timestamp",
    "published_at": "timestamp",
}

_TYPE_MAP = {
    "string": "varchar",
    "uid": "varchar",
    "text": "text",
    "richtext": "text",
    "email": "varchar",
    "integer": "integer",
    "biginteger": "bigint",
    "float": "double precision",
    "decimal": "numeric",
    "boolean": "boolean",
    "date": "date",
    "datetime": "timestamp",
    "json": "jsonb",
}


def _snake(value: str) -> str:
    out = []
    for char in value:
        if char.isupper():
            out.append("_")
            out.append(char.lower())
        elif char == "-":
            out.append("_")
        else:
            out.append(char)
    return "".join(out).lstrip("_")


class StrapiContentTypeSchema:
    def __init__(
        self,
        schema_dir: str | Path,
        namespace: str = "public",
        information_schema_path: str | Path | None = None,
    ) -> None:
        self._schema_dir = Path(schema_dir)
        self._namespace = namespace
        self._information_schema_path = (
            Path(information_schema_path) if information_schema_path else None
        )

    def resolve(self) -> Schema:
        tables: dict[str, dict[str, str]] = {}
        for schema_file in sorted(self._schema_dir.glob("**/schema.json")):
            self._read_content_type(json.loads(schema_file.read_text()), tables)
        self._apply_information_schema(tables)
        return {self._namespace: tables}

    def _read_content_type(self, definition: dict, tables: dict[str, dict[str, str]]) -> None:
        info = definition.get("info", {})
        table = definition.get("collectionName") or _snake(info["pluralName"])
        source_singular = _snake(info["singularName"])
        columns = dict(_MANAGED_COLUMNS)
        for attr_name, attr in definition.get("attributes", {}).items():
            if attr.get("type") == "relation":
                self._add_link_table(table, source_singular, attr_name, attr, tables)
                continue
            columns[_snake(attr_name)] = _TYPE_MAP.get(attr.get("type", ""), "varchar")
        tables[table] = columns

    def _add_link_table(
        self,
        source_table: str,
        source_singular: str,
        attr_name: str,
        attr: dict,
        tables: dict[str, dict[str, str]],
    ) -> None:
        target_singular = _snake(attr["target"].split(".")[-1])
        link_table = f"{source_table}_{_snake(attr_name)}_lnk"
        tables[link_table] = {
            f"{source_singular}_id": "integer",
            f"{target_singular}_id": "integer",
        }

    def _apply_information_schema(self, tables: dict[str, dict[str, str]]) -> None:
        if not self._information_schema_path:
            return
        confirmed = json.loads(self._information_schema_path.read_text())
        for table, columns in confirmed.items():
            tables[table] = dict(columns)
