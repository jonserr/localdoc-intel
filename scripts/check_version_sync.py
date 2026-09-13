#!/usr/bin/env python
"""Verify that every place the release version appears agrees.

Sources checked:
  pyproject.toml            [project] version
  package.json              root workspace version
  frontend/package.json     frontend package version
  frontend/package-lock.json top-level and root-package versions
  backend/config/version.py APP_VERSION, served by /api/settings/

Usage:
    python scripts/check_version_sync.py            # verify
    python scripts/check_version_sync.py --set 1.1.0  # rewrite all of them
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+([-+][0-9A-Za-z.-]+)?$")


def read_pyproject() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return match.group(1) if match else ""


def read_json_version(relative: str) -> str:
    return json.loads((ROOT / relative).read_text(encoding="utf-8")).get("version", "")


def read_app_version() -> str:
    text = (ROOT / "backend" / "config" / "version.py").read_text(encoding="utf-8")
    match = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return match.group(1) if match else ""


def collect() -> dict[str, str]:
    return {
        "pyproject.toml": read_pyproject(),
        "package.json": read_json_version("package.json"),
        "frontend/package.json": read_json_version("frontend/package.json"),
        "backend/config/version.py": read_app_version(),
        "frontend/package-lock.json": read_json_version("frontend/package-lock.json"),
        'frontend/package-lock.json packages[""]': json.loads(
            (ROOT / "frontend/package-lock.json").read_text(encoding="utf-8")
        )
        .get("packages", {})
        .get("", {})
        .get("version", ""),
    }


def write_version(version: str) -> None:
    path = ROOT / "pyproject.toml"
    text = path.read_text(encoding="utf-8")
    path.write_text(
        re.sub(
            r'^version\s*=\s*"[^"]+"',
            f'version = "{version}"',
            text,
            count=1,
            flags=re.MULTILINE,
        ),
        encoding="utf-8",
    )

    for relative in ("package.json", "frontend/package.json"):
        path = ROOT / relative
        data = json.loads(path.read_text(encoding="utf-8"))
        data["version"] = version
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    path = ROOT / "frontend/package-lock.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["version"] = version
    data["packages"][""]["version"] = version
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    path = ROOT / "backend" / "config" / "version.py"
    text = path.read_text(encoding="utf-8")
    path.write_text(
        re.sub(
            r'^APP_VERSION\s*=\s*"[^"]+"',
            f'APP_VERSION = "{version}"',
            text,
            count=1,
            flags=re.MULTILINE,
        ),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--set", dest="new_version", default="")
    args = parser.parse_args()

    if args.new_version:
        if not VERSION_PATTERN.match(args.new_version):
            print(f"Not a valid version: {args.new_version}", file=sys.stderr)
            return 2
        write_version(args.new_version)
        print(f"Set version to {args.new_version} in {len(collect())} version fields.")

    versions = collect()
    missing = [name for name, value in versions.items() if not value]
    if missing:
        print("Could not read a version from: " + ", ".join(missing), file=sys.stderr)
        return 1

    unique = set(versions.values())
    if len(unique) > 1:
        print("Version values disagree:")
        for name, value in versions.items():
            print(f"  {name}: {value}")
        print(
            "\nSynchronize them with: python scripts/check_version_sync.py --set X.Y.Z"
        )
        return 1

    print(f"All version values agree: {unique.pop()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
