# Evaluation

The retrieval evaluation harness lives in `backend/evaluations/harness.py`. It runs retrieval metrics, generates answers, and scores answer quality with the configured local Ollama judge model.

## Metrics

- **Recall@k / hit rate** — expected document appears in the top-k retrieved chunks. Computed only over questions that declare `expected_document`.
- **Mean reciprocal rank (MRR)** — 1/rank of the first chunk from the expected document. Computed only over questions that declare `expected_document`.
- **Citation coverage** — fraction of a question's expected terms found in retrieved text. Computed only over questions with expectations.
- **Groundedness** — fraction of questions with at least half of expected terms covered (lexical proxy). Computed only over questions with expectations.
- **Answer quality** — local LLM score from 0.0 to 1.0 for correctness, completeness, citation use, and evidence grounding.
- **Average latency** — mean retrieval time per question.

## Running

```bash
make demo-data     # optional: copy Kaggle receipt PDFs
make ingest-demo   # index current files in data/demo_intake/
make eval          # hybrid mode, top-5, rerank on (retrieval + LLM answer + judge)
make eval-fast     # retrieval metrics only, no LLM calls (seconds)

# Compare configurations:
docker compose exec backend python manage.py run_eval --mode vector --top-k 3
docker compose exec backend python manage.py run_eval --no-rerank
docker compose exec backend python manage.py run_eval --retrieval-only
```

Each run is persisted as an `EvaluationRun` and shown on the Evaluations page. The editable demo question set is `data/demo_questions.json`. Rows may be open-ended:

```json
{
  "question": "What dates are visible?"
}
```

For regression-style retrieval metrics, rows can also include expected source information:

```json
{
  "question": "Which source file supports the answer?",
  "expected_document": "receipt-001.pdf",
  "expected_terms": ["total", "date"]
}
```

Edit this file for your own intake documents to track retrieval and answer quality over time.

Open-ended questions are answered and judged for answer quality but are excluded from the retrieval-rank and coverage denominators — they never count as automatic misses. When a run contains no labeled questions, `make eval` and the Evaluations page report those metrics as **n/a** instead of 0%.

## Performance

A full run makes two local LLM calls per question (answer generation, then judging), so total time is dominated by inference speed. Levers:

- `make eval-fast` / `--retrieval-only` — skip all LLM calls when iterating on retrieval.
- `LLM_MAX_ANSWER_TOKENS` (default 512) and `EVAL_JUDGE_MAX_TOKENS` (default 200) cap response lengths.
- `EVAL_JUDGE_MAX_CONTEXT_CHARS` (default 4000) truncates evidence sent to the judge.
- `OLLAMA_KEEP_ALIVE` (default 10m) keeps models loaded between questions, avoiding reload stalls.
- Progress output reports each stage (retrieved → generating → judging) with per-stage timings, and the summary includes average retrieval/generation/judging time.
