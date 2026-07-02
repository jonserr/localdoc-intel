"""Ingest local demo intake files into a demo collection."""

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from documents.ingestion import format_extension_counts, ingest_folder

ANSI_GREEN = "\033[32m"
ANSI_RED = "\033[31m"
ANSI_RESET = "\033[0m"
PROGRESS_BAR_WIDTH = 30


def default_demo_intake_path() -> Path:
    candidates = [
        Path("/data/demo_intake"),
        Path(__file__).resolve().parents[4] / "data" / "demo_intake",
        Path("data/demo_intake"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[-1]


def progress_bar(completed: int, total: int) -> str:
    if total <= 0:
        return "[" + "-" * PROGRESS_BAR_WIDTH + "]"
    bounded = max(0, min(completed, total))
    filled = round((bounded / total) * PROGRESS_BAR_WIDTH)
    return "[" + "=" * filled + "-" * (PROGRESS_BAR_WIDTH - filled) + "]"


class Command(BaseCommand):
    help = "Ingest local files from data/demo_intake into the Demo collection."

    def add_arguments(self, parser):
        parser.add_argument("--folder", default="")
        parser.add_argument("--collection", default="Demo")
        parser.add_argument(
            "--no-progress",
            action="store_true",
            help="Suppress per-file progress output.",
        )

    def handle(self, *args, **options):
        folder = (
            Path(options["folder"]) if options["folder"] else default_demo_intake_path()
        )
        folder.mkdir(parents=True, exist_ok=True)

        memory = settings.RUNTIME_PROFILE.memory_mb
        self.stdout.write(
            "Ingesting local files from "
            f"{folder} with OCR DPI={settings.OCR_PDF_DPI}, "
            f"OCR timeout={settings.OCR_TIMEOUT_SECONDS}s, "
            f"detected CPUs={settings.RUNTIME_PROFILE.cpu_count}, "
            f"detected memory={memory if memory is not None else 'unknown'} MB."
        )
        self.stdout.write(
            "Large scanned PDF folders can take a while; progress and failures "
            "are printed per file."
        )

        def progress(state, path, index, total, detail):
            if options["no_progress"]:
                return
            completed = index if state in {"done", "error"} else index - 1
            percent = round((completed / total) * 100) if total else 0
            bar = f"{ANSI_GREEN}{progress_bar(completed, total)}{ANSI_RESET}"
            if state == "start":
                self.stdout.write(
                    f"{bar} {percent:3d}% {completed:>4}/{total:<4} "
                    f"ingesting {path.name}"
                )
            elif state == "done":
                self.stdout.write(
                    f"{bar} {percent:3d}% {completed:>4}/{total:<4} "
                    f"done      {path.name}"
                )
            else:
                self.stderr.write(
                    f"{bar} {percent:3d}% {completed:>4}/{total:<4} "
                    f"{ANSI_RED}failed{ANSI_RESET}    {path.name}: {detail}"
                )

        try:
            report = ingest_folder(
                folder,
                collection_name=options["collection"],
                progress_callback=progress,
            )
        except Exception as exc:
            raise CommandError(str(exc)) from exc

        for result in report.results:
            state = "created" if result.created else "updated"
            self.stdout.write(
                f"{state}: {result.document.title} "
                f"({result.chunks_created + result.chunks_updated} chunks)"
            )
        for error in report.errors:
            self.stderr.write(f"error: {error['path']}: {error['error']}")

        if report.errors:
            self.stderr.write("")
            self.stderr.write("Files that failed intake:")
            for error in report.errors:
                self.stderr.write(f"  - {error['path']}: {error['error']}")

        self.stdout.write("")
        self.stdout.write("Demo intake summary:")
        self.stdout.write(f"  folder:             {folder}")
        self.stdout.write(f"  files discovered:   {report.files_discovered}")
        self.stdout.write(f"  files ingested:     {report.files_ingested}")
        self.stdout.write(f"  files skipped:      {report.files_skipped}")
        self.stdout.write(
            "  unsupported types:  "
            f"{format_extension_counts(report.unsupported_file_types) or 'none'}"
        )
        self.stdout.write(f"  empty files:        {report.empty_files}")
        self.stdout.write(f"  extraction failures:{report.extraction_failures}")
        self.stdout.write(
            f"Ingested {report.files_ingested} documents into "
            f"'{options['collection']}' with {report.extraction_failures} errors."
        )
