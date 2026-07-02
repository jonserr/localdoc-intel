from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from collections.abc import Callable
from csv import reader
from dataclasses import dataclass, replace
from email import policy
from email.parser import BytesParser
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import transaction
from django.utils import timezone
from pypdf import PdfReader

from .models import Collection, Document, DocumentChunk
from .ocr import OCRError, ocr_image_bytes, ocr_pdf_bytes

TEXT_EXTENSIONS = {"txt", "md", "markdown", "rst", "log", "yaml", "yml"}
TABLE_EXTENSIONS = {"csv", "tsv"}
JSON_EXTENSIONS = {"json", "jsonl"}
MARKUP_EXTENSIONS = {"html", "htm", "xml"}
OFFICE_XML_EXTENSIONS = {"docx", "xlsx", "xlsm", "pptx", "odt", "ods"}
LEGACY_OFFICE_EXTENSIONS = {"doc", "xls", "ppt"}
MAIL_EXTENSIONS = {"eml", "msg"}
RTF_EXTENSIONS = {"rtf"}
CODE_EXTENSIONS = {
    "py",
    "r",
    "sh",
    "js",
    "ts",
    "tsx",
    "jsx",
    "cpp",
    "c",
    "h",
    "hpp",
    "java",
}
PDF_EXTENSIONS = {"pdf"}
IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "tif", "tiff", "bmp", "webp"}
SUPPORTED_EXTENSIONS = (
    TEXT_EXTENSIONS
    | TABLE_EXTENSIONS
    | JSON_EXTENSIONS
    | MARKUP_EXTENSIONS
    | OFFICE_XML_EXTENSIONS
    | LEGACY_OFFICE_EXTENSIONS
    | MAIL_EXTENSIONS
    | RTF_EXTENSIONS
    | CODE_EXTENSIONS
    | PDF_EXTENSIONS
    | IMAGE_EXTENSIONS
)
TEMP_SUFFIXES = {".tmp", ".ocr.tmp", ".rag.tmp", ".swp"}
DEFAULT_CHUNK_SIZE = 1200
DEFAULT_OVERLAP = 150
CPP_CHUNKER_ENV = "LOCALDOC_CHUNKER_PATH"
CPP_CHUNKER_TIMEOUT_SECONDS = 15
LEGACY_OFFICE_TIMEOUT_SECONDS = 45


class IngestionError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedSource:
    title: str
    text: str
    metadata: dict
    page: int | None = None


@dataclass(frozen=True)
class ChunkPayload:
    chunk_index: int
    text: str
    page: int | None
    start_line: int | None
    end_line: int | None
    byte_start: int | None
    byte_end: int | None
    token_count: int


@dataclass(frozen=True)
class IngestionResult:
    document: Document
    created: bool
    chunks_created: int
    chunks_updated: int


@dataclass(frozen=True)
class FolderIngestionReport:
    results: list[IngestionResult]
    errors: list[dict]
    files_discovered: int
    files_ingested: int
    files_skipped: int
    unsupported_file_types: dict[str, int]
    empty_files: int
    extraction_failures: int

    def __iter__(self):
        yield self.results
        yield self.errors


def normalize_extension(filename: str) -> str:
    return Path(filename).suffix.lower().lstrip(".")


def validate_supported_file(filename: str) -> str:
    extension = normalize_extension(filename)
    if extension not in SUPPORTED_EXTENSIONS:
        raise IngestionError(f"Unsupported file type '.{extension}' for {filename}.")
    return extension


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def metadata_for_file(filename: str, content: bytes, source_path: str = "") -> dict:
    extension = validate_supported_file(filename)
    if extension in PDF_EXTENSIONS:
        parser = "pypdf"
    elif extension in IMAGE_EXTENSIONS:
        parser = "tesseract"
    elif extension in TABLE_EXTENSIONS:
        parser = "csv"
    elif extension in JSON_EXTENSIONS:
        parser = "json"
    elif extension in MARKUP_EXTENSIONS:
        parser = "markup"
    elif extension in OFFICE_XML_EXTENSIONS:
        parser = "office-xml"
    elif extension in LEGACY_OFFICE_EXTENSIONS:
        parser = "libreoffice"
    elif extension in MAIL_EXTENSIONS:
        parser = "email"
    elif extension in RTF_EXTENSIONS:
        parser = "rtf"
    else:
        parser = "utf-8"
    return {
        "filename": filename,
        "extension": extension,
        "byte_size": len(content),
        "source_path": source_path,
        "parser": parser,
    }


