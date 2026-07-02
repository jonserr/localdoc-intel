"""Shared pytest configuration for the backend test suite.

Tests must be hermetic: they may not depend on live Qdrant, Ollama, Redis, or
a Celery worker, regardless of what a developer's .env or the Docker
environment enables. Individual tests opt back in with @override_settings or
by injecting fake providers.
"""

import pytest


@pytest.fixture(autouse=True)
def _hermetic_local_ai_flags(settings):
    settings.VECTOR_SEARCH_ENABLED = False
    settings.VECTOR_INDEXING_ENABLED = False
    settings.ANSWER_GENERATION_ENABLED = False
    settings.ASYNC_INDEXING_ENABLED = False
