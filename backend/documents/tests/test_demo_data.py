import json
from pathlib import Path
from types import SimpleNamespace

from django.core.management import call_command

from documents.management.commands import download_demo_data


def test_demo_questions_json_is_valid():
    path = Path(__file__).resolve().parents[3] / "data" / "demo_questions.json"
    questions = json.loads(path.read_text(encoding="utf-8"))

    assert questions
    assert all("question" in row for row in questions)


def test_downloader_skips_cleanly_when_kagglehub_missing(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(download_demo_data, "import_kagglehub", lambda: None)

    call_command("download_demo_data", "--output-dir", str(tmp_path))

    output = capsys.readouterr().out
    assert "Skipped demo data download: kagglehub is not installed" in output
    assert list(tmp_path.iterdir()) == []


def test_downloader_copies_all_pdf_files_only(tmp_path):
    source = tmp_path / "cache"
    source.mkdir()
    for index in range(12):
        (source / f"receipt-{index}.pdf").write_bytes(f"pdf-{index}".encode())
    (source / "notes.txt").write_text("not copied", encoding="utf-8")
    output = tmp_path / "intake"

    result = download_demo_data.copy_receipt_pdfs(source, output)

    copied = sorted(path.name for path in output.iterdir())
    assert result.source_count == 12
    assert result.copied_count == 12
    assert len(copied) == 12
    assert all(name.endswith(".pdf") for name in copied)
    assert "notes.txt" not in copied


def test_downloader_is_idempotent_and_uses_dataset_download(
    monkeypatch, tmp_path, capsys
):
    source = tmp_path / "cache"
    source.mkdir()
    (source / "receipt.pdf").write_bytes(b"%PDF demo")
    output = tmp_path / "intake"
    calls = []

    fake_kagglehub = SimpleNamespace(
        dataset_download=lambda dataset: calls.append(dataset) or str(source)
    )
    monkeypatch.setattr(download_demo_data, "import_kagglehub", lambda: fake_kagglehub)

    call_command("download_demo_data", "--output-dir", str(output))
    call_command("download_demo_data", "--output-dir", str(output))

    assert calls == ["jenswalter/receipts", "jenswalter/receipts"]
    assert [path.name for path in output.iterdir()] == ["receipt.pdf"]
    output_text = capsys.readouterr().out
    assert "Copied 1 receipt PDFs" in output_text
    assert "0 existing" in output_text
    assert "Copied 0 receipt PDFs" in output_text
    assert "1 existing" in output_text
