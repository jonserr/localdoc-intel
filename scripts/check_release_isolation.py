#!/usr/bin/env python
"""Probe Docker exclusions and smoke isolation using synthetic data only.

Requires Docker/Compose, but starts no services, pulls no images, and never
reads the developer's .env or uploads. Run from any directory.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
SMOKE_ENDPOINTS = {
    "DATABASE_URL": "postgres://localdoc:localdoc@db:5432/localdoc",
    "REDIS_URL": "redis://redis:6379/0",
    "QDRANT_URL": "http://qdrant:6333",
    "OLLAMA_BASE_URL": "http://127.0.0.1:9",
}
DISABLED_FLAGS = (
    "VECTOR_INDEXING_ENABLED",
    "VECTOR_SEARCH_ENABLED",
    "ANSWER_GENERATION_ENABLED",
    "ASYNC_INDEXING_ENABLED",
    "OCR_ENABLED",
)
CANARIES = (
    "backend/media/upload.txt",
    "backend/media/nested/upload.pdf",
    "backend/db.sqlite3",
    "backend/db.sqlite3-wal",
    "backend/db.sqlite3-shm",
    "backend/db.sqlite3-journal",
    "backend/nested/cache.sqlite3",
)


def run(command: list[str], cwd: Path) -> str:
    result = subprocess.run(
        command, cwd=cwd, capture_output=True, text=True, check=True
    )
    return result.stdout


def verify_context(output: Path) -> None:
    if not (output / "backend/keep.py").is_file():
        raise ValueError("Docker context probe did not retain application code")
    leaked = [name for name in CANARIES if (output / name).exists()]
    if leaked:
        raise ValueError(
            "Runtime data entered the Docker context: " + ", ".join(leaked)
        )


def check_context(root: Path, temporary: Path) -> None:
    context = temporary / "context"
    context.mkdir()
    shutil.copyfile(root / ".dockerignore", context / ".dockerignore")
    for name in CANARIES + ("backend/keep.py",):
        path = context / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Synthetic release-check fixture only.\n")
    (context / "Dockerfile").write_text("FROM scratch\nCOPY . /\n")
    output = temporary / "output"
    run(
        [
            "docker",
            "build",
            "--network",
            "none",
            "--output",
            f"type=local,dest={output}",
            ".",
        ],
        context,
    )
    verify_context(output)


def verify_smoke(config: dict) -> None:
    for service in ("backend", "celery"):
        values = config["services"][service]
        environment = values.get("environment", {})
        for key, expected in SMOKE_ENDPOINTS.items():
            if environment.get(key) != expected:
                raise ValueError(
                    f"{service}: {key} must target the isolated smoke service"
                )
        for key in DISABLED_FLAGS:
            if str(environment.get(key)).lower() != "false":
                raise ValueError(f"{service}: {key} must be disabled")
        if environment.get("VECTOR_MIN_SCORE") != "0.0":
            raise ValueError(f"{service}: smoke relevance floor must be explicit")
        if values.get("env_file") or environment.get("DEVELOPER_ENV_CANARY"):
            raise ValueError(f"{service}: developer environment leaked into smoke")
        if values.get("volumes") or values.get("extra_hosts"):
            raise ValueError(f"{service}: development mounts or host aliases remain")


def check_smoke(root: Path, temporary: Path) -> None:
    context = temporary / "compose"
    context.mkdir()
    for name in ("docker-compose.yml", "compose.smoke.yml"):
        shutil.copyfile(root / name, context / name)
    # Hostile values are placeholders, never real credentials or endpoints.
    (context / ".env").write_text(
        "DATABASE_URL=postgres://synthetic:synthetic@developer.invalid/private\n"
        "REDIS_URL=redis://developer.invalid:6379/0\n"
        "QDRANT_URL=http://developer.invalid:6333\n"
        "OLLAMA_BASE_URL=http://developer.invalid:11434\n"
        "VECTOR_MIN_SCORE=0.99\n"
        "DEVELOPER_ENV_CANARY=must-not-leak\n"
        + "".join(f"{key}=true\n" for key in DISABLED_FLAGS)
    )
    config = json.loads(
        run(
            [
                "docker",
                "compose",
                "-f",
                "docker-compose.yml",
                "-f",
                "compose.smoke.yml",
                "config",
                "--format",
                "json",
            ],
            context,
        )
    )
    verify_smoke(config)


def main() -> int:
    with TemporaryDirectory(prefix="localdoc-isolation-") as directory:
        temporary = Path(directory)
        check_context(ROOT, temporary)
        print(
            "Docker context excludes uploads and local databases; application code remains."
        )
        check_smoke(ROOT, temporary)
        print("Smoke service configuration is isolated from the developer environment.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        if isinstance(error, subprocess.CalledProcessError):
            print(error.stderr)
        raise SystemExit(f"Release isolation check failed: {error}") from error
