"""`di0 check` scans the workspace recursively, skipping local combine-stage SQL."""

from __future__ import annotations

from di0 import cli
from di0.ports import ValidationResult


class _StubEngine:
    def __init__(self) -> None:
        self.checked: list = []

    def validate_paths(self, paths):
        self.checked = list(paths)
        return [(path, ValidationResult(ok=True, errors=())) for path in paths]


def test_check_skips_combine_stage_sql(tmp_path, monkeypatch):
    bundle = tmp_path / "arr_overview"
    bundle.mkdir()
    (bundle / "revenue.sql").write_text("SELECT 1")
    (bundle / "combine.sql").write_text("SELECT 1")
    (bundle / "_ranking.sql").write_text("SELECT 1")
    engine = _StubEngine()
    monkeypatch.setattr(cli, "_build_engine", lambda profile: engine)

    assert cli.main(["check", "--queries", str(bundle)]) == 0
    assert [path.name for path in engine.checked] == ["revenue.sql"]