def parse_document(
    filename: str, content: bytes, source_path: str = ""
) -> list[ParsedSource]:
    extension = validate_supported_file(filename)
    title = Path(filename).name
    base_metadata = metadata_for_file(filename, content, source_path)

    if extension in PDF_EXTENSIONS:
        reader = PdfReader(BytesIO(content))
        parsed_pages = []
        for index, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            if text.strip():
                parsed_pages.append(
                    ParsedSource(
                        title=title,
                        text=text,
                        page=index,
                        metadata={
                            **base_metadata,
                            "page_count": len(reader.pages),
                            "content_type": "pdf",
                        },
                    )
                )
        if not parsed_pages:
            ocr_error = ""
            try:
                ocr_pages = ocr_pdf_bytes(content)
            except OCRError as exc:
                ocr_pages = []
                ocr_error = str(exc)
            parsed_pages = [
                ParsedSource(
                    title=title,
                    text=ocr_page.text,
                    page=ocr_page.page,
                    metadata={
                        **base_metadata,
                        "parser": "pypdf+tesseract",
                        "page_count": len(reader.pages),
                        "content_type": "pdf",
                        "ocr": True,
                    },
                )
                for ocr_page in ocr_pages
                if ocr_page.text.strip()
            ]
        if not parsed_pages:
            metadata = {
                **base_metadata,
                "page_count": len(reader.pages),
                "content_type": "pdf",
                "ocr": False,
            }
            if ocr_error:
                metadata["ocr_error"] = ocr_error
            parsed_pages.append(
                ParsedSource(
                    title=title,
                    text="",
                    page=None,
                    metadata=metadata,
                )
            )
        return parsed_pages

    if extension in IMAGE_EXTENSIONS:
        try:
            text = ocr_image_bytes(content, extension)
        except OCRError as exc:
            raise IngestionError(str(exc)) from exc
        return [
            ParsedSource(
                title=title,
                text=text,
                metadata={
                    **base_metadata,
                    "content_type": "image",
                    "ocr": True,
                },
            )
        ]

    if extension in TABLE_EXTENSIONS:
        return [
            ParsedSource(
                title=title,
                text=table_bytes_to_text(
                    content, delimiter="\t" if extension == "tsv" else ","
                ),
                metadata={**base_metadata, "content_type": "table"},
            )
        ]

    if extension in JSON_EXTENSIONS:
        return [
            ParsedSource(
                title=title,
                text=json_bytes_to_text(content, json_lines=extension == "jsonl"),
                metadata={**base_metadata, "content_type": "json"},
            )
        ]

    if extension in MARKUP_EXTENSIONS:
        return [
            ParsedSource(
                title=title,
                text=markup_bytes_to_text(content, xml=extension == "xml"),
                metadata={**base_metadata, "content_type": "markup"},
            )
        ]

    if extension == "docx":
        return [
            ParsedSource(
                title=title,
                text=docx_bytes_to_text(content),
                metadata={**base_metadata, "content_type": "document"},
            )
        ]

    if extension in {"xlsx", "xlsm"}:
        return [
            ParsedSource(
                title=title,
                text=xlsx_bytes_to_text(content),
                metadata={**base_metadata, "content_type": "workbook"},
            )
        ]

    if extension == "pptx":
        return [
            ParsedSource(
                title=title,
                text=office_zip_text(content, "ppt/slides/slide", "Presentation"),
                metadata={**base_metadata, "content_type": "presentation"},
            )
        ]

    if extension in {"odt", "ods"}:
        return [
            ParsedSource(
                title=title,
                text=office_zip_text(content, "content.xml", "OpenDocument"),
                metadata={**base_metadata, "content_type": "opendocument"},
            )
        ]

    if extension in LEGACY_OFFICE_EXTENSIONS:
        return [
            ParsedSource(
                title=title,
                text=legacy_office_bytes_to_text(filename, content),
                metadata={**base_metadata, "content_type": "legacy-office"},
            )
        ]

    if extension == "eml":
        return [
            ParsedSource(
                title=title,
                text=email_bytes_to_text(content),
                metadata={**base_metadata, "content_type": "email"},
            )
        ]

    if extension == "msg":
        raise IngestionError(
            "Legacy Outlook .msg files require conversion to PDF, EML, or text before ingestion."
        )

    if extension in RTF_EXTENSIONS:
        return [
            ParsedSource(
                title=title,
                text=rtf_bytes_to_text(content),
                metadata={**base_metadata, "content_type": "rtf"},
            )
        ]

    content_type = "code" if extension in CODE_EXTENSIONS else "text"
    return [
        ParsedSource(
            title=title,
            text=content.decode("utf-8", errors="replace"),
            metadata={**base_metadata, "content_type": content_type},
        )
    ]


