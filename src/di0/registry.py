"""Wire a profile to concrete adapters.

This is the one composition edge where adapter names are mentioned. The core,
the skills, and the validation loop never reach past a port to a named adapter;
they ask the registry for ports and use them abstractly.
"""

from __future__ import annotations

from di0.adapters.dbt_manifest import DbtManifestSchema
from di0.adapters.drizzle_schema import DrizzleSnapshotSchema
from di0.adapters.explain_validation import ExplainValidation
from di0.adapters.http_rows_execution import HttpRowsExecution
from di0.adapters.metabase_execution import MetabaseExecution
from di0.adapters.noop_execution import NoopExecution
from di0.adapters.sqlglot_dialect import SqlglotDialect
from di0.adapters.sqlglot_validation import SqlglotOfflineValidation
from di0.adapters.strapi_schema import StrapiContentTypeSchema
from di0.ports import DialectPort, ExecutionPort, SchemaPort, ValidationPort
from di0.profile import Profile


def build_schema_port(profile: Profile) -> SchemaPort:
    if profile.schema_source == "dbt-manifest":
        manifest_path = profile.options.get("manifest_path")
        if not manifest_path:
            raise ValueError("dbt-manifest schema source requires `manifest_path` in the profile")
        return DbtManifestSchema(str(manifest_path))
    if profile.schema_source == "strapi-content-types":
        schema_dir = profile.options.get("schema_dir")
        if not schema_dir:
            raise ValueError("strapi-content-types schema source requires `schema_dir`")
        return StrapiContentTypeSchema(
            str(schema_dir),
            namespace=str(profile.options.get("namespace", "public")),
            information_schema_path=profile.options.get("information_schema_path"),
        )
    if profile.schema_source == "drizzle-snapshot":
        snapshot_path = profile.options.get("snapshot_path")
        if not snapshot_path:
            raise ValueError("drizzle-snapshot schema source requires `snapshot_path`")
        return DrizzleSnapshotSchema(
            str(snapshot_path),
            default_namespace=str(profile.options.get("namespace", "public")),
        )
    raise ValueError(f"unknown schema_source: {profile.schema_source}")


def build_dialect_port(profile: Profile) -> DialectPort:
    return SqlglotDialect(profile.dialect)


def build_validation_port(
    profile: Profile, execution_port: ExecutionPort | None = None
) -> ValidationPort:
    if profile.validation == "sqlglot-offline":
        return SqlglotOfflineValidation(profile.dialect)
    if profile.validation == "explain":
        if execution_port is None or not hasattr(execution_port, "run_native"):
            raise ValueError(
                "explain validation requires an execution adapter that can run native SQL "
                "(e.g. execution: metabase)"
            )
        return ExplainValidation(execution_port)
    raise ValueError(f"unknown validation tier: {profile.validation}")


def build_execution_port(profile: Profile) -> ExecutionPort:
    if profile.execution == "noop":
        return NoopExecution()
    if profile.execution == "metabase":
        base_url = profile.options.get("metabase_url")
        database_id = profile.options.get("metabase_database_id")
        if not base_url or database_id is None:
            raise ValueError(
                "metabase execution requires `metabase_url` and `metabase_database_id` "
                "in the profile"
            )
        api_key_env = profile.options.get("metabase_api_key_env")
        kwargs = {"api_key_env": str(api_key_env)} if api_key_env else {}
        return MetabaseExecution(str(base_url), int(database_id), **kwargs)
    if profile.execution == "http-rows":
        base_url = profile.options.get("rows_url")
        if not base_url:
            raise ValueError("http-rows execution requires `rows_url` in the profile")
        api_key_env = profile.options.get("rows_api_key_env")
        kwargs = {"api_key_env": str(api_key_env)} if api_key_env else {}
        return HttpRowsExecution(str(base_url), **kwargs)
    raise ValueError(f"unknown execution target: {profile.execution}")
