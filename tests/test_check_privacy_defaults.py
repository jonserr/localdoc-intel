"""Unit tests for the telemetry opt-out check (no Docker required)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_privacy_defaults.py"
spec = importlib.util.spec_from_file_location("check_privacy_defaults", SCRIPT)
check_privacy_defaults = importlib.util.module_from_spec(spec)
sys.modules["check_privacy_defaults"] = check_privacy_defaults
spec.loader.exec_module(check_privacy_defaults)
find_telemetry_gaps = check_privacy_defaults.find_telemetry_gaps


def config(qdrant_env=None, frontend_env=None):
    services = {"db": {}}
    if qdrant_env is not None:
        services["qdrant"] = {"environment": qdrant_env}
    if frontend_env is not None:
        services["frontend"] = {"environment": frontend_env}
    return {"services": services}


def test_opted_out_services_pass():
    resolved = config(
        {"QDRANT__TELEMETRY_DISABLED": "true"}, {"NEXT_TELEMETRY_DISABLED": "1"}
    )

    assert find_telemetry_gaps(resolved) == []


def test_list_syntax_is_accepted():
    resolved = config(
        ["QDRANT__TELEMETRY_DISABLED=true"], ["NEXT_TELEMETRY_DISABLED=1"]
    )

    assert find_telemetry_gaps(resolved) == []


def test_missing_qdrant_opt_out_is_reported():
    resolved = config({"QDRANT__SERVICE__HTTP_PORT": "6333"}, None)

    problems = find_telemetry_gaps(resolved)

    assert len(problems) == 1
    assert "QDRANT__TELEMETRY_DISABLED is not set" in problems[0]


def test_non_opt_out_value_is_reported():
    resolved = config(
        {"QDRANT__TELEMETRY_DISABLED": "false"}, {"NEXT_TELEMETRY_DISABLED": "0"}
    )

    problems = find_telemetry_gaps(resolved)

    assert len(problems) == 2
    assert any("QDRANT__TELEMETRY_DISABLED=false" in problem for problem in problems)
    assert any("NEXT_TELEMETRY_DISABLED=0" in problem for problem in problems)


def test_absent_service_is_not_required():
    assert find_telemetry_gaps({"services": {"backend": {}}}) == []


def test_shipped_compose_file_disables_telemetry():
    """The repository's own Compose file must pass without Docker."""
    yaml = pytest.importorskip("yaml", reason="PyYAML is not installed here")
    compose_file = Path(__file__).resolve().parents[1] / "docker-compose.yml"
    if not compose_file.is_file():
        pytest.skip("the packaged image does not ship the Compose files")

    assert (
        find_telemetry_gaps(yaml.safe_load(compose_file.read_text(encoding="utf-8")))
        == []
    )
