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
- expected_term_coverage: fraction of a question's expected terms found in
  the retrieved text, averaged over questions with expectations. This looks at
  retrieved text before answer generation; it is not citation accuracy.
- groundedness_score: lexical proxy only. Fraction of questions with
  expectations where at least half of the expected terms appear in the
  retrieved text. It does not check whether the generated answer's claims are
  supported by the cited sources.
- unrelated-query rejection rate (stored as ``no_results_precision``): fraction
  of questions marked ``expect_no_results`` that correctly retrieved nothing.
  It catches a retriever that answers everything with something.
- answer_quality: local LLM judge score, averaged over judged answers.
- average_latency_ms: mean retrieval latency per question.

Open-ended questions (no expected_document/expected_terms) are still answered
and judged for answer quality, but they are excluded from the retrieval-rank
and coverage denominators instead of counting as automatic misses.

Every question records the retrieval strategy that actually ran (``vector``,
``hybrid``, or ``bm25``) next to the requested mode, so a run requested as
``vector`` that fell back to BM25 is reported as such rather than silently
labeled a vector run.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from chat.generation import build_context, generate_answer
from django.conf import settings
from documents.models import Document, DocumentChunk
from retrieval.services import RRF_RANK_CONSTANT, retrieve

from evaluations.judging import AnswerJudgeProvider, judge_answer_quality

# Minimum expected-term coverage required by the lexical groundedness proxy.
GROUNDEDNESS_THRESHOLD = 0.5

# Per-document ingestion settings that determine the chunks retrieval sees.
INGESTION_METADATA_KEYS = ("chunk_size", "overlap", "chunker", "offset_basis")


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
    retrieval_strategy: str = ""
    retrieval_fallback_reason: str = ""
    kind: str = ""
    expect_no_results: bool = False
    retrieved_count: int = 0
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
    expected_term_coverage: float
    groundedness_score: float
    average_latency_ms: int
    top_k: int
    labeled_question_count: int = 0
    coverage_question_count: int = 0
    no_results_precision: float = 0.0
    no_results_question_count: int = 0
    answer_quality_score: float = 0.0
    judged_answer_count: int = 0
    answer_judge_model: str = ""
    requested_mode: str = "hybrid"
    rerank: bool = True
    # Strategy that actually ran: "vector", "hybrid", "bm25", or "mixed".
    retrieval_strategy: str = ""
    retrieval_strategy_counts: dict[str, int] = field(default_factory=dict)
    fallback_reason: str = ""
    results: list[QuestionResult] = field(default_factory=list)
    effective_config: dict = field(default_factory=dict)


@dataclass(frozen=True)
class EvaluationIdentity:
    """Everything needed to reproduce a run: data identity plus code revision."""

    corpus_hash: str
    corpus_document_count: int
    chunk_hash: str
    corpus_chunk_count: int
    question_set_hash: str
    question_set_path: str
    revision: str
    embedding_model: str
    llm_model: str


def corpus_documents(collection: str | None = None):
    """Documents in fingerprint order, optionally scoped to one collection."""
    queryset = Document.objects.order_by("sha256", "id")
    if collection:
        queryset = queryset.filter(collection__name__iexact=collection)
    return queryset


def corpus_fingerprint(collection: str | None = None) -> tuple[str, int]:
    """Hash the ingested corpus identity (document content hashes)."""
    digests = list(corpus_documents(collection).values_list("sha256", flat=True))
    fingerprint = hashlib.sha256("\n".join(digests).encode("utf-8")).hexdigest()
    return fingerprint, len(digests)


