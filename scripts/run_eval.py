#!/usr/bin/env python
"""Standalone wrapper around the `run_eval` management command.

Prefer `python manage.py run_eval` (or `make eval`). This wrapper exists so the
evaluation can be launched from the repository root or the /scripts mount in
Docker without changing directories.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def bootstrap_django() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    for candidate in (repo_root / "backend", Path("/app")):
        if candidate.exists():
            sys.path.insert(0, str(candidate))
            break
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()


def main() -> None:
    bootstrap_django()
    from django.core.management import call_command

    call_command("run_eval", *sys.argv[1:])


if __name__ == "__main__":
    main()
