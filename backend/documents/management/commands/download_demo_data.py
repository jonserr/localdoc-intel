"""Download receipt PDFs for the local demo intake folder."""

from __future__ import annotations

import importlib
import shutil
from dataclasses import dataclass
from pathlib import Path

from django.core.management.base import BaseCommand

DEFAULT_DATASET = "jenswalter/receipts"
# Copy half the dataset by default. The full set is about 1,150 receipts, and a
# collection review costs roughly one second per stored chunk, so the whole set
# turns a demo into a long wait. A share adapts if the dataset changes size.
DEFAULT_SHARE = 0.5


@dataclass(frozen=True)
class CopyResult:
    source_count: int
    copied_count: int
    skipped_existing: int
    output_dir: Path


def default_demo_intake_path() -> Path:
    candidates = [
        Path("/data/demo_intake"),
        Path(__file__).resolve().parents[4] / "data" / "demo_intake",
        Path("data/demo_intake"),
    ]
    for candidate in candidates:
        if candidate.parent.exists():
            return candidate
    return candidates[-1]


def import_kagglehub():
    try:
        return importlib.import_module("kagglehub")
    except ImportError:
        return None


def evenly_spaced(paths: list[Path], limit: int) -> list[Path]:
    """Take `limit` files spread across the sorted list, not the first N.

    Receipt filenames start with the merchant, so the first N would collect a
    few merchants many times over instead of a cross-section of the dataset.
    """
    if limit <= 0 or len(paths) <= limit:
        return paths
    step = len(paths) / limit
    return [paths[int(index * step)] for index in range(limit)]


def copy_receipt_pdfs(
    source_dir: Path, output_dir: Path, limit: int | None = None
) -> CopyResult:
    """Copy receipt PDFs. `limit` None takes half the dataset, 0 takes all."""
    output_dir.mkdir(parents=True, exist_ok=True)
    available = sorted(
        path
        for path in source_dir.rglob("*")
        if path.is_file() and path.suffix.lower() == ".pdf"
    )
    if limit is None:
        limit = round(len(available) * DEFAULT_SHARE)
    pdfs = evenly_spaced(available, limit)
    copied_count = 0
    skipped_existing = 0
    for source in pdfs:
        destination = output_dir / source.name
        if destination.exists() and destination.stat().st_size == source.stat().st_size:
            skipped_existing += 1
            continue
        shutil.copy2(source, destination)
        copied_count += 1
    return CopyResult(
        source_count=len(available),
        copied_count=copied_count,
        skipped_existing=skipped_existing,
        output_dir=output_dir,
    )


class Command(BaseCommand):
    help = "Download Kaggle receipts PDFs into data/demo_intake."

    def add_arguments(self, parser):
        parser.add_argument("--dataset", default=DEFAULT_DATASET)
        parser.add_argument("--output-dir", default="")
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help=(
                "Copy at most this many PDFs, spread across the dataset. "
                "Default copies half. 0 copies all."
            ),
        )

    def handle(self, *args, **options):
        output_dir = (
            Path(options["output_dir"])
            if options["output_dir"]
            else default_demo_intake_path()
        )
        output_dir.mkdir(parents=True, exist_ok=True)

        kagglehub = import_kagglehub()
        if kagglehub is None:
            self.stdout.write(
                "Skipped demo data download: kagglehub is not installed. "
                "Rebuild the backend image or install kagglehub in your Python environment."
            )
            return

        try:
            dataset_path = Path(kagglehub.dataset_download(options["dataset"]))
        except Exception as exc:
            self.stdout.write(
                "Skipped demo data download: KaggleHub could not download the "
                f"dataset ({exc}). This can happen when Kaggle requires network "
                "access, authentication, consent, or accepted dataset terms."
            )
            return

        result = copy_receipt_pdfs(dataset_path, output_dir, options["limit"])
        if result.source_count == 0:
            self.stdout.write(
                f"Skipped demo data copy: no PDF files found in {dataset_path}."
            )
            return

        self.stdout.write(
            f"Copied {result.copied_count} receipt PDFs into {result.output_dir} "
            f"({result.skipped_existing} existing, {result.source_count} PDFs available). "
            "Half the dataset by default. Pass --limit 0 for all of it."
        )
