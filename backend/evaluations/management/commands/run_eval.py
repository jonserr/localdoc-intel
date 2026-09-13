"""Run the retrieval evaluation harness and persist an EvaluationRun."""

from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from evaluations.harness import (
    EvaluationInputError,
    default_questions_path,
    evaluation_identity,
    load_questions,
    run_evaluation,
)
from evaluations.runs import record_evaluation_run

ANSI_GREEN = "\033[32m"
ANSI_RESET = "\033[0m"
PROGRESS_BAR_WIDTH = 30


def progress_bar(completed: int, total: int) -> str:
    if total <= 0:
        return "[" + "-" * PROGRESS_BAR_WIDTH + "]"
    bounded = max(0, min(completed, total))
    filled = round((bounded / total) * PROGRESS_BAR_WIDTH)
    return "[" + "=" * filled + "-" * (PROGRESS_BAR_WIDTH - filled) + "]"


def format_elapsed(elapsed_ms: int) -> str:
    if elapsed_ms >= 1000:
        return f"{elapsed_ms / 1000:.1f}s"
    return f"{elapsed_ms}ms"


def result_marker(result) -> str:
    """PASS/MISS for labeled and no-result rows; OPEN for unscored ones."""
    if result is None:
        return "OPEN"
    if result.expect_no_results:
        return "PASS" if result.retrieved_count == 0 else "MISS"
    if result.expected_document:
        return "PASS" if result.hit else "MISS"
    return "OPEN"


def one_line(text: str, max_chars: int) -> str:
    """Collapse whitespace and truncate for single-line report output."""
    collapsed = " ".join(str(text).split())
    if len(collapsed) > max_chars:
        return collapsed[: max_chars - 3] + "..."
    return collapsed


