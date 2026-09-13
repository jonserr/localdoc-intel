#!/usr/bin/env python
"""Reject Compose host port bindings that are not loopback-only.

LocalDoc Intel has no authentication layer, so every published port must
bind to 127.0.0.1 or ::1. Docker publishes a port on all host interfaces when
the host address is omitted.

Usage:
    python scripts/check_compose_ports.py            # runs docker compose config
    python scripts/check_compose_ports.py --json FILE  # checks a saved config
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

LOOPBACK_ADDRESSES = {"127.0.0.1", "::1", "localhost"}


def find_public_ports(config: dict) -> list[str]:
    """Return one description per host port binding that is not loopback-only."""
    problems = []
    for service_name, service in (config.get("services") or {}).items():
        for entry in service.get("ports") or []:
            published, host_ip = _port_entry(entry)
            if published in (None, ""):
                # An unpublished target port stays inside the compose network.
                continue
            if host_ip not in LOOPBACK_ADDRESSES:
                shown_ip = host_ip or "0.0.0.0"
                problems.append(f"{service_name}: {shown_ip}:{published}")
    return problems


def _port_entry(entry) -> tuple[str | None, str]:
    if isinstance(entry, dict):
        published = entry.get("published")
        return (str(published) if published is not None else None), str(
            entry.get("host_ip") or ""
        )
    # Short syntax: [host_ip:]host_port:container_port[/protocol]
    text = str(entry).split("/")[0]
    parts = text.rsplit(":", 2)
    if len(parts) == 3:
        return parts[1], parts[0]
    if len(parts) == 2:
        return parts[0], ""
    return None, ""


def load_config(json_path: Path | None, compose_files: list[str]) -> dict:
    if json_path is not None:
        return json.loads(json_path.read_text(encoding="utf-8"))
    command = ["docker", "compose"]
    for compose_file in compose_files:
        command.extend(["-f", compose_file])
    command.extend(["config", "--format", "json"])
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    return json.loads(completed.stdout)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", type=Path, default=None, help="saved compose config")
    parser.add_argument(
        "-f", "--file", action="append", default=[], help="compose file(s) to resolve"
    )
    args = parser.parse_args()

    config = load_config(args.json, args.file)
    problems = find_public_ports(config)
    if problems:
        print("Host port bindings must use a loopback address (127.0.0.1):")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("All published Compose ports bind to loopback.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
