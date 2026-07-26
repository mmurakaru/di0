"""ValidationPort adapter: enforce a governance policy on top of schema validity.

A policy is optional and opt-in: a profile turns it on with a ``policy: <path>``
key pointing at a standalone ``policy.yml``. When no policy is configured the
registry never builds this adapter, so behaviour is byte-for-byte the base
validator's. When one is, this wraps the configured base validator: schema
validity is proven first, then - and only then - the policy is checked against the
query's parsed shape.

The three rules are deliberately generic; the concrete column, table, and limit
values live in the user's ``policy.yml`` at runtime, never as literals here:

- ``deny_columns``: column names forbidden anywhere in a query. An entry matches a
  reference when the entry is a suffix of the reference's qualified name, so a bare
  name (``ssn``) forbids that column however it is qualified, and a qualified entry
  (``pii.ssn``) forbids the qualified form.
- ``require_aggregation``: tables that may only be queried in aggregate. A query
  touching one must carry a GROUP BY or an aggregate function.
- ``row_limit``: the largest LIMIT a query may carry; a missing or larger LIMIT is
  denied.

di0 never rewrites SQL to satisfy a policy - a violation is a denial, nothing more.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import sqlglot
import yaml
from sqlglot import exp
from sqlglot.errors import SqlglotError

from di0.adapters._sqlglot import to_sqlglot_dialect
from di0.ports import Schema, ValidationPort, ValidationResult


@dataclass(frozen=True)
class Policy:
    """A governance policy: what a query may reference, aggregate, and return."""

    deny_columns: tuple[str, ...] = ()
    require_aggregation: tuple[str, ...] = ()
    row_limit: int | None = None


def load_policy(path: str | Path) -> Policy:
    """Load a standalone ``policy.yml`` into a typed Policy."""
    raw = yaml.safe_load(Path(path).read_text()) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"policy at {path} must be a mapping")
    row_limit = raw.get("row_limit")
    return Policy(
        deny_columns=tuple(str(name) for name in (raw.get("deny_columns") or ())),
        require_aggregation=tuple(str(name) for name in (raw.get("require_aggregation") or ())),
        row_limit=int(row_limit) if row_limit is not None else None,
    )


def _parts(node: exp.Expression) -> list[str]:
    """The lower-cased dotted parts of a column or table reference."""
    return [str(part.name).lower() for part in node.parts]


def _is_suffix(entry: list[str], reference: list[str]) -> bool:
    """Whether a policy entry is a trailing match of a reference's qualified parts."""
    return len(entry) <= len(reference) and reference[len(reference) - len(entry) :] == entry


class PolicyValidation:
    """Compose a base ValidationPort with a policy gate.

    Base validity comes first: if the query does not resolve against the schema
    that is an ordinary validation error, returned unchanged, and the policy is
    never consulted. Only a schema-valid query is checked against the policy, and a
    violation yields a denial (``ok=False`` with ``denied=True``).
    """

    def __init__(self, base: ValidationPort, policy: Policy, dialect: str = "") -> None:
        self._base = base
        self._policy = policy
        self._dialect = to_sqlglot_dialect(dialect) if dialect else None

    def validate(self, sql: str, schema: Schema) -> ValidationResult:
        base_result = self._base.validate(sql, schema)
        if not base_result.ok:
            return base_result
        violations = self._violations(sql)
        if violations:
            return ValidationResult(ok=False, errors=tuple(violations), denied=True)
        return base_result

    def _violations(self, sql: str) -> list[str]:
        try:
            expression = sqlglot.parse_one(sql, read=self._dialect)
        except SqlglotError as error:
            # Base validity already held; if the policy checker cannot parse the
            # query it cannot prove the policy holds, so it fails closed.
            return [f"policy: could not parse the query to evaluate policy ({error})"]
        return [
            *self._denied_columns(expression),
            *self._missing_aggregation(expression),
            *self._row_limit(expression),
        ]

    def _denied_columns(self, expression: exp.Expression) -> list[str]:
        if not self._policy.deny_columns:
            return []
        referenced = [_parts(column) for column in expression.find_all(exp.Column)]
        violations: list[str] = []
        for rule in self._policy.deny_columns:
            entry = rule.lower().split(".")
            if any(_is_suffix(entry, parts) for parts in referenced):
                violations.append(f"policy: column {rule!r} is denied")
        return violations

    def _missing_aggregation(self, expression: exp.Expression) -> list[str]:
        if not self._policy.require_aggregation:
            return []
        has_aggregation = (
            expression.find(exp.Group) is not None or expression.find(exp.AggFunc) is not None
        )
        if has_aggregation:
            return []
        referenced = [_parts(table) for table in expression.find_all(exp.Table)]
        violations: list[str] = []
        for rule in self._policy.require_aggregation:
            entry = rule.lower().split(".")
            if any(_is_suffix(entry, parts) for parts in referenced):
                violations.append(
                    f"policy: querying {rule!r} requires aggregation "
                    "(a GROUP BY or an aggregate function)"
                )
        return violations

    def _row_limit(self, expression: exp.Expression) -> list[str]:
        maximum = self._policy.row_limit
        if maximum is None:
            return []
        node = expression.args.get("limit")
        if node is None:
            return [f"policy: query must carry a LIMIT of at most {maximum}"]
        try:
            value = int(node.expression.name)
        except (AttributeError, ValueError):
            return [f"policy: query LIMIT must be an integer literal of at most {maximum}"]
        if value > maximum:
            return [f"policy: query LIMIT {value} exceeds the maximum of {maximum}"]
        return []
