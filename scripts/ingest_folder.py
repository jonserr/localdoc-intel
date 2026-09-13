#!/usr/bin/env python
"""Ingest a folder of documents from the command line.

Usage:
    python scripts/ingest_folder.py <folder> [--collection NAME]
"""

from __future__ import annotations

import argparse
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
    parser = argparse.ArgumentParser(description="Ingest a folder into LocalDoc Intel.")
    parser.add_argument("folder", type=Path)
    parser.add_argument("--collection", default="Demo")
    args = parser.parse_args()

    bootstrap_django()
    from documents.ingestion import IngestionError, ingest_folder

    try:
        results, errors = ingest_folder(args.folder, collection_name=args.collection)
    except IngestionError as exc:
        raise SystemExit(str(exc)) from exc

    for result in results:
        state = "created" if result.created else "updated"
        print(f"{state}: {result.document.title}")
    for error in errors:
        print(f"error: {error['path']}: {error['error']}", file=sys.stderr)
    print(f"Ingested {len(results)} documents with {len(errors)} errors.")


if __name__ == "__main__":
    main()
