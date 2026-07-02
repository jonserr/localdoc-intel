from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Protocol

import requests
from django.conf import settings


class AnswerJudgeError(RuntimeError):
    pass


@dataclass(frozen=True)
class AnswerQualityResult:
    score: float | None
    rationale: str = ""
    error: str = ""


class AnswerJudgeProvider(Protocol):
    model: str

    def judge(
        self,
        question: str,
        answer: str,
        context: str,
        expected_terms: list[str],
    ): ...


JUDGE_SYSTEM_INSTRUCTIONS = (
    "You are evaluating a local document question-answering system. Score the "
    "answer from 0.0 to 1.0 for correctness, completeness, citation use, and "
    "grounding in the supplied evidence. Penalize unsupported claims. Return "
    "only JSON with keys score and rationale. Keep the rationale under 25 "
    "words so the JSON stays short."
)


class OllamaAnswerJudgeProvider:
    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
    ):
        self.base_url = (base_url or settings.OLLAMA_BASE_URL).rstrip("/")
        self.model = model or settings.EVAL_JUDGE_MODEL
        self.timeout_seconds = timeout_seconds or settings.LLM_TIMEOUT_SECONDS

    def judge(
        self,
        question: str,
        answer: str,
        context: str,
        expected_terms: list[str],
    ) -> AnswerQualityResult:
        response = requests.post(
            f"{self.base_url}/api/chat",
            json={
                "model": self.model,
                "stream": False,
                "keep_alive": settings.OLLAMA_KEEP_ALIVE,
                "options": {
                    "temperature": 0,
                    # The judge only returns a small JSON verdict; capping the
                    # response keeps each judgement fast on local hardware.
                    "num_predict": settings.EVAL_JUDGE_MAX_TOKENS,
                },
                "messages": [
                    {"role": "system", "content": JUDGE_SYSTEM_INSTRUCTIONS},
                    {
                        "role": "user",
                        "content": build_judge_request(
                            question=question,
                            answer=answer,
                            context=context,
                            expected_terms=expected_terms,
                        ),
                    },
                ],
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        content = (response.json().get("message") or {}).get("content", "")
        return normalize_answer_quality_result(parse_judge_json(content))


def build_judge_request(
    *,
    question: str,
    answer: str,
    context: str,
    expected_terms: list[str],
) -> str:
    terms = ", ".join(expected_terms) if expected_terms else "none supplied"
    # Truncate the evidence so judge prompt processing stays fast; the verdict
    # depends far more on the answer/question than on the full source text.
    max_chars = settings.EVAL_JUDGE_MAX_CONTEXT_CHARS
    if max_chars > 0 and len(context) > max_chars:
        context = context[:max_chars] + "\n[evidence truncated]"
    return (
        f"Question:\n{question}\n\n"
        f"Answer:\n{answer}\n\n"
        f"Expected key terms:\n{terms}\n\n"
        f"Retrieved evidence:\n{context}\n\n"
        "Return JSON only, for example: "
        '{"score": 0.75, "rationale": "Brief reason."}'
    )


def judge_answer_quality(
    *,
    question: str,
    answer: str,
    context: str,
    expected_terms: list[str],
    provider: AnswerJudgeProvider | None = None,
) -> AnswerQualityResult:
    active_provider = provider or OllamaAnswerJudgeProvider()
    try:
        raw_result = active_provider.judge(
            question=question,
            answer=answer,
            context=context,
            expected_terms=expected_terms,
        )
    except (requests.RequestException, AnswerJudgeError, ValueError, TypeError) as exc:
        return AnswerQualityResult(score=None, error=str(exc))
    return normalize_answer_quality_result(raw_result)


def normalize_answer_quality_result(raw_result) -> AnswerQualityResult:
    if isinstance(raw_result, AnswerQualityResult):
        return raw_result
    if not isinstance(raw_result, dict):
        raise AnswerJudgeError("Answer judge returned an unsupported result.")

    try:
        score = float(raw_result["score"])
    except (KeyError, TypeError, ValueError) as exc:
        raise AnswerJudgeError(
            "Answer judge result must include a numeric score."
        ) from exc
    score = max(0.0, min(1.0, score))
    rationale = str(raw_result.get("rationale", ""))
    return AnswerQualityResult(score=score, rationale=rationale)


def parse_judge_json(content: str) -> dict:
    cleaned = strip_json_fence(content.strip())
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        # Local models sometimes wrap the JSON in prose or hit the response
        # token cap mid-rationale. Salvage the verdict rather than failing:
        # first try the outermost {...} block, then a bare "score": <n> match.
        block = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if block:
            try:
                payload = json.loads(block.group(0))
            except json.JSONDecodeError:
                payload = None
        else:
            payload = None
        if payload is None:
            score_match = re.search(r'"score"\s*:\s*([0-9]*\.?[0-9]+)', cleaned)
            if score_match:
                payload = {
                    "score": float(score_match.group(1)),
                    "rationale": "(rationale unavailable: truncated judge output)",
                }
            else:
                raise AnswerJudgeError("Answer judge returned invalid JSON.") from exc
    if not isinstance(payload, dict):
        raise AnswerJudgeError("Answer judge JSON must be an object.")
    return payload


def strip_json_fence(content: str) -> str:
    match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", content, flags=re.DOTALL)
    if match:
        return match.group(1).strip()
    return content
