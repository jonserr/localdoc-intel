from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path

_UNLIMITED_CGROUP_MEMORY = 1 << 60


@dataclass(frozen=True)
class RuntimeProfile:
    cpu_count: int
    memory_mb: int | None
    ingest_max_workers: int
    celery_concurrency: int
    ocr_pdf_dpi: int
    ocr_timeout_seconds: float

    def as_dict(self) -> dict:
        return asdict(self)


def runtime_profile() -> RuntimeProfile:
    cpu_count = detected_cpu_count()
    memory_mb = detected_memory_mb()
    return RuntimeProfile(
        cpu_count=cpu_count,
        memory_mb=memory_mb,
        ingest_max_workers=recommended_worker_count(cpu_count),
        celery_concurrency=recommended_worker_count(cpu_count),
        ocr_pdf_dpi=recommended_ocr_pdf_dpi(memory_mb),
        ocr_timeout_seconds=recommended_ocr_timeout_seconds(cpu_count, memory_mb),
    )


def detected_cpu_count() -> int:
    try:
        return max(1, len(os.sched_getaffinity(0)))
    except AttributeError:
        return max(1, os.cpu_count() or 1)


def detected_memory_mb() -> int | None:
    cgroup_limit = _read_cgroup_memory_limit()
    if cgroup_limit:
        return cgroup_limit // (1024 * 1024)

    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
    except (AttributeError, OSError, ValueError):
        return None
    if pages <= 0 or page_size <= 0:
        return None
    return int(pages * page_size // (1024 * 1024))


def recommended_worker_count(cpu_count: int) -> int:
    return max(1, min(4, cpu_count - 1 if cpu_count > 1 else 1))


def recommended_ocr_pdf_dpi(memory_mb: int | None) -> int:
    if memory_mb is None:
        return 200
    if memory_mb < 2048:
        return 150
    if memory_mb < 4096:
        return 175
    return 200


def recommended_ocr_timeout_seconds(cpu_count: int, memory_mb: int | None) -> float:
    if cpu_count <= 2 or (memory_mb is not None and memory_mb < 2048):
        return 45.0
    return 30.0


def _read_cgroup_memory_limit() -> int | None:
    candidates = [
        Path("/sys/fs/cgroup/memory.max"),
        Path("/sys/fs/cgroup/memory/memory.limit_in_bytes"),
    ]
    for path in candidates:
        try:
            raw_value = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if raw_value == "max":
            continue
        try:
            value = int(raw_value)
        except ValueError:
            continue
        if 0 < value < _UNLIMITED_CGROUP_MEMORY:
            return value
    return None