def sanitize_extracted_text(text: str) -> str:
    return text.replace("\x00", "")


def sanitize_parsed_sources(sources: list[ParsedSource]) -> list[ParsedSource]:
    return [
        replace(source, text=sanitize_extracted_text(source.text)) for source in sources
    ]


def table_bytes_to_text(content: bytes, delimiter: str) -> str:
    decoded = content.decode("utf-8-sig", errors="replace")
    rows = list(reader(decoded.splitlines(), delimiter=delimiter))
    if not rows:
        return ""
    headers = rows[0]
    output = [f"Columns: {', '.join(headers)}"]
    for index, row in enumerate(rows[1:], start=1):
        values = []
        for column, value in zip(headers, row, strict=False):
            if value != "":
                values.append(f"{column}: {value}")
        if len(row) > len(headers):
            values.extend(value for value in row[len(headers) :] if value)
        output.append(f"Row {index}: " + "; ".join(values))
    return "\n".join(output)


def json_bytes_to_text(content: bytes, json_lines: bool) -> str:
    decoded = content.decode("utf-8-sig", errors="replace")
    if json_lines:
        objects = []
        for line_number, line in enumerate(decoded.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                objects.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise IngestionError(
                    f"Invalid JSONL on line {line_number}: {exc}"
                ) from exc
    else:
        try:
            objects = json.loads(decoded)
        except json.JSONDecodeError as exc:
            raise IngestionError(f"Invalid JSON: {exc}") from exc
    return "\n".join(flatten_json(objects))


def flatten_json(value, prefix: str = "") -> list[str]:
    if isinstance(value, dict):
        lines = []
        for key, nested in value.items():
            nested_prefix = f"{prefix}.{key}" if prefix else str(key)
            lines.extend(flatten_json(nested, nested_prefix))
        return lines
    if isinstance(value, list):
        lines = []
        for index, nested in enumerate(value, start=1):
            nested_prefix = f"{prefix}[{index}]" if prefix else f"item[{index}]"
            lines.extend(flatten_json(nested, nested_prefix))
        return lines
    if value is None:
        return []
    return [f"{prefix}: {value}" if prefix else str(value)]


class ReadableHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data):
        cleaned = " ".join(data.split())
        if cleaned:
            self.parts.append(cleaned)


def markup_bytes_to_text(content: bytes, xml: bool) -> str:
    decoded = content.decode("utf-8-sig", errors="replace")
    if xml:
        try:
            root = ElementTree.fromstring(decoded)
        except ElementTree.ParseError:
            return strip_markup(decoded)
        return "\n".join(text.strip() for text in root.itertext() if text.strip())
    parser = ReadableHTMLParser()
    parser.feed(decoded)
    return "\n".join(parser.parts)


def strip_markup(text: str) -> str:
    return "\n".join(
        part.strip()
        for part in re.sub(r"<[^>]+>", "\n", text).splitlines()
        if part.strip()
    )


def docx_bytes_to_text(content: bytes) -> str:
    lines = []
    with zipfile.ZipFile(BytesIO(content)) as archive:
        for name in sorted(archive.namelist()):
            if not name.startswith("word/") or not name.endswith(".xml"):
                continue
            if not any(part in name for part in ("document", "header", "footer")):
                continue
            lines.extend(xml_text_fragments(archive.read(name)))
    return "\n".join(lines)


def xlsx_bytes_to_text(content: bytes) -> str:
    with zipfile.ZipFile(BytesIO(content)) as archive:
        shared_strings = read_shared_strings(archive)
        sheet_names = read_sheet_names(archive)
        lines = []
        sheet_paths = sorted(
            name
            for name in archive.namelist()
            if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")
        )
        for index, sheet_path in enumerate(sheet_paths, start=1):
            sheet_name = sheet_names.get(index, f"Sheet {index}")
            lines.append(f"Sheet: {sheet_name}")
            lines.extend(xlsx_sheet_rows(archive.read(sheet_path), shared_strings))
    return "\n".join(lines)


