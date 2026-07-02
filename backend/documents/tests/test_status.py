import pytest
from django.urls import reverse

from documents import status as status_module


@pytest.fixture
def healthy_services(mocker):
    mocker.patch.object(
        status_module,
        "database_status",
        return_value={"available": True},
    )
    redis_client = mocker.Mock()
    redis_client.ping.return_value = True
    mocker.patch.object(
        status_module.redis_lib.Redis, "from_url", return_value=redis_client
    )

    def fake_get(url, timeout):
        response = mocker.Mock()
        response.raise_for_status.return_value = None
        if "/collections" in url:
            response.json.return_value = {
                "result": {"collections": [{"name": "localdoc_chunks"}]}
            }
        else:
            response.json.return_value = {
                "models": [
                    {"name": "qwen3-embedding:0.6b"},
                    {"name": "hf.co/unsloth/Qwen3-4B-Instruct-2507-GGUF:Q4_K_M"},
                ]
            }
        return response

    mocker.patch.object(status_module.requests, "get", side_effect=fake_get)


def test_system_status_ok(healthy_services, settings):
    settings.QDRANT_COLLECTION = "localdoc_chunks"
    settings.EMBEDDING_MODEL = "qwen3-embedding:0.6b"
    settings.LLM_MODEL = "hf.co/unsloth/Qwen3-4B-Instruct-2507-GGUF:Q4_K_M"

    result = status_module.system_status()

    assert result["status"] == "ok"
    assert result["services"]["qdrant"]["target_collection_exists"] is True
    assert result["services"]["ollama"]["embedding_model_pulled"] is True
    assert result["services"]["ollama"]["llm_model_pulled"] is True
    assert result["runtime"]["cpu_count"] >= 1
    assert result["runtime"]["active"]["ocr_pdf_dpi"] > 0


def test_system_status_degraded_when_ollama_down(healthy_services, mocker):
    mocker.patch.object(
        status_module,
        "ollama_status",
        return_value={"available": False, "error": "connection refused"},
    )

    result = status_module.system_status()

    assert result["status"] == "degraded"
    assert result["services"]["ollama"]["available"] is False


def test_model_pulled_handles_default_latest_tag():
    assert status_module._model_pulled("llama3.1", ["llama3.1:latest"]) is True
    assert status_module._model_pulled("llama3.1:8b", ["llama3.1:latest"]) is False
    assert (
        status_module._model_pulled("qwen3-embedding:0.6b", ["qwen3-embedding:0.6b"])
        is True
    )


@pytest.mark.django_db
def test_status_endpoint_returns_services(client, healthy_services):
    response = client.get(reverse("status"))

    assert response.status_code == 200
    payload = response.json()
    assert set(payload["services"]) == {"database", "redis", "qdrant", "ollama"}
    assert "features" in payload
    assert "runtime" in payload
