"""Local answer generation with citations via Ollama.

The generator builds numbered source context from retrieved chunks and asks a
local Ollama chat model to answer with inline ``[n]`` citation markers. When
generation is disabled or the local model is unavailable, it degrades to an
extractive answer built from the top retrieved chunks so the API stays usable
without any model running.
"""

from __future__ import annotations

from dataclasses import dataclass

import requests
from django.conf import settings
from retrieval.services import RetrievedChunk

SYSTEM_INSTRUCTIONS = (
    "You are a document question-answering assistant. Answer the user's "
    "question using ONLY the numbered sources provided. Start your reply with "
    "the direct answer (the specific value, name, or list requested) before "
    "any explanation. Cite every claim with the matching source number in "
    "square brackets, like [1] or [2]. If the sources do not contain the "
    "answer, say so explicitly. Be concise and factual. Do not invent "
    "citations or use outside knowledge."
)

MAX_SOURCE_CHARS = 2000


class GenerationError(RuntimeError):
    pass


@dataclass(frozen=True)
class GenerationResult:
    answer: str
    mode: str  # "generated" | "extractive" | "no_results"
    model: str = ""
    error: str = ""


class OllamaGenerationProvider:
    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
    ):
        self.base_url = (base_url or settings.OLLAMA_BASE_URL).rstrip("/")
        self.model = model or settings.LLM_MODEL
        self.timeout_seconds = timeout_seconds or settings.LLM_TIMEOUT_SECONDS

    def generate(self, question: str, context: str) -> str:
        response = requests.post(
            f"{self.base_url}/api/chat",
            json={
                "model": self.model,
                "stream": False,
                # keep_alive holds the model in memory between calls so
                # consecutive questions skip the (slow) model reload.
                "keep_alive": settings.OLLAMA_KEEP_ALIVE,
                "options": {
                    "temperature": settings.LLM_TEMPERATURE,
                    # Cap the response length; grounded answers with citations
                    # rarely need more, and unbounded generation dominates
                    # per-question latency on CPU-class hardware.
                    "num_predict": settings.LLM_MAX_ANSWER_TOKENS,
                },
                "messages": [
                    {"role": "system", "content": SYSTEM_INSTRUCTIONS},
                    {
                        "role": "user",
                        "content": f"{context}\n\nQuestion: {question}",
                    },
                ],
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        answer = (payload.get("message") or {}).get("content", "").strip()
        if not answer:
            raise GenerationError("Ollama returned an empty answer.")
        return answer


def build_context(retrieved: list[RetrievedChunk]) -> str:
    blocks = ["Sources:"]
    for number, item in enumerate(retrieved, start=1):
        chunk = item.chunk
        location = source_location(chunk)
        text = chunk.text[:MAX_SOURCE_CHARS]
        blocks.append(f"[{number}] {chunk.document.title}{location}\n{text}")
    return "\n\n".join(blocks)


def source_location(chunk) -> str:
    if chunk.page:
        return f" (page {chunk.page})"
    if chunk.start_line and chunk.end_line:
        return f" (lines {chunk.start_line}-{chunk.end_line})"
    return ""


def extractive_answer(retrieved: list[RetrievedChunk]) -> str:
    lines = [
        "Local answer generation is unavailable, so here are the most "
        "relevant passages from your documents:"
    ]
    for number, item in enumerate(retrieved[:3], start=1):
        chunk = item.chunk
        location = source_location(chunk)
        preview = " ".join(chunk.text.split())[:300]
        lines.append(f"[{number}] {chunk.document.title}{location}: {preview}")
    return "\n\n".join(lines)


def generate_answer(
    question: str,
    retrieved: list[RetrievedChunk],
    provider: OllamaGenerationProvider | None = None,
    enabled: bool | None = None,
) -> GenerationResult:
    if not retrieved:
        return GenerationResult(
            answer=(
                "No relevant passages were found in your local documents for "
                "this question. Try rephrasing it, choosing a different "
                "collection, or ingesting more documents."
            ),
            mode="no_results",
        )

    should_generate = settings.ANSWER_GENERATION_ENABLED if enabled is None else enabled
    if not should_generate:
        return GenerationResult(answer=extractive_answer(retrieved), mode="extractive")

    active_provider = provider or OllamaGenerationProvider()
    context = build_context(retrieved)
    try:
        answer = active_provider.generate(question, context)
    except (requests.RequestException, GenerationError, ValueError) as exc:
        return GenerationResult(
            answer=extractive_answer(retrieved),
            mode="extractive",
            model=active_provider.model,
            error=str(exc),
        )
    return GenerationResult(
        answer=answer, mode="generated", model=active_provider.model
    )
