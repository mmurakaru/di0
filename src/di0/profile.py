"""Load di0.profile.yml into a typed config.

The profile is the only place the warehouse, dialect, schema source, validation
tier, and execution target are named. The core reads these as opaque strings and
hands them to the registry, which maps them to adapters.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT_PROFILE_NAME = "di0.profile.yml"


@dataclass(frozen=True)
class Profile:
    schema_source: str
    dialect: str
    validation: str
    execution: str
    # Free-form per-adapter settings (paths, endpoints), kept out of the core.
    options: dict[str, object]

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> Profile:
        required = ("schema_source", "dialect", "validation", "execution")
        missing = [key for key in required if key not in data]
        if missing:
            raise ValueError(f"profile is missing required keys: {', '.join(missing)}")
        known = set(required)
        return cls(
            schema_source=str(data["schema_source"]),
            dialect=str(data["dialect"]),
            validation=str(data["validation"]),
            execution=str(data["execution"]),
            options={k: v for k, v in data.items() if k not in known},
        )


def load_profile(path: str | Path = DEFAULT_PROFILE_NAME) -> Profile:
    raw = yaml.safe_load(Path(path).read_text()) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"profile at {path} must be a mapping")
    return Profile.from_dict(raw)
