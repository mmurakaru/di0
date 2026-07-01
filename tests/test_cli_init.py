"""`di0 init` scaffolds a workspace from a template (or empty), gitignored."""

from __future__ import annotations

from di0 import cli


def test_init_scaffolds_workspace_from_template(tmp_path, monkeypatch):
    template = tmp_path / "tpl"
    (template / "queries").mkdir(parents=True)
    (template / "queries" / "a.sql").write_text("SELECT 1")
    (template / "di0.profile.yml").write_text("schema_source: x\n")
    workspace = tmp_path / "ws"
    monkeypatch.setenv("DI0_WORKSPACE", str(workspace))  # absolute -> no .gitignore edit

    assert cli.main(["init", "--template", str(template)]) == 0
    assert (workspace / "queries" / "a.sql").read_text() == "SELECT 1"
    assert (workspace / "di0.profile.yml").exists()


def test_init_creates_empty_workspace_without_template(tmp_path, monkeypatch):
    workspace = tmp_path / "ws"
    monkeypatch.setenv("DI0_WORKSPACE", str(workspace))

    assert cli.main(["init", "--template", str(tmp_path / "missing")]) == 0
    assert (workspace / "queries").is_dir()
    assert (workspace / "context").is_dir()