class Command(BaseCommand):
    help = "Evaluate retrieval and answer quality against a demo question set."

    def add_arguments(self, parser):
        parser.add_argument("--questions", default="")
        parser.add_argument(
            "--collection",
            default="",
            help="Scope retrieval to this collection for rows that do not name one.",
        )
        parser.add_argument("--top-k", type=int, default=5)
        parser.add_argument(
            "--mode",
            default="hybrid",
            choices=["vector", "hybrid", "metadata-filtered"],
        )
        parser.add_argument("--no-rerank", action="store_true")
        parser.add_argument("--name", default="")
        parser.add_argument(
            "--no-progress",
            action="store_true",
            help="Suppress per-question progress output.",
        )
        parser.add_argument(
            "--retrieval-only",
            action="store_true",
            help=(
                "Skip answer generation and judging (no LLM calls). Runs in "
                "seconds; answer quality is reported as n/a."
            ),
        )

    def handle(self, *args, **options):
        questions_path = (
            Path(options["questions"])
            if options["questions"]
            else default_questions_path()
        )
        try:
            questions = load_questions(questions_path)
            if options["collection"]:
                questions = [
                    {
                        **question,
                        "collection": question.get("collection")
                        or options["collection"],
                    }
                    for question in questions
                ]
            identity = evaluation_identity(
                questions, questions_path, collection=options["collection"] or None
            )
            self.stdout.write(
                f"Evaluating {len(questions)} questions from {questions_path} "
                f"(mode={options['mode']}, top_k={options['top_k']}, "
                f"rerank={not options['no_rerank']})."
            )

            stage_messages = {
                "retrieved": "generating answer with local LLM...",
                "generated": "judging answer quality...",
                "judged": "",
            }
            if options["retrieval_only"]:
                stage_messages["retrieved"] = ""

            def progress(state, row, index, total, result):
                if options["no_progress"]:
                    return
                question = row.get("question", "").strip()
                if len(question) > 70:
                    question = question[:67] + "..."

                if state in stage_messages:
                    info = result or {}
                    elapsed = format_elapsed(info.get("elapsed_ms", 0))
                    detail = info.get("detail", "")
                    line = f"        {state} in {elapsed}"
                    if detail:
                        line += f" ({detail})"
                    next_step = stage_messages[state]
                    if next_step:
                        line += f"; {next_step}"
                    self.stdout.write(line)
                    return

                completed = index if state == "done" else index - 1
                percent = round((completed / total) * 100) if total else 0
                bar = f"{ANSI_GREEN}{progress_bar(completed, total)}{ANSI_RESET}"
                if state == "start":
                    self.stdout.write(
                        f"{bar} {percent:3d}% {completed:>3}/{total:<3} "
                        f"evaluating {question}"
                    )
                    return
                marker = result_marker(result)
                total_ms = (
                    result.latency_ms + result.generation_ms + result.judge_ms
                    if result
                    else 0
                )
                self.stdout.write(
                    f"{bar} {percent:3d}% {completed:>3}/{total:<3} "
                    f"{marker:<4}      {question} ({format_elapsed(total_ms)} total)"
                )

            metrics = run_evaluation(
                questions,
                top_k=options["top_k"],
                mode=options["mode"],
                rerank=not options["no_rerank"],
                retrieval_only=options["retrieval_only"],
                progress_callback=progress,
            )
        except EvaluationInputError as exc:
            raise CommandError(str(exc)) from exc

        run = record_evaluation_run(
            options["name"] or f"{options['mode']} top-{options['top_k']}",
            metrics,
            identity,
        )
        self.stdout.write("")
        self.stdout.write("Results:")
        for result in metrics.results:
            marker = result_marker(result)
            expected = (
                f" (expected {result.expected_document})"
                if result.expected_document
                else ""
            )
            coverage = (
                f"coverage {result.term_coverage:.0%}"
                if result.term_coverage is not None
                else "coverage n/a"
            )
            self.stdout.write(f"\n[{marker}] {result.question}{expected}")
            answer = one_line(result.answer, 220)
            if answer:
                self.stdout.write(f"  answer:  {answer}")
            score = result.answer_quality_score
            rationale = one_line(result.answer_quality_rationale, 160)
            judge_error = one_line(result.answer_judge_error, 160)
            if score is not None:
                verdict = f"  judge:   {score:.2f}"
                if rationale:
                    verdict += f" - {rationale}"
                self.stdout.write(verdict)
            elif judge_error:
                self.stdout.write(f"  judge:   failed - {judge_error}")
            self.stdout.write(
                f"  sources: "
                f"{', '.join(result.retrieved_documents[:3]) or 'nothing'} "
                f"({coverage}, retrieval {result.latency_ms}ms)"
            )

        labeled = metrics.labeled_question_count
        covered = metrics.coverage_question_count
        recall = (
            f"{metrics.recall_at_k:.2%} ({labeled} labeled)"
            if labeled
            else "n/a (no questions define expected_document)"
        )
        mrr = (
            f"{metrics.mean_reciprocal_rank:.3f} ({labeled} labeled)"
            if labeled
            else "n/a (no questions define expected_document)"
        )
        coverage_line = (
            f"{metrics.expected_term_coverage:.2%} ({covered} scored)"
            if covered
            else "n/a (no questions define expected_terms)"
        )
        groundedness = (
            f"{metrics.groundedness_score:.2%} ({covered} scored)"
            if covered
            else "n/a (no questions define expected_terms)"
        )

        self.stdout.write("")
        self.stdout.write(f"Evaluation run #{run.id}: {run.name}")
        self.stdout.write(f"  questions:          {metrics.question_count}")
        self.stdout.write(f"  recall@{metrics.top_k}:           {recall}")
        self.stdout.write(f"  MRR:                {mrr}")
        self.stdout.write(f"  expected-term cov.: {coverage_line}")
        self.stdout.write(f"  groundedness*:      {groundedness}")
        if options["retrieval_only"]:
            quality = "skipped (--retrieval-only)"
        elif metrics.judged_answer_count:
            quality = (
                f"{metrics.answer_quality_score:.2%} "
                f"({metrics.judged_answer_count} judged)"
            )
        else:
            quality = "n/a (0 judged)"
        self.stdout.write(f"  answer quality:     {quality}")
        if metrics.no_results_question_count:
            self.stdout.write(
                f"  unrelated rejected: {metrics.no_results_precision:.2%} "
                f"({metrics.no_results_question_count} unrelated)"
            )
        self.stdout.write(
            f"  answer judge:       {metrics.answer_judge_model or 'unavailable'}"
        )
        self.stdout.write(f"  avg retrieval:      {metrics.average_latency_ms}ms")
        strategy = metrics.retrieval_strategy or "none"
        requested = metrics.requested_mode
        strategy_line = (
            strategy if strategy == requested else f"{strategy} (requested {requested})"
        )
        self.stdout.write(f"  retrieval strategy: {strategy_line}")
        if metrics.fallback_reason:
            self.stdout.write(f"  fallback reason:    {metrics.fallback_reason}")
        self.stdout.write(
            f"  corpus:             {identity.corpus_document_count} documents, sha256 {identity.corpus_hash[:12]}"
        )
        self.stdout.write(
            f"  chunks:             {identity.corpus_chunk_count} chunks, sha256 {identity.chunk_hash[:12]}"
        )
        self.stdout.write(
            f"  question set:       sha256 {identity.question_set_hash[:12]} ({questions_path})"
        )
        self.stdout.write(f"  revision:           {identity.revision or 'unknown'}")
        self.stdout.write(f"  embedding model:    {identity.embedding_model}")
        self.stdout.write("")
        self.stdout.write(
            "* groundedness is a lexical proxy over retrieved text, not a check that answer claims are supported."
        )
        if metrics.results and not options["retrieval_only"]:
            count = len(metrics.results)
            avg_generation = (
                sum(result.generation_ms for result in metrics.results) / count
            )
            avg_judge = sum(result.judge_ms for result in metrics.results) / count
            self.stdout.write(
                f"  avg generation:     {format_elapsed(int(avg_generation))}"
            )
            self.stdout.write(f"  avg judging:        {format_elapsed(int(avg_judge))}")
        if not metrics.judged_answer_count and not options["retrieval_only"]:
            first_error = next(
                (
                    result.answer_judge_error
                    for result in metrics.results
                    if result.answer_judge_error
                ),
                "",
            )
            if first_error:
                self.stdout.write(
                    f"\nAnswer judging failed for every question. First error: "
                    f"{first_error}"
                )
        if not labeled:
            self.stdout.write(
                '\nTip: add "expected_document" (and optionally '
                '"expected_terms") to entries in your questions file to '
                "enable retrieval regression metrics."
            )
