"""The version-sync check must actually catch a drifting version."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_version_sync.py"
spec = importlib.util.spec_from_file_location("check_version_sync", SCRIPT)
check_version_sync = importlib.util.module_from_spec(spec)
sys.modules["check_version_sync"] = check_version_sync
spec.loader.exec_module(check_version_sync)


def test_repository_versions_agree():
    versions = check_version_sync.collect()

    assert len(versions) == 6
    assert all(versions.values()), versions
    assert len(set(versions.values())) == 1, versions


def test_api_settings_version_matches_project_metadata():
    from config.version import APP_VERSION

    pyproject_version = check_version_sync.collect()["pyproject.toml"]
    assert pyproject_version == APP_VERSION


def test_frontend_and_root_package_versions_match():
    root = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    frontend = json.loads(
        (ROOT / "frontend" / "package.json").read_text(encoding="utf-8")
    )

    assert root["version"] == frontend["version"]


def test_disagreeing_versions_are_reported(monkeypatch, capsys):
    monkeypatch.setattr(
        check_version_sync,
        "collect",
        lambda: {
            "pyproject.toml": "1.0.0",
            "package.json": "1.0.0",
            "frontend/package.json": "1.1.0",
            "backend/config/version.py": "1.0.0",
        },
    )
    monkeypatch.setattr(sys, "argv", ["check_version_sync.py"])

    assert check_version_sync.main() == 1
    assert "disagree" in capsys.readouterr().out


def test_set_version_updates_both_lockfile_entries_without_changing_dependencies(
    tmp_path, monkeypatch
):
    import shutil

    for relative in (
        "pyproject.toml",
        "package.json",
        "frontend/package.json",
        "frontend/package-lock.json",
        "backend/config/version.py",
    ):
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, destination)
    lock_path = tmp_path / "frontend/package-lock.json"
    previous = json.loads(lock_path.read_text())
    monkeypatch.setattr(check_version_sync, "ROOT", tmp_path)
    check_version_sync.write_version("1.2.3")
    assert set(check_version_sync.collect().values()) == {"1.2.3"}
    updated = json.loads(lock_path.read_text())
    assert (
        updated["packages"]["node_modules/next"]
        == previous["packages"]["node_modules/next"]
    )