def ingestion_settings_line() -> str:
    """Global settings that change extracted text, and so change chunks."""
    return json.dumps(
        {
            "ocr_enabled": settings.OCR_ENABLED,
            "ocr_pdf_dpi": settings.OCR_PDF_DPI,
            "ocr_tesseract_psm": settings.OCR_TESSERACT_PSM,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def document_ingestion_line(metadata: dict | None) -> str:
    """The ingestion settings a document recorded when it was chunked."""
    recorded = metadata or {}
    return json.dumps(
        {key: recorded.get(key) for key in INGESTION_METADATA_KEYS},
        sort_keys=True,
        separators=(",", ":"),
    )


def chunk_fingerprint(collection: str | None = None) -> tuple[str, int]:
    """Hash the retrieval corpus: chunk text, offsets, and ingestion settings.

    The corpus hash covers source bytes only. Re-ingesting identical bytes at a
    different chunk size changes what retrieval sees without changing that
    hash, so two runs are comparable only when this fingerprint matches too.
    """
    documents = corpus_documents(collection)
    digest = hashlib.sha256()
    digest.update(ingestion_settings_line().encode("utf-8"))
    for document_hash, metadata in documents.values_list("sha256", "metadata"):
        digest.update(f"\ndocument:{document_hash}:".encode())
        digest.update(document_ingestion_line(metadata).encode("utf-8"))
    chunk_count = 0
    chunk_rows = (
        DocumentChunk.objects.filter(document__in=documents)
        .order_by("document__sha256", "document_id", "chunk_index")
        .values_list(
            "document__sha256", "chunk_index", "byte_start", "byte_end", "text"
        )
    )
    for document_hash, chunk_index, byte_start, byte_end, text in chunk_rows:
        digest.update(
            f"\nchunk:{document_hash}:{chunk_index}:{byte_start}:{byte_end}:".encode()
        )
        digest.update(text.encode("utf-8"))
        chunk_count += 1
    return digest.hexdigest(), chunk_count


def question_set_fingerprint(questions: list[dict]) -> str:
    canonical = json.dumps(questions, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def current_revision() -> str:
    """Git revision of the running code, or LOCALDOC_REVISION inside Docker."""
    configured = os.environ.get("LOCALDOC_REVISION", "")
    if configured:
        return configured
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=Path(__file__).resolve().parent,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return completed.stdout.strip() if completed.returncode == 0 else ""


def evaluation_identity(
    questions: list[dict],
    questions_path: Path | str = "",
    collection: str | None = None,
) -> EvaluationIdentity:
    corpus_hash, document_count = corpus_fingerprint(collection)
    chunk_hash, chunk_count = chunk_fingerprint(collection)
    return EvaluationIdentity(
        corpus_hash=corpus_hash,
        corpus_document_count=document_count,
        chunk_hash=chunk_hash,
        corpus_chunk_count=chunk_count,
        question_set_hash=question_set_fingerprint(questions),
        question_set_path=str(questions_path),
        revision=current_revision(),
        embedding_model=settings.EMBEDDING_MODEL,
        llm_model=settings.LLM_MODEL,
    )


def validate_question_row(row, row_number: int) -> None:
    """Type-check one question row. Row numbers are 1-based, as an editor shows.

    Types are checked rather than coerced. A string "false" is truthy, so an
    untyped ``expect_no_results`` silently inverts how a question is scored.
    """
    if not isinstance(row, dict):
        raise EvaluationInputError(f"Question {row_number} must be a JSON object.")
    question = row.get("question")
    if not isinstance(question, str) or not question.strip():
        raise EvaluationInputError(
            f"Question {row_number} needs a non-empty 'question' string."
        )
    for key in ("expected_document", "collection", "kind"):
        value = row.get(key)
        if value is not None and not isinstance(value, str):
            raise EvaluationInputError(
                f"Question {row_number}: '{key}' must be a string."
            )
    expected_terms = row.get("expected_terms")
    if expected_terms is not None and (
        not isinstance(expected_terms, list)
        or not all(isinstance(term, str) for term in expected_terms)
    ):
        raise EvaluationInputError(
            f"Question {row_number}: 'expected_terms' must be a list of strings."
        )
    expect_no_results = row.get("expect_no_results")
    if expect_no_results is not None and not isinstance(expect_no_results, bool):
        raise EvaluationInputError(
            f"Question {row_number}: 'expect_no_results' must be true or false."
        )


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
    for row_number, row in enumerate(question_rows, start=1):
        validate_question_row(row, row_number)
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
    outcome = retrieve(
        question=row["question"],
        collection=row.get("collection") or None,
        top_k=top_k,
        mode=mode,
        rerank=rerank,
    )
    retrieved_chunks = outcome.chunks
    latency_ms = int((time.perf_counter() - started) * 1000)
    report(
        "retrieved",
        latency_ms,
        f"{len(retrieved_chunks)} chunks via {outcome.strategy}",
    )

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

    expect_no_results = bool(row.get("expect_no_results"))
    expected_terms = [term.lower() for term in row.get("expected_terms", [])]
    if expect_no_results:
        # Scored as precision, not coverage: the correct behavior is nothing.
        term_coverage = None
    elif expected_terms:
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
        retrieval_strategy=outcome.strategy,
        retrieval_fallback_reason=outcome.fallback_reason,
        kind=row.get("kind", ""),
        expect_no_results=expect_no_results,
        retrieved_count=len(retrieved_chunks),
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

    # Snapshot before retrieval; persistence must not read later environment values.
    effective_config = {
        "vector_min_score": settings.VECTOR_MIN_SCORE,
        "vector_search_enabled": settings.VECTOR_SEARCH_ENABLED,
        "answer_generation_enabled": settings.ANSWER_GENERATION_ENABLED,
        "retrieval_only": retrieval_only,
        "hybrid_fusion": "rrf",
        "rrf_rank_constant": RRF_RANK_CONSTANT,
    }
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
    no_results_expected = [
        result for result in question_results if result.expect_no_results
    ]
    strategy_counts = Counter(result.retrieval_strategy for result in question_results)
    if len(strategy_counts) == 1:
        actual_strategy = next(iter(strategy_counts))
    elif strategy_counts:
        actual_strategy = "mixed"
    else:
        actual_strategy = ""
    fallback_reason = next(
        (
            result.retrieval_fallback_reason
            for result in question_results
            if result.retrieval_fallback_reason
        ),
        "",
    )
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
        expected_term_coverage=(
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
        average_latency_ms=(
            int(sum(result.latency_ms for result in question_results) / question_count)
            if question_count
            else 0
        ),
        top_k=top_k,
        labeled_question_count=len(labeled_results),
        coverage_question_count=len(coverage_results),
        no_results_precision=(
            sum(1 for result in no_results_expected if result.retrieved_count == 0)
            / len(no_results_expected)
            if no_results_expected
            else 0.0
        ),
        no_results_question_count=len(no_results_expected),
        answer_quality_score=(
            sum(judged_scores) / len(judged_scores) if judged_scores else 0.0
        ),
        judged_answer_count=len(judged_scores),
        answer_judge_model=getattr(answer_judge, "model", settings.EVAL_JUDGE_MODEL),
        requested_mode=mode,
        rerank=rerank,
        retrieval_strategy=actual_strategy,
        retrieval_strategy_counts=dict(strategy_counts),
        fallback_reason=fallback_reason,
        results=question_results,
        effective_config=effective_config,
    )


def generate_answer_text(question: str, retrieved: list, answer_generator=None) -> str:
    """Generate answer text using an injected provider or the default generator."""

    if answer_generator is not None:
        generated_result = answer_generator(question, retrieved)
    else:
        generated_result = generate_answer(question, retrieved)
    return str(getattr(generated_result, "answer", generated_result))
