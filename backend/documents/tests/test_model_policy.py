"""Cloud-served Ollama models are rejected in configuration and reported."""

import pytest
from config.model_policy import (
    CloudModelConfigured,
    configured_remote_models,
    is_cloud_model_name,
    remote_model_names,
    validate_configured_models,
)

from documents import status as status_module

CLOUD_TAGS = {
    "models": [
        {"name": "qwen3-embedding:0.6b", "size": 639150858},
        {
            "name": "hf.co/unsloth/Qwen3-4B-Instruct-2507-GGUF:Q4_K_M",
            "size": 2497283341,
        },
        {
            "name": "glm-5.1:cloud",
            "remote_model": "glm-5.1",
            "remote_host": "https://ollama.com:443",
            "size": 327,
        },
        {"name": "gpt-oss:120b-cloud", "remote_host": "https://ollama.com:443"},
    ]
}


@pytest.mark.parametrize(
    "name,expected",
    [
        ("glm-5.1:cloud", True),
        ("gpt-oss:120b-cloud", True),
        ("qwen3-embedding:0.6b", False),
        ("hf.co/unsloth/Qwen3-4B-Instruct-2507-GGUF:Q4_K_M", False),
        ("cloudy-model:1b", False),
        ("", False),
    ],
)
def test_cloud_tag_detection(name, expected):
    assert is_cloud_model_name(name) is expected


def test_remote_models_are_listed_from_tags():
    assert remote_model_names(CLOUD_TAGS) == ["glm-5.1:cloud", "gpt-oss:120b-cloud"]


def test_remote_entry_without_cloud_tag_is_still_reported():
    payload = {"models": [{"name": "private:7b", "remote_host": "https://example:443"}]}

    assert remote_model_names(payload) == ["private:7b"]


def test_configured_remote_models_reports_only_offenders():
    configured = {
        "LLM_MODEL": "glm-5.1:cloud",
        "EMBEDDING_MODEL": "qwen3-embedding:0.6b",
    }

    assert configured_remote_models(configured, remote_model_names(CLOUD_TAGS)) == {
        "LLM_MODEL": "glm-5.1:cloud"
    }


def test_validation_rejects_cloud_model_configuration():
    with pytest.raises(CloudModelConfigured) as error:
        validate_configured_models({"LLM_MODEL": "glm-5.1:cloud"})

    assert "LLM_MODEL=glm-5.1:cloud" in str(error.value)


def test_validation_accepts_local_models():
    validate_configured_models(
        {
            "EMBEDDING_MODEL": "qwen3-embedding:0.6b",
            "LLM_MODEL": "hf.co/unsloth/Qwen3-4B-Instruct-2507-GGUF:Q4_K_M",
            "EVAL_JUDGE_MODEL": "",
        }
    )


def test_status_reports_cloud_entries_without_claiming_they_are_used(mocker, settings):
    settings.EMBEDDING_MODEL = "qwen3-embedding:0.6b"
    settings.LLM_MODEL = "hf.co/unsloth/Qwen3-4B-Instruct-2507-GGUF:Q4_K_M"
    settings.EVAL_JUDGE_MODEL = settings.LLM_MODEL
    response = mocker.Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = CLOUD_TAGS
    mocker.patch.object(status_module.requests, "get", return_value=response)

    result = status_module.ollama_status()

    assert result["available"] is True
    assert result["cloud_models"] == ["glm-5.1:cloud", "gpt-oss:120b-cloud"]
    assert result["configured_cloud_models"] == []
    assert result["llm_model_pulled"] is True


def test_status_reports_a_configured_cloud_model(mocker, settings):
    settings.EMBEDDING_MODEL = "qwen3-embedding:0.6b"
    settings.LLM_MODEL = "glm-5.1:cloud"
    settings.EVAL_JUDGE_MODEL = "glm-5.1:cloud"
    response = mocker.Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = CLOUD_TAGS
    mocker.patch.object(status_module.requests, "get", return_value=response)

    result = status_module.ollama_status()

    assert result["configured_cloud_models"] == ["glm-5.1:cloud"]
