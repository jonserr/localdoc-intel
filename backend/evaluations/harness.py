"""Retrieval and answer-quality evaluation harness.

Runs an editable set of demo questions through retrieval, answer generation,
and the local answer judge. Questions may include expected source documents and
expected terms for regression-style metrics, but open-ended demo questions are
also valid.

Metrics:
- hit_rate / recall@k: fraction of labeled questions (those that declare an
  expected_document) whose expected document appears in the top-k retrieved
  chunks.
- mean_reciprocal_rank: 1/rank of the first chunk from the expected document,
  averaged over labeled questions (0 when absent).
- citation_coverage: fraction of a question's expected terms found in the
  retrieved text, averaged over questions with expectations.
- groundedness_score: fraction of questions with expectations where at least
  half of the expected terms are covered (a lexical groundedness proxy).
- answer_quality: local LLM judge score, averaged over judged answers.
- average_latency_ms: mean retrieval latency per question.

Open-ended questions (no expected_document/expected_terms) are still answered
and judged for answer quality, but they are excluded from the retrieval-rank
and coverage denominators instead of counting as automatic misses.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from chat.generation import build_context, generate_answer
from django.conf import settings
from retrieval.services import retrieve_chunks

from evaluations.judging import AnswerJudgeProvider, judge_answer_quality

# Minimum expected-term coverage required by the lexical groundedness proxy.
GROUNDEDNESS_THRESHOLD = 0.5


class EvaluationInputError(ValueError):
    """Raised when an evaluation question set cannot be loaded or validated."""


def default_questions_path() -> Path:
    """Resolve the demo question set inside or outside Docker."""
    candidates = [
        Path("/data/demo_questions.json"),
        Path(__file__).resolve().parents[2] / "data" / "demo_questions.json",
        Path("data/demo_questions.json"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[-1]


@dataclass(frozen=True)
class QuestionResult:
    """Metrics and generated output for one evaluated question."""

    question: str
    expected_document: str
    hit: bool
    reciprocal_rank: float
    term_coverage: float | None
    latency_ms: int
    retrieved_documents: list[str] = field(default_factory=list)
    answer: str = ""
    answer_quality_score: float | None = None
    answer_quality_rationale: str = ""
    answer_judge_error: str = ""
    generation_ms: int = 0
    judge_ms: int = 0


@dataclass(frozen=True)
class EvaluationMetrics:
    """Aggregate metrics and question-level details for an evaluation run."""

    question_count: int
    recall_at_k: float
    mean_reciprocal_rank: float
    citation_coverage: float
    groundedness_score: float
    average_latency_ms: int
    top_k: int
    labeled_question_count: int = 0
    coverage_question_count: int = 0
    answer_quality_score: float = 0.0
    judged_answer_count: int = 0
    answer_judge_model: str = ""
    results: list[QuestionResult] = field(default_factory=list)


def load_questions(path: Path) -> list[dict]:
    """Load and validate a non-empty JSON question set from ``path``."""

    if not path.exists():
        raise EvaluationInputError(f"Questions file not found: {path}")
    try:
        question_rows = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise EvaluationInputError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(question_rows, list) or not question_rows:
        raise EvaluationInputError("Questions file must be a non-empty JSON array.")
    for question_data in question_rows:
        if "question" not in question_data:
            raise EvaluationInputError("Each question needs a 'question' key.")
    return question_rows


def evaluate_question(
    row: dict,
    top_k: int,
    mode: str,
    rerank: bool,
    answer_generator=None,
    answer_judge: AnswerJudgeProvider | None = None,
    retrieval_only: bool = False,
    stage_callback: Callable[[str, dict], None] | None = None,
) -> QuestionResult:
    """Evaluate retrieval and optional answer quality for one question."""

    def report(stage: str, elapsed_ms: int = 0, detail: str = "") -> None:
        if stage_callback:
            stage_callback(stage, {"elapsed_ms": elapsed_ms, "detail": detail})

    started = time.perf_counter()
    retrieved_chunks = retrieve_chunks(
        question=row["question"],
        collection=row.get("collection") or None,
        top_k=top_k,
        mode=mode,
        rerank=rerank,
    )
    latency_ms = int((time.perf_counter() - started) * 1000)
    report("retrieved", latency_ms, f"{len(retrieved_chunks)} chunks")

    expected_document = row.get("expected_document") or ""
    expected_document_key = expected_document.lower()
    retrieved_documents: list[str] = []
    expected_document_rank = 0
    for index, retrieved_chunk in enumerate(retrieved_chunks, start=1):
        document = retrieved_chunk.chunk.document
        document_names = {
            document.title.lower(),
            document.original_filename.lower(),
        }
        retrieved_documents.append(document.title)
        if (
            expected_document_key
            and expected_document_rank == 0
            and expected_document_key in document_names
        ):
            expected_document_rank = index

    expected_terms = [term.lower() for term in row.get("expected_terms", [])]
    if expected_terms:
        retrieved_text = " ".join(item.chunk.text.lower() for item in retrieved_chunks)
        covered_term_count = sum(1 for term in expected_terms if term in retrieved_text)
        term_coverage: float | None = covered_term_count / len(expected_terms)
    elif expected_document_key:
        term_coverage = 1.0 if expected_document_rank else 0.0
    else:
        # Open-ended question: no expectations to score coverage against.
        term_coverage = None

    answer = ""
    answer_quality_score = None
    answer_quality_rationale = ""
    answer_judge_error = ""
    generation_ms = 0
    judge_ms = 0
    if not retrieval_only:
        generation_started = time.perf_counter()
        answer = generate_answer_text(
            question=row["question"],
            retrieved=retrieved_chunks,
            answer_generator=answer_generator,
        )
        generation_ms = int((time.perf_counter() - generation_started) * 1000)
        report("generated", generation_ms, f"{len(answer)} chars")

        judge_started = time.perf_counter()
        judge_result = judge_answer_quality(
            question=row["question"],
            answer=answer,
            context=build_context(retrieved_chunks),
            expected_terms=expected_terms,
            provider=answer_judge,
        )
        judge_ms = int((time.perf_counter() - judge_started) * 1000)
        answer_quality_score = judge_result.score
        answer_quality_rationale = judge_result.rationale
        answer_judge_error = judge_result.error
        report(
            "judged",
            judge_ms,
            (
                f"score {judge_result.score:.2f}"
                if judge_result.score is not None
                else "failed"
            ),
        )

    return QuestionResult(
        question=row["question"],
        expected_document=expected_document,
        hit=expected_document_rank > 0,
        reciprocal_rank=(
            1.0 / expected_document_rank if expected_document_rank else 0.0
        ),
        term_coverage=term_coverage,
        latency_ms=latency_ms,
        retrieved_documents=retrieved_documents,
        answer=answer,
        answer_quality_score=answer_quality_score,
        answer_quality_rationale=answer_quality_rationale,
        answer_judge_error=answer_judge_error,
        generation_ms=generation_ms,
        judge_ms=judge_ms,
    )


def run_evaluation(
    questions: list[dict],
    top_k: int = 5,
    mode: str = "hybrid",
    rerank: bool = True,
    answer_generator=None,
    answer_judge: AnswerJudgeProvider | None = None,
    retrieval_only: bool = False,
    progress_callback: Callable[[str, dict, int, int, object], None] | None = None,
) -> EvaluationMetrics:
    """Run the configured pipeline and aggregate retrieval and answer metrics."""

    question_results: list[QuestionResult] = []
    question_count = len(questions)
    for index, question_data in enumerate(questions, start=1):
        if progress_callback:
            progress_callback("start", question_data, index, question_count, None)

        # Bind the current question and index so stage events retain their context.
        def stage(
            name: str,
            info: dict,
            question_data=question_data,
            index=index,
        ) -> None:
            if progress_callback:
                progress_callback(name, question_data, index, question_count, info)

        result = evaluate_question(
            question_data,
            top_k,
            mode,
            rerank,
            answer_generator=answer_generator,
            answer_judge=answer_judge,
            retrieval_only=retrieval_only,
            stage_callback=stage,
        )
        question_results.append(result)
        if progress_callback:
            progress_callback("done", question_data, index, question_count, result)

    # Metric-specific cohorts keep open-ended or unjudged questions from being
    # counted as retrieval or answer-quality failures.
    labeled_results = [
        result for result in question_results if result.expected_document
    ]
    coverage_results = [
        result for result in question_results if result.term_coverage is not None
    ]
    judged_scores = [
        result.answer_quality_score
        for result in question_results
        if result.answer_quality_score is not None
    ]
    return EvaluationMetrics(
        question_count=question_count,
        recall_at_k=(
            sum(1 for result in labeled_results if result.hit) / len(labeled_results)
            if labeled_results
            else 0.0
        ),
        mean_reciprocal_rank=(
            sum(result.reciprocal_rank for result in labeled_results)
            / len(labeled_results)
            if labeled_results
            else 0.0
        ),
        citation_coverage=(
            sum(result.term_coverage for result in coverage_results)
            / len(coverage_results)
            if coverage_results
            else 0.0
        ),
        groundedness_score=(
            sum(
                1
                for result in coverage_results
                if result.term_coverage >= GROUNDEDNESS_THRESHOLD
            )
            / len(coverage_results)
            if coverage_results
            else 0.0
        ),
        average_latency_ms=int(
            sum(result.latency_ms for result in question_results) / question_count
        ),
        top_k=top_k,
        labeled_question_count=len(labeled_results),
        coverage_question_count=len(coverage_results),
        answer_quality_score=(
            sum(judged_scores) / len(judged_scores) if judged_scores else 0.0
        ),
        judged_answer_count=len(judged_scores),
        answer_judge_model=getattr(answer_judge, "model", settings.EVAL_JUDGE_MODEL),
        results=question_results,
    )


def generate_answer_text(question: str, retrieved: list, answer_generator=None) -> str:
    """Generate answer text using an injected provider or the default generator."""

    if answer_generator is not None:
        generated_result = answer_generator(question, retrieved)
    else:
        generated_result = generate_answer(question, retrieved)
    return str(getattr(generated_result, "answer", generated_result))
