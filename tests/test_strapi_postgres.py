"""Slice #5: a Strapi schema source + Postgres dialect, profile-only swap.

Same engine, same flow as the dbt/Snowflake path - only the profile changed.
The join goes through the generated `*_lnk` link table, resolved from the
content-type schema rather than typed by hand.
"""

from __future__ import annotations

import json
from pathlib import Path

from di0.core import Engine
from di0.profile import Profile
from di0.registry import (
    build_dialect_port,
    build_execution_port,
    build_schema_port,
    build_validation_port,
)

STRAPI_DIR = str(Path(__file__).parent / "fixtures" / "strapi")

PUBLISHED_AUTHOR_RANKING = """
SELECT
  au.name                          AS author,
  COUNT(DISTINCT ar.id)            AS published_articles,
  COALESCE(SUM(ar.word_count), 0)  AS total_words
FROM blog_articles ar
JOIN blog_articles_author_lnk lnk ON lnk.blog_article_id = ar.id
JOIN blog_authors au              ON au.id = lnk.blog_author_id
WHERE ar.published_at IS NOT NULL
GROUP BY au.name
ORDER BY total_words DESC
"""


def _engine(options: dict) -> Engine:
    profile = Profile(
        schema_source="strapi-content-types",
        dialect="postgres",
        validation="sqlglot-offline",
        execution="noop",
        options={"schema_dir": STRAPI_DIR, **options},
    )
    return Engine(
        schema_port=build_schema_port(profile),
        dialect_port=build_dialect_port(profile),
        validation_port=build_validation_port(profile),
        execution_port=build_execution_port(profile),
    )


def test_link_table_resolved_from_convention():
    schema = build_schema_port(
        Profile("strapi-content-types", "postgres", "sqlglot-offline", "noop",
                {"schema_dir": STRAPI_DIR})
    ).resolve()
    public = schema["public"]
    assert "blog_articles_author_lnk" in public
    assert set(public["blog_articles_author_lnk"]) == {"blog_article_id", "blog_author_id"}
    assert "word_count" in public["blog_articles"]  # wordCount snake-cased


def test_postgres_join_through_link_table_validates():
    assert _engine({}).validate(PUBLISHED_AUTHOR_RANKING).ok


def test_unknown_column_on_strapi_schema_fails():
    result = _engine({}).validate("SELECT made_up FROM blog_authors")
    assert not result.ok


def test_information_schema_overrides_convention(tmp_path):
    info = tmp_path / "information_schema.json"
    info.write_text(
        json.dumps(
            {
                "blog_articles_author_lnk": {
                    "blog_article_id": "integer",
                    "blog_author_id": "integer",
                    "article_order": "double precision",
                }
            }
        )
    )
    schema = _engine({"information_schema_path": str(info)}).schema_port.resolve()
    assert "article_order" in schema["public"]["blog_articles_author_lnk"]