def read_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
    return [
        " ".join(text.strip() for text in item.itertext() if text.strip())
        for item in root
    ]


def read_sheet_names(archive: zipfile.ZipFile) -> dict[int, str]:
    if "xl/workbook.xml" not in archive.namelist():
        return {}
    root = ElementTree.fromstring(archive.read("xl/workbook.xml"))
    sheets = {}
    for sheet in root.iter():
        if sheet.tag.endswith("sheet"):
            name = sheet.attrib.get("name")
            if name:
                sheets[len(sheets) + 1] = name
    return sheets


def xlsx_sheet_rows(sheet_xml: bytes, shared_strings: list[str]) -> list[str]:
    root = ElementTree.fromstring(sheet_xml)
    lines = []
    for row_index, row in enumerate(root.iter(), start=1):
        if not row.tag.endswith("row"):
            continue
        values = []
        for cell in row:
            if not cell.tag.endswith("c"):
                continue
            values.append(read_xlsx_cell(cell, shared_strings))
        values = [value for value in values if value]
        if values:
            lines.append(
                f"Row {row.attrib.get('r') or row_index}: " + " | ".join(values)
            )
    return lines


def read_xlsx_cell(cell, shared_strings: list[str]) -> str:
    value = ""
    for child in cell:
        if child.tag.endswith("v") and child.text is not None:
            value = child.text
            break
        if child.tag.endswith("is"):
            value = " ".join(text.strip() for text in child.itertext() if text.strip())
            break
    if cell.attrib.get("t") == "s" and value.isdigit():
        index = int(value)
        if 0 <= index < len(shared_strings):
            return shared_strings[index]
    return value


def office_zip_text(content: bytes, name_prefix: str, label: str) -> str:
    with zipfile.ZipFile(BytesIO(content)) as archive:
        lines = []
        for name in sorted(archive.namelist()):
            if name_prefix not in name or not name.endswith(".xml"):
                continue
            parts = xml_text_fragments(archive.read(name))
            if parts:
                lines.append(f"{label} part: {Path(name).name}")
                lines.extend(parts)
        return "\n".join(lines)


def xml_text_fragments(content: bytes) -> list[str]:
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError:
        return strip_markup(content.decode("utf-8", errors="replace")).splitlines()
    return [text.strip() for text in root.itertext() if text.strip()]


