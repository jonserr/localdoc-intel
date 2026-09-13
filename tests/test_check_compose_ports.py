"""Unit tests for the Compose port-binding check (no Docker required)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_compose_ports.py"
spec = importlib.util.spec_from_file_location("check_compose_ports", SCRIPT)
check_compose_ports = importlib.util.module_from_spec(spec)
sys.modules["check_compose_ports"] = check_compose_ports
spec.loader.exec_module(check_compose_ports)
find_public_ports = check_compose_ports.find_public_ports


def test_loopback_long_syntax_passes():
    config = {
        "services": {
            "frontend": {
                "ports": [
                    {
                        "mode": "ingress",
                        "host_ip": "127.0.0.1",
                        "target": 3000,
                        "published": "3000",
                        "protocol": "tcp",
                    }
                ]
            },
            "db": {},
        }
    }
    assert find_public_ports(config) == []


def test_missing_host_ip_is_reported_as_public():
    config = {
        "services": {
            "db": {
                "ports": [
                    {"mode": "ingress", "target": 5432, "published": "5432"},
                ]
            }
        }
    }
    assert find_public_ports(config) == ["db: 0.0.0.0:5432"]


def test_explicit_wildcard_is_reported():
    config = {"services": {"api": {"ports": ["0.0.0.0:8000:8000"]}}}
    assert find_public_ports(config) == ["api: 0.0.0.0:8000"]


def test_short_syntax_variants():
    config = {
        "services": {
            "a": {"ports": ["127.0.0.1:3000:3000", "::1:4000:4000/tcp"]},
            "b": {"ports": ["8000:8000"]},
        }
    }
    assert find_public_ports(config) == ["b: 0.0.0.0:8000"]


def test_unpublished_target_port_is_ignored():
    config = {"services": {"a": {"ports": [{"target": 9000}]}}}
    assert find_public_ports(config) == []
