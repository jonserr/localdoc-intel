"""Ingest the redistributable evaluation corpus into its own collection."""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from documents.ingestion import IngestionError, ingest_folder

DEFAULT_COLLECTION = "Eval Corpus"


def default_corpus_path() -> Path:
    candidates = [
        Path("/data/eval_corpus"),
        Path(__file__).resolve().parents[4] / "data" / "eval_corpus",
        Path("data/eval_corpus"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[-1]


class Command(BaseCommand):
    help = "Ingest data/eval_corpus into the reproducible evaluation collection."

    def add_arguments(self, parser):
        parser.add_argument("--folder", default="")
        parser.add_argument("--collection", default=DEFAULT_COLLECTION)

    def handle(self, *args, **options):
        folder = Path(options["folder"]) if options["folder"] else default_corpus_path()
        try:
            report = ingest_folder(folder, collection_name=options["collection"])
        except IngestionError as exc:
            raise CommandError(str(exc)) from exc

        for error in report.errors:
            self.stderr.write(f"error: {error['path']}: {error['error']}")
        self.stdout.write(
            f"Ingested {report.files_ingested} of {report.files_discovered} files "
            f"from {folder} into '{options['collection']}'."
        )
