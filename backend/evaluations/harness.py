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


class EvaluationInputError(ValueError):
    pass


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
    if not path.exists():
        raise EvaluationInputError(f"Questions file not found: {path}")
    try:
        questions = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise EvaluationInputError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(questions, list) or not questions:
        raise EvaluationInputError("Questions file must be a non-empty JSON array.")
    for row in questions:
        if "question" not in row:
            raise EvaluationInputError("Each question needs a 'question' key.")
    return questions


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
    def report(stage: str, elapsed_ms: int = 0, detail: str = "") -> None:
        if stage_callback:
            stage_callback(stage, {"elapsed_ms": elapsed_ms, "detail": detail})

    started = time.perf_counter()
    retrieved = retrieve_chunks(
        question=row["question"],
        collection=row.get("collection") or None,
        top_k=top_k,
        mode=mode,
        rerank=rerank,
    )
    latency_ms = int((time.perf_counter() - started) * 1000)
    report("retrieved", latency_ms, f"{len(retrieved)} chunks")

    expected_document = row.get("expected_document") or ""
    expected = expected_document.lower()
    retrieved_documents = []
    rank = 0
    for index, item in enumerate(retrieved, start=1):
        document = item.chunk.document
        names = {document.title.lower(), document.original_filename.lower()}
        retrieved_documents.append(document.title)
        if expected and rank == 0 and expected in names:
            rank = index

    expected_terms = [term.lower() for term in row.get("expected_terms", [])]
    if expected_terms:
        corpus = " ".join(item.chunk.text.lower() for item in retrieved)
        covered = sum(1 for term in expected_terms if term in corpus)
        term_coverage: float | None = covered / len(expected_terms)
    elif expected:
        term_coverage = 1.0 if rank else 0.0
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
            retrieved=retrieved,
            answer_generator=answer_generator,
        )
        generation_ms = int((time.perf_counter() - generation_started) * 1000)
        report("generated", generation_ms, f"{len(answer)} chars")

        judge_started = time.perf_counter()
        judge_result = judge_answer_quality(
            question=row["question"],
            answer=answer,
            context=build_context(retrieved),
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
        hit=rank > 0,
        reciprocal_rank=1.0 / rank if rank else 0.0,
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
    results = []
    total = len(questions)
    for index, row in enumerate(questions, start=1):
        if progress_callback:
            progress_callback("start", row, index, total, None)

        def stage(name: str, info: dict, row=row, index=index) -> None:
            if progress_callback:
                progress_callback(name, row, index, total, info)

        result = evaluate_question(
            row,
            top_k,
            mode,
            rerank,
            answer_generator=answer_generator,
            answer_judge=answer_judge,
            retrieval_only=retrieval_only,
            stage_callback=stage,
        )
        results.append(result)
        if progress_callback:
            progress_callback("done", row, index, total, result)
    count = len(results)
    labeled = [r for r in results if r.expected_document]
    covered = [r for r in results if r.term_coverage is not None]
    judged_scores = [
        result.answer_quality_score
        for result in results
        if result.answer_quality_score is not None
    ]
    return EvaluationMetrics(
        question_count=count,
        recall_at_k=(
            sum(1 for r in labeled if r.hit) / len(labeled) if labeled else 0.0
        ),
        mean_reciprocal_rank=(
            sum(r.reciprocal_rank for r in labeled) / len(labeled) if labeled else 0.0
        ),
        citation_coverage=(
            sum(r.term_coverage for r in covered) / len(covered) if covered else 0.0
        ),
        groundedness_score=(
            sum(1 for r in covered if r.term_coverage >= 0.5) / len(covered)
            if covered
            else 0.0
        ),
        average_latency_ms=int(sum(r.latency_ms for r in results) / count),
        top_k=top_k,
        labeled_question_count=len(labeled),
        coverage_question_count=len(covered),
        answer_quality_score=(
            sum(judged_scores) / len(judged_scores) if judged_scores else 0.0
        ),
        judged_answer_count=len(judged_scores),
        answer_judge_model=getattr(answer_judge, "model", settings.EVAL_JUDGE_MODEL),
        results=results,
    )


def generate_answer_text(question: str, retrieved: list, answer_generator=None) -> str:
    if answer_generator is not None:
        result = answer_generator(question, retrieved)
    else:
        result = generate_answer(question, retrieved)
    return str(getattr(result, "answer", result))
