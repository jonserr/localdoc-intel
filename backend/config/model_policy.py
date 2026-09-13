"""Keep model configuration on locally served models.

Ollama can serve models from its own cloud. Locally, those entries carry a
``cloud`` tag, and ``/api/tags`` reports them with a remote host. This module
rejects such names in configuration and identifies them in a tags response.

Configuration rejection is a guard against a typo or a copied model name, not
an enforced sandbox: the host runtime decides whether cloud routing exists at
all. Set OLLAMA_NO_CLOUD=1 there as well.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

CLOUD_TAG = "cloud"
REMOTE_KEYS = ("remote_model", "remote_host")


class CloudModelConfigured(ValueError):
    """Raised when configuration names a model that Ollama serves remotely."""


def is_cloud_model_name(name: str) -> bool:
    """Report whether a model name carries Ollama's cloud tag.

    Ollama names cloud entries ``model:cloud`` or ``model:<size>-cloud``.
    """
    tag = str(name).rsplit(":", 1)[-1] if ":" in str(name) else ""
    return tag == CLOUD_TAG or tag.endswith(f"-{CLOUD_TAG}")


def remote_model_names(tags_payload: Mapping) -> list[str]:
    """Return the names Ollama reports as remotely served."""
    names = []
    for row in tags_payload.get("models") or []:
        if not isinstance(row, Mapping):
            continue
        remote = any(row.get(key) for key in REMOTE_KEYS)
        name = str(row.get("name") or "")
        if name and (remote or is_cloud_model_name(name)):
            names.append(name)
    return sorted(set(names))


def configured_remote_models(
    configured: Mapping[str, str], remote_names: Iterable[str]
) -> dict[str, str]:
    """Return the configured settings whose model Ollama serves remotely."""
    remote = set(remote_names)
    return {
        setting: model
        for setting, model in configured.items()
        if model and (model in remote or is_cloud_model_name(model))
    }


def validate_configured_models(configured: Mapping[str, str]) -> None:
    """Reject configuration that names a cloud-tagged model."""
    offenders = {
        setting: model
        for setting, model in configured.items()
        if model and is_cloud_model_name(model)
    }
    if offenders:
        listed = ", ".join(
            f"{setting}={model}" for setting, model in sorted(offenders.items())
        )
        raise CloudModelConfigured(
            "Ollama cloud models are not supported by this local-first application: "
            f"{listed}. Configure a locally pulled model instead."
        )
