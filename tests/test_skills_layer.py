"""Slice #8: the verb-skills layer is the agnostic surface.

Every skill must call a port through the CLI and name no warehouse, dialect, or
physical table - a skill that names a warehouse is a bug, like a hard-coded table.
"""

from __future__ import annotations

import json
from pathlib import Path

from di0 import cli

REPO_ROOT = Path(__file__).parent.parent
SKILLS_DIR = REPO_ROOT / "skills"

VERBS = (
    "resolve-schema",
    "compose-and-validate",
    "execute-and-author",
    "investigate",
    "reconcile",
    "narrate",
)

# Concrete warehouses, BI tools, and dialects that must never appear in a skill.
FORBIDDEN = (
    "snowflake",
    "metabase",
    "postgres",
    "cockroach",
    "bigquery",
    "redshift",
    "databricks",
    "drizzle",
    "strapi",
)


def test_all_verb_skills_present():
    for verb in VERBS:
        assert (SKILLS_DIR / verb / "SKILL.md").exists(), f"missing skill: {verb}"


def test_skills_name_no_warehouse_or_dialect():
    offenders = []
    for skill in SKILLS_DIR.glob("**/*.md"):
        text = skill.read_text().lower()
        for token in FORBIDDEN:
            if token in text:
                offenders.append(f"{skill.relative_to(REPO_ROOT)} names '{token}'")
    assert not offenders, "skills must stay warehouse-blind:\n" + "\n".join(offenders)


def test_schema_command_resolves(tmp_path, capsys):
    profile = tmp_path / "di0.profile.yml"
    profile.write_text(
        "schema_source: dbt-manifest\n"
        f"manifest_path: {REPO_ROOT / 'tests' / 'fixtures' / 'manifest.json'}\n"
        "dialect: snowflake\n"
        "validation: sqlglot-offline\n"
        "execution: noop\n"
    )
    exit_code = cli.main(["--profile", str(profile), "schema"])
    out = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert "dim_customers" in out["analytics"]
