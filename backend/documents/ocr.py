from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from django.conf import settings


class OCRError(RuntimeError):
    pass


@dataclass(frozen=True)
class OCRPage:
    page: int
    text: str


def ocr_image_bytes(content: bytes, extension: str) -> str:
    if not settings.OCR_ENABLED:
        return ""

    suffix = extension.lower().lstrip(".") or "png"
    with TemporaryDirectory() as temp_dir:
        image_path = Path(temp_dir) / f"source.{suffix}"
        image_path.write_bytes(content)
        return ocr_image_path(image_path)


def ocr_pdf_bytes(content: bytes) -> list[OCRPage]:
    if not settings.OCR_ENABLED:
        return []

    with TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        pdf_path = temp_path / "source.pdf"
        output_prefix = temp_path / "page"
        pdf_path.write_bytes(content)
        _run_command(
            [
                "pdftoppm",
                "-png",
                "-r",
                str(settings.OCR_PDF_DPI),
                str(pdf_path),
                str(output_prefix),
            ],
            tool_name="pdftoppm",
        )
        pages = []
        for image_path in sorted(temp_path.glob("page-*.png"), key=_page_sort_key):
            text = ocr_image_path(image_path)
            pages.append(OCRPage(page=_page_number(image_path), text=text))
        return pages


def ocr_image_path(image_path: Path) -> str:
    completed = _run_command(
        [
            "tesseract",
            str(image_path),
            "stdout",
            "--psm",
            str(settings.OCR_TESSERACT_PSM),
        ],
        tool_name="tesseract",
    )
    return completed.stdout.strip()


def _run_command(command: list[str], tool_name: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=settings.OCR_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        raise OCRError(f"{tool_name} is not installed in the backend image.") from exc
    except subprocess.TimeoutExpired as exc:
        raise OCRError(f"{tool_name} timed out during OCR processing.") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        message = f"{tool_name} failed during OCR processing."
        if detail:
            message = f"{message} {detail}"
        raise OCRError(message) from exc


def _page_sort_key(path: Path) -> int:
    return _page_number(path)


def _page_number(path: Path) -> int:
    match = re.search(r"-(\d+)\.png$", path.name)
    if not match:
        return 0
    return int(match.group(1))
