from datetime import timedelta

import pytest
from config.resources import recommended_review_context
from django.utils import timezone

from chat.cache import artifact_key, get_artifact, put_artifact
from chat.models import CachedArtifact


@pytest.mark.django_db
def test_cache_is_persistent_bounded_and_expires(mocker):
    mocker.patch("chat.cache.CACHE_LIMITS", {"generation": 2})
    for i in range(3):
        put_artifact("generation", artifact_key([i]), {"answer": str(i)})
    assert CachedArtifact.objects.count() == 2
    assert get_artifact("generation", artifact_key([0])) is None
    key = artifact_key([2])
    assert get_artifact("generation", key) == {"answer": "2"}
    CachedArtifact.objects.filter(pk=key).update(
        expires_at=timezone.now() - timedelta(seconds=1)
    )
    assert get_artifact("generation", key) is None


def test_memory_budgets_are_conservative():
    assert recommended_review_context(2048) == 4096
    assert recommended_review_context(8192) == 8192
    assert recommended_review_context(None) == 8192
    assert recommended_review_context(65536) == 8192
