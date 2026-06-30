"""Wire a profile to concrete adapters.

This is the one composition edge where adapter names are mentioned. The core,
the skills, and the validation loop never reach past a port to a named adapter;
they ask the registry for ports and use them abstractly.
"""

from __future__ import annotations

from di0.adapters.dbt_manifest import DbtManifestSchema
from di0.adapters.noop_execution import NoopExecution
from di0.adapters.sqlglot_dialect import SqlglotDialect
from di0.adapters.sqlglot_validation import SqlglotOfflineValidation
from di0.ports import DialectPort, ExecutionPort, SchemaPort, ValidationPort
from di0.profile import Profile


def build_schema_port(profile: Profile) -> SchemaPort:
    if profile.schema_source == "dbt-manifest":
        manifest_path = profile.options.get("manifest_path")
        if not manifest_path:
            raise ValueError("dbt-manifest schema source requires `manifest_path` in the profile")
        return DbtManifestSchema(str(manifest_path))
    raise ValueError(f"unknown schema_source: {profile.schema_source}")


def build_dialect_port(profile: Profile) -> DialectPort:
    return SqlglotDialect(profile.dialect)


def build_validation_port(profile: Profile) -> ValidationPort:
    if profile.validation == "sqlglot-offline":
        return SqlglotOfflineValidation(profile.dialect)
    raise ValueError(f"unknown validation tier: {profile.validation}")


def build_execution_port(profile: Profile) -> ExecutionPort:
    if profile.execution == "noop":
        return NoopExecution()
    raise ValueError(f"unknown execution target: {profile.execution}")