def legacy_office_bytes_to_text(filename: str, content: bytes) -> str:
    libreoffice = shutil.which("libreoffice") or shutil.which("soffice")
    if not libreoffice:
        raise IngestionError(
            f"Legacy Office file '{filename}' requires LibreOffice; convert it to PDF, DOCX, XLSX, or PPTX, or install LibreOffice."
        )
    extension = normalize_extension(filename)
    with tempfile.TemporaryDirectory(prefix="localdoc-office-") as temp_dir:
        input_path = Path(temp_dir) / filename
        input_path.write_bytes(content)
        try:
            subprocess.run(
                [
                    libreoffice,
                    "--headless",
                    "--convert-to",
                    "txt",
                    "--outdir",
                    temp_dir,
                    str(input_path),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=LEGACY_OFFICE_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise IngestionError(
                f"LibreOffice could not convert legacy .{extension} file '{filename}'."
            ) from exc
        output_path = input_path.with_suffix(".txt")
        if not output_path.exists():
            raise IngestionError(
                f"LibreOffice conversion did not produce text for '{filename}'."
            )
        return output_path.read_text(encoding="utf-8", errors="replace")


def email_bytes_to_text(content: bytes) -> str:
    message = BytesParser(policy=policy.default).parsebytes(content)
    lines = []
    for header in ("from", "to", "subject", "date"):
        value = message.get(header)
        if value:
            lines.append(f"{header.title()}: {value}")
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_type() == "text/plain":
                lines.append(part.get_content())
    elif message.get_content_type() == "text/plain":
        lines.append(message.get_content())
    return "\n".join(str(line).strip() for line in lines if str(line).strip())


def rtf_bytes_to_text(content: bytes) -> str:
    text = content.decode("utf-8", errors="replace")
    text = re.sub(r"\\'[0-9a-fA-F]{2}", " ", text)
    text = re.sub(r"\\[a-zA-Z]+-?\d* ?", " ", text)
    text = text.replace("{", " ").replace("}", " ")
    return " ".join(text.split())


def chunk_parsed_sources(
    parsed_sources: list[ParsedSource],
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
    source_file_path: Path | None = None,
) -> tuple[list[ChunkPayload], str]:
    chunks: list[ChunkPayload] = []
    chunker = "python"
    for source in parsed_sources:
        cpp_chunks = None
        if source.page is None and source_file_path:
            cpp_chunks = run_cpp_chunker(
                source_file_path,
                start_index=len(chunks),
                chunk_size=chunk_size,
                overlap=overlap,
            )
        if cpp_chunks is not None:
            chunks.extend(cpp_chunks)
            chunker = "cpp"
            continue

        chunks.extend(
            _chunk_text(
                source.text,
                page=source.page,
                start_index=len(chunks),
                chunk_size=chunk_size,
                overlap=overlap,
                include_byte_offsets=source.page is None,
            )
        )
    return chunks, chunker


def find_cpp_chunker() -> Path | None:
    executable_name = "localdoc_chunker.exe" if os.name == "nt" else "localdoc_chunker"
    configured_path = os.environ.get(CPP_CHUNKER_ENV)
    repo_root = Path(__file__).resolve().parents[2]
    candidates = [
        Path(configured_path) if configured_path else None,
        repo_root / "cpp" / "chunker" / "build" / executable_name,
        Path("/cpp") / "chunker" / "build" / executable_name,
    ]
    for candidate in candidates:
        if candidate and candidate.exists() and os.access(candidate, os.X_OK):
            return candidate
    return None


def run_cpp_chunker(
    input_path: Path,
    start_index: int,
    chunk_size: int,
    overlap: int,
) -> list[ChunkPayload] | None:
    binary = find_cpp_chunker()
    if binary is None or not input_path.exists():
        return None

    try:
        completed = subprocess.run(
            [
                str(binary),
                "--input",
                str(input_path),
                "--chunk-size",
                str(chunk_size),
                "--overlap",
                str(overlap),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=CPP_CHUNKER_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    chunks = []
    try:
        for raw_line in completed.stdout.splitlines():
            if not raw_line.strip():
                continue
            row = json.loads(raw_line)
            text = row.get("text", "")
            chunks.append(
                ChunkPayload(
                    chunk_index=start_index + int(row["chunk_index"]),
                    text=text,
                    page=None,
                    start_line=_nullable_positive_int(row.get("start_line")),
                    end_line=_nullable_positive_int(row.get("end_line")),
                    byte_start=_nullable_non_negative_int(row.get("byte_start")),
                    byte_end=_nullable_non_negative_int(row.get("byte_end")),
                    token_count=len(text.split()),
                )
            )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None
    return chunks or None


def _nullable_positive_int(value) -> int | None:
    parsed = int(value)
    return parsed if parsed > 0 else None


def _nullable_non_negative_int(value) -> int | None:
    parsed = int(value)
    return parsed if parsed >= 0 else None


def _chunk_text(
    text: str,
    page: int | None,
    start_index: int,
    chunk_size: int,
    overlap: int,
    include_byte_offsets: bool,
) -> list[ChunkPayload]:
    if chunk_size <= 0:
        raise IngestionError("chunk_size must be greater than zero.")
    if overlap >= chunk_size:
        raise IngestionError("overlap must be smaller than chunk_size.")

    lines = _line_records(text)
    if not lines:
        return [
            ChunkPayload(
                chunk_index=start_index,
                text="",
                page=page,
                start_line=None,
                end_line=None,
                byte_start=0 if include_byte_offsets else None,
                byte_end=0 if include_byte_offsets else None,
                token_count=0,
            )
        ]

    chunks = []
    line_index = 0
    chunk_index = start_index
    while line_index < len(lines):
        chunk_lines = []
        byte_count = 0
        current = line_index

        while current < len(lines):
            line_text = lines[current]["text"]
            line_bytes = len(line_text.encode("utf-8"))
            separator_bytes = 1 if chunk_lines else 0
            would_exceed = byte_count + separator_bytes + line_bytes > chunk_size
            if would_exceed and chunk_lines:
                break
            chunk_lines.append(lines[current])
            byte_count += separator_bytes + line_bytes
            current += 1

        chunk_text = "\n".join(line["text"] for line in chunk_lines)
        first = chunk_lines[0]
        last = chunk_lines[-1]
        chunks.append(
            ChunkPayload(
                chunk_index=chunk_index,
                text=chunk_text,
                page=page,
                start_line=first["line_number"],
                end_line=last["line_number"],
                byte_start=first["byte_start"] if include_byte_offsets else None,
                byte_end=last["byte_end"] if include_byte_offsets else None,
                token_count=len(chunk_text.split()),
            )
        )
        chunk_index += 1

        if current >= len(lines):
            break

        overlap_bytes = 0
        next_index = current
        while next_index > line_index and overlap_bytes < overlap:
            next_index -= 1
            overlap_bytes += len(lines[next_index]["text"].encode("utf-8")) + 1
        line_index = max(next_index, line_index + 1)

    return chunks


def _line_records(text: str) -> list[dict]:
    records = []
    byte_offset = 0
    split_lines = text.splitlines()
    for index, line in enumerate(split_lines, start=1):
        encoded_length = len(line.encode("utf-8"))
        start = byte_offset
        end = start + encoded_length
        records.append(
            {
                "line_number": index,
                "text": line,
                "byte_start": start,
                "byte_end": end,
            }
        )
        byte_offset = end + 1
    return records


def save_source_file(filename: str, content: bytes, digest: str) -> str:
    extension = normalize_extension(filename)
    storage_name = f"documents/{digest}.{extension}"
    if not default_storage.exists(storage_name):
        default_storage.save(storage_name, ContentFile(content))
    return storage_name


def storage_file_path(storage_name: str) -> Path | None:
    try:
        path = default_storage.path(storage_name)
    except (AttributeError, NotImplementedError):
        return None
    return Path(path)


@transaction.atomic
def ingest_bytes(
    *,
    filename: str,
    content: bytes,
    collection_name: str,
    source_path: str = "",
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
) -> IngestionResult:
    extension = validate_supported_file(filename)
    digest = sha256_bytes(content)
    collection, _ = Collection.objects.get_or_create(name=collection_name or "Default")
    stored_path = save_source_file(filename, content, digest)
    parsed_sources = parse_document(
        filename, content, source_path=source_path or stored_path
    )
    parsed_sources = sanitize_parsed_sources(parsed_sources)
    source_file_path = (
        Path(source_path)
        if source_path and Path(source_path).exists()
        else storage_file_path(stored_path)
    )
    chunks, chunker = chunk_parsed_sources(
        parsed_sources,
        chunk_size=chunk_size,
        overlap=overlap,
        source_file_path=(
            source_file_path
            if extension not in PDF_EXTENSIONS | IMAGE_EXTENSIONS
            else None
        ),
    )
    metadata = (
        parsed_sources[0].metadata
        if parsed_sources
        else metadata_for_file(filename, content, source_path)
    )
    metadata = {
        **metadata,
        "stored_path": stored_path,
        "chunk_size": chunk_size,
        "overlap": overlap,
        "chunk_count": len(chunks),
        "chunker": chunker,
    }

    document, created = Document.objects.update_or_create(
        collection=collection,
        sha256=digest,
        defaults={
            "title": Path(filename).name,
            "original_filename": filename,
            "file_type": extension,
            "source_path": source_path or stored_path,
            "metadata": metadata,
            "status": Document.Status.INDEXED,
            "error_message": "",
            "chunk_count": len(chunks),
            "byte_size": len(content),
            "last_indexed_at": timezone.now(),
        },
    )

    chunks_created = 0
    chunks_updated = 0
    seen_indexes = []
    for chunk in chunks:
        _, chunk_created = DocumentChunk.objects.update_or_create(
            document=document,
            chunk_index=chunk.chunk_index,
            defaults={
                "text": sanitize_extracted_text(chunk.text),
                "page": chunk.page,
                "start_line": chunk.start_line,
                "end_line": chunk.end_line,
                "byte_start": chunk.byte_start,
                "byte_end": chunk.byte_end,
                "token_count": chunk.token_count,
            },
        )
        seen_indexes.append(chunk.chunk_index)
        if chunk_created:
            chunks_created += 1
        else:
            chunks_updated += 1

    document.chunks.exclude(chunk_index__in=seen_indexes).delete()
    _schedule_indexing(document)

    return IngestionResult(
        document=document,
        created=created,
        chunks_created=chunks_created,
        chunks_updated=chunks_updated,
    )


def apply_indexing_result(document: Document, indexing_result) -> None:
    """Record vector indexing outcome on the document's metadata."""
    if not indexing_result.enabled:
        return
    metadata = {
        **document.metadata,
        "vector_indexed": indexing_result.indexed,
        "vector_index_error": indexing_result.error,
    }
    Document.objects.filter(id=document.id).update(metadata=metadata)
    document.metadata = metadata


def _schedule_indexing(document: Document) -> None:
    """Index vectors via Celery when enabled, falling back to inline indexing."""
    from retrieval.services import index_document_chunks

    if not settings.VECTOR_INDEXING_ENABLED:
        return

    if settings.ASYNC_INDEXING_ENABLED:
        from .tasks import index_document_chunks_task

        def dispatch() -> None:
            try:
                index_document_chunks_task.delay(document.id)
            except Exception:
                # Broker unavailable: fall back to inline indexing.
                apply_indexing_result(document, index_document_chunks(document.id))

        metadata = {**document.metadata, "vector_indexing": "queued"}
        Document.objects.filter(id=document.id).update(metadata=metadata)
        document.metadata = metadata
        transaction.on_commit(dispatch)
        return

    apply_indexing_result(document, index_document_chunks(document.id))


def ingest_path(
    path: Path,
    collection_name: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
) -> IngestionResult:
    if not path.exists() or not path.is_file():
        raise IngestionError(f"File does not exist: {path}")
    return ingest_bytes(
        filename=path.name,
        content=path.read_bytes(),
        collection_name=collection_name,
        source_path=str(path),
        chunk_size=chunk_size,
        overlap=overlap,
    )


def ingest_folder(
    folder: Path,
    collection_name: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
    progress_callback: Callable[[str, Path, int, int, str], None] | None = None,
) -> FolderIngestionReport:
    if not folder.exists() or not folder.is_dir():
        raise IngestionError(f"Folder does not exist: {folder}")

    results = []
    errors = []
    supported_paths = []
    unsupported_file_types: dict[str, int] = {}
    empty_files = 0
    files_discovered = 0

    for path in sorted(folder.rglob("*")):
        if not should_consider_path(path):
            continue
        files_discovered += 1
        if path.stat().st_size == 0:
            empty_files += 1
            continue
        extension = normalize_extension(path.name)
        if extension not in SUPPORTED_EXTENSIONS:
            key = f".{extension}" if extension else "(none)"
            unsupported_file_types[key] = unsupported_file_types.get(key, 0) + 1
            continue
        supported_paths.append(path)

    if files_discovered == 0:
        raise IngestionError(
            f"No intake files found in {folder}. Add files or run make demo-data."
        )
    if not supported_paths:
        raise IngestionError(
            f"No supported files found in {folder}. Unsupported types: "
            f"{format_extension_counts(unsupported_file_types) or 'none'}."
        )

    total_supported = len(supported_paths)
    for index, path in enumerate(supported_paths, start=1):
        try:
            if progress_callback:
                progress_callback("start", path, index, total_supported, "")
            results.append(
                ingest_path(
                    path,
                    collection_name=collection_name,
                    chunk_size=chunk_size,
                    overlap=overlap,
                )
            )
            if progress_callback:
                progress_callback("done", path, index, total_supported, "")
        except Exception as exc:
            errors.append({"path": str(path), "error": str(exc)})
            if progress_callback:
                progress_callback("error", path, index, total_supported, str(exc))

    files_skipped = empty_files + sum(unsupported_file_types.values()) + len(errors)
    return FolderIngestionReport(
        results=results,
        errors=errors,
        files_discovered=files_discovered,
        files_ingested=len(results),
        files_skipped=files_skipped,
        unsupported_file_types=unsupported_file_types,
        empty_files=empty_files,
        extraction_failures=len(errors),
    )


def should_consider_path(path: Path) -> bool:
    if not path.is_file():
        return False
    if any(part.startswith(".") for part in path.parts):
        return False
    name = path.name
    if name.startswith("~$"):
        return False
    lowered = name.lower()
    return not any(lowered.endswith(suffix) for suffix in TEMP_SUFFIXES)


def format_extension_counts(counts: dict[str, int]) -> str:
    return ", ".join(
        f"{extension} ({count})" for extension, count in sorted(counts.items())
    )
