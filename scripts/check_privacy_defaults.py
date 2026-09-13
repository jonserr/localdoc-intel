#!/usr/bin/env python
"""Reject Compose services that leave vendor telemetry at its default.

Qdrant sends anonymized usage statistics unless telemetry is disabled, and
Next.js collects anonymous usage data unless the opt-out is set. Both are
configuration, so they are checked the same way as published ports.

Usage:
    python scripts/check_privacy_defaults.py            # runs docker compose config
    python scripts/check_privacy_defaults.py --json FILE  # checks a saved config
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

# service name -> (environment variable, accepted values, why it matters)
REQUIRED_OPT_OUTS = {
    "qdrant": (
        "QDRANT__TELEMETRY_DISABLED",
        {"true", "1"},
        "Qdrant reports anonymized usage statistics by default.",
    ),
    "frontend": (
        "NEXT_TELEMETRY_DISABLED",
        {"1", "true"},
        "Next.js collects anonymous usage telemetry by default.",
    ),
}


def _environment(service: dict) -> dict[str, str]:
    """Normalize both Compose environment forms into a string mapping."""
    environment = service.get("environment") or {}
    if isinstance(environment, list):
        pairs = [str(entry).split("=", 1) for entry in environment]
        environment = {pair[0]: pair[1] if len(pair) > 1 else "" for pair in pairs}
    return {
        str(key): "" if value is None else str(value)
        for key, value in environment.items()
    }


def find_telemetry_gaps(config: dict) -> list[str]:
    """Return one description per service that does not opt out of telemetry."""
    problems = []
    services = config.get("services") or {}
    for name, (variable, accepted, reason) in REQUIRED_OPT_OUTS.items():
        service = services.get(name)
        if service is None:
            continue
        value = _environment(service).get(variable)
        if value is None:
            problems.append(f"{name}: {variable} is not set. {reason}")
        elif value.strip().lower() not in accepted:
            problems.append(
                f"{name}: {variable}={value} is not an opt-out value "
                f"({', '.join(sorted(accepted))}). {reason}"
            )
    return problems


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
    problems = find_telemetry_gaps(config)
    if problems:
        print("Vendor telemetry must be disabled explicitly:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("All telemetry opt-outs are set.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
