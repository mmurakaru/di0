"""`di0 doctor` - self-diagnose a workspace's setup before anything runs.

doctor runs an ordered sequence of checks over a profile and reports each as
pass/fail with a concrete fix hint, so a first-run user (or an agent) learns
exactly what to correct. It stays agnostic: it talks only to the ports and reads
adapter and credential-env-var names generically from the profile, so it names no
warehouse, dialect, or BI tool. That is why this module is safe under `di0 guard`.

The checks, in order:
  1. profile      - the profile parses and its adapters wire up (build_engine).
  2. schema       - the schema source resolves to a non-empty schema.
  3. credentials  - every credential env var the profile names is set.
  4. validation   - a trivial query composes and validates against the schema.
  5. connectivity - (only with probe) the execution target answers a trivial query.

A failing check is classed as either a config problem or an unreachable target,
which the CLI maps to a sysexit code.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from di0.profile import Profile, load_profile
from di0.registry import build_engine

# The class of a failing check; the CLI maps these to sysexit codes.
CATEGORY_CONFIG = "config"
CATEGORY_UNAVAILABLE = "unavailable"

# A profile option whose key ends in this suffix names the ENVIRONMENT VARIABLE
# that holds a credential - the secret itself is never stored in the profile.
# doctor reads these generically, so it never has to know any adapter's name.
_CREDENTIAL_ENV_SUFFIX = "_env"

# A query that resolves no references, so it round-trips against any schema.
_TRIVIAL_QUERY = "SELECT 1"


@dataclass(frozen=True)
class Check:
    """One diagnostic outcome: a name, pass/fail, what was found, and a fix hint."""

    name: str
    passed: bool
    detail: str
    hint: str = ""
    # Only meaningful when `passed` is False.
    category: str = CATEGORY_CONFIG


@dataclass(frozen=True)
class Report:
    checks: tuple[Check, ...]

    @property
    def ok(self) -> bool:
        return all(check.passed for check in self.checks)

    @property
    def exit_category(self) -> str | None:
        """The class of the run: a config problem outranks an unreachable target."""
        failed = {check.category for check in self.checks if not check.passed}
        if CATEGORY_CONFIG in failed:
            return CATEGORY_CONFIG
        if CATEGORY_UNAVAILABLE in failed:
            return CATEGORY_UNAVAILABLE
        return None


def _credential_env_names(profile: Profile) -> list[str]:
    """Every credential env-var name the profile declares, read generically."""
    names: list[str] = []
    for key, value in profile.options.items():
        if key.endswith(_CREDENTIAL_ENV_SUFFIX) and isinstance(value, str) and value:
            names.append(value)
    return names


def _check_credentials(profile: Profile) -> Check:
    declared = _credential_env_names(profile)
    if not declared:
        return Check("credentials", True, "the profile names no credential env vars")
    missing = [name for name in declared if not os.environ.get(name)]
    if missing:
        listed = ", ".join(missing)
        return Check(
            "credentials",
            False,
            f"required credential env var(s) not set: {listed}",
            hint=f"export the missing environment variable(s) in your shell: {listed}",
            category=CATEGORY_CONFIG,
        )
    return Check("credentials", True, f"all credential env vars are set: {', '.join(declared)}")


def run_checks(profile_path: str, probe: bool = False) -> Report:
    """Run every diagnostic and return the collected report.

    The first check (profile wires up) short-circuits: without an engine, none of
    the later checks can run, so a config problem is reported on its own.
    """
    checks: list[Check] = []

    try:
        profile = load_profile(profile_path)
        engine = build_engine(profile)
    except Exception as error:  # noqa: BLE001 - any load/wire failure is a config problem
        checks.append(
            Check(
                "profile",
                False,
                str(error),
                hint="fix the profile so it parses and its adapters wire up; "
                "`di0 init` scaffolds a commented starter",
                category=CATEGORY_CONFIG,
            )
        )
        return Report(tuple(checks))
    checks.append(Check("profile", True, "the profile parses and its adapters wire up"))

    schema_ok = False
    try:
        schema = engine.schema_port.resolve()
        if schema:
            schema_ok = True
            checks.append(
                Check("schema", True, f"the schema source resolved {len(schema)} namespace(s)")
            )
        else:
            checks.append(
                Check(
                    "schema",
                    False,
                    "the schema source resolved to an empty schema",
                    hint="point the schema source at a populated schema",
                    category=CATEGORY_UNAVAILABLE,
                )
            )
    except Exception as error:  # noqa: BLE001 - an unresolvable source is unreachable
        checks.append(
            Check(
                "schema",
                False,
                str(error),
                hint="make the schema source reachable (check its path or endpoint)",
                category=CATEGORY_UNAVAILABLE,
            )
        )

    checks.append(_check_credentials(profile))

    if schema_ok:
        try:
            result = engine.validate(_TRIVIAL_QUERY)
            if result.ok:
                checks.append(
                    Check("validation", True, "a trivial query composes and validates")
                )
            else:
                checks.append(
                    Check(
                        "validation",
                        False,
                        "; ".join(result.errors),
                        hint="check the dialect and validation tier in the profile",
                        category=CATEGORY_UNAVAILABLE,
                    )
                )
        except Exception as error:  # noqa: BLE001 - compose/validate blew up
            checks.append(
                Check(
                    "validation",
                    False,
                    str(error),
                    hint="check the dialect and validation tier in the profile",
                    category=CATEGORY_UNAVAILABLE,
                )
            )

    if probe:
        # TODO(#66): a full probe compares the execution target's capability shape
        # against the profile (drift detection). For now this is a minimal
        # reachability round-trip: validate then execute a trivial query.
        try:
            engine.query(_TRIVIAL_QUERY)
            checks.append(
                Check("connectivity", True, "the execution target answered a trivial query")
            )
        except Exception as error:  # noqa: BLE001 - the target is unreachable
            checks.append(
                Check(
                    "connectivity",
                    False,
                    str(error),
                    hint="check the execution target is reachable and its credentials are valid",
                    category=CATEGORY_UNAVAILABLE,
                )
            )

    return Report(tuple(checks))
