"""Service and model availability checks for the local stack."""

from __future__ import annotations

import redis as redis_lib
import requests
from django.conf import settings
from django.db import connection

PROBE_TIMEOUT_SECONDS = 3.0


def database_status() -> dict:
    try:
        connection.ensure_connection()
        return {"available": True}
    except Exception as exc:
        return {"available": False, "error": str(exc)}


def redis_status() -> dict:
    try:
        client = redis_lib.Redis.from_url(
            settings.REDIS_URL,
            socket_connect_timeout=PROBE_TIMEOUT_SECONDS,
            socket_timeout=PROBE_TIMEOUT_SECONDS,
        )
        client.ping()
        return {"available": True}
    except Exception as exc:
        return {"available": False, "error": str(exc)}


def qdrant_status() -> dict:
    try:
        response = requests.get(
            f"{settings.QDRANT_URL.rstrip('/')}/collections",
            timeout=PROBE_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        collections = [
            row.get("name")
            for row in response.json().get("result", {}).get("collections", [])
        ]
        return {
            "available": True,
            "collections": collections,
            "target_collection": settings.QDRANT_COLLECTION,
            "target_collection_exists": settings.QDRANT_COLLECTION in collections,
        }
    except Exception as exc:
        return {"available": False, "error": str(exc)}


def _model_pulled(model: str, pulled_names: list[str]) -> bool:
    """Ollama lists models as name:tag; treat a missing tag as ':latest'."""
    normalized = model if ":" in model else f"{model}:latest"
    return any(
        name == normalized or name.startswith(f"{model}:") for name in pulled_names
    )


def ollama_status() -> dict:
    try:
        response = requests.get(
            f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/tags",
            timeout=PROBE_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        pulled = [row.get("name", "") for row in response.json().get("models", [])]
        return {
            "available": True,
            "embedding_model": settings.EMBEDDING_MODEL,
            "embedding_model_pulled": _model_pulled(settings.EMBEDDING_MODEL, pulled),
            "llm_model": settings.LLM_MODEL,
            "llm_model_pulled": _model_pulled(settings.LLM_MODEL, pulled),
        }
    except Exception as exc:
        return {
            "available": False,
            "embedding_model": settings.EMBEDDING_MODEL,
            "embedding_model_pulled": False,
            "llm_model": settings.LLM_MODEL,
            "llm_model_pulled": False,
            "error": str(exc),
        }


def system_status() -> dict:
    services = {
        "database": database_status(),
        "redis": redis_status(),
        "qdrant": qdrant_status(),
        "ollama": ollama_status(),
    }
    return {
        "status": (
            "ok" if all(s["available"] for s in services.values()) else "degraded"
        ),
        "services": services,
        "features": {
            "vector_indexing": settings.VECTOR_INDEXING_ENABLED,
            "vector_search": settings.VECTOR_SEARCH_ENABLED,
            "answer_generation": settings.ANSWER_GENERATION_ENABLED,
            "async_indexing": settings.ASYNC_INDEXING_ENABLED,
            "ocr": settings.OCR_ENABLED,
        },
        "runtime": {
            **settings.RUNTIME_PROFILE.as_dict(),
            "active": {
                "ingestion_max_workers": settings.INGESTION_MAX_WORKERS,
                "celery_worker_concurrency": settings.CELERY_WORKER_CONCURRENCY,
                "ocr_pdf_dpi": settings.OCR_PDF_DPI,
                "ocr_timeout_seconds": settings.OCR_TIMEOUT_SECONDS,
            },
        },
    }
