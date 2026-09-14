"""Bounded, persistent caches for model work; never a source of corpus facts."""

import hashlib
import json
from datetime import timedelta

from django.utils import timezone

from .models import CachedArtifact

CACHE_LIMITS = {
    "generation": 1000,
    "extraction": 10000,
    "planning": 1000,
    "restriction": 5000,
}
CACHE_TTL = {
    "generation": timedelta(days=1),
    "extraction": timedelta(days=30),
    "planning": timedelta(days=1),
    # A restriction verdict is about a value's identity, not the corpus.
    "restriction": timedelta(days=30),
}


def artifact_key(parts: list) -> str:
    return hashlib.sha256(
        json.dumps(parts, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def get_artifact(kind: str, key: str) -> dict | None:
    return (
        CachedArtifact.objects.filter(pk=key, kind=kind, expires_at__gt=timezone.now())
        .values_list("value", flat=True)
        .first()
    )


def put_artifact(kind: str, key: str, value: dict) -> None:
    now = timezone.now()
    CachedArtifact.objects.update_or_create(
        key=key,
        defaults={"kind": kind, "value": value, "expires_at": now + CACHE_TTL[kind]},
    )
    CachedArtifact.objects.filter(kind=kind, expires_at__lte=now).delete()
    # Disk-backed and bounded: no unbounded Python cache on a small Mac.
    obsolete = list(
        CachedArtifact.objects.filter(kind=kind)
        .order_by("-updated_at")
        .values_list("key", flat=True)[CACHE_LIMITS[kind] :]
    )
    if obsolete:
        CachedArtifact.objects.filter(key__in=obsolete).delete()
