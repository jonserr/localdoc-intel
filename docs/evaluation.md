# Evaluation

The retrieval evaluation harness lives in `backend/evaluations/harness.py`. It runs retrieval metrics, generates answers, and scores answer quality with the configured local Ollama judge model.

## Metrics

- **Recall@k / hit rate** — expected document appears in the top-k retrieved chunks. Computed only over questions that declare `expected_document`.
- **Mean reciprocal rank (MRR)** — 1/rank of the first chunk from the expected document. Computed only over questions that declare `expected_document`.
- **Expected-term coverage** — fraction of a question's expected terms found in retrieved text. Computed only over questions with expectations. This inspects retrieved text before answer generation, so it measures retrieval, not citation accuracy. It was previously named "citation coverage"; the old name overstated what it measured.
- **Groundedness (lexical proxy)** — fraction of questions with at least half of expected terms covered. It does not check whether the generated answer's claims are supported by the sources it cites.
- **Unrelated-query rejection rate** — fraction of questions marked `expect_no_results` that correctly retrieved nothing. Stored as `no_results_precision`.
- **Answer quality** — local LLM score from 0.0 to 1.0 for correctness, completeness, citation use, and evidence grounding.
- **Average latency** — mean retrieval time per question.

## Running

```bash
make eval-corpus   # ingest the redistributable corpus in data/eval_corpus/
make eval-published # run the default hybrid configuration
make demo-data     # optional: copy Kaggle receipt PDFs
make ingest-demo   # index current files in data/demo_intake/
make eval          # hybrid mode, top-5, rerank on (retrieval + LLM answer + judge)
make eval-fast     # skip answer generation and judging; retrieval may embed queries

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

A row can instead assert that nothing should be retrieved. These are scored for
the unrelated-query rejection rate and never enter the recall or coverage
denominators:

```json
{
  "question": "What is the orbital period of Enceladus?",
  "kind": "unrelated",
  "expect_no_results": true
}
```

## Reproducibility

Each run records the requested retrieval mode alongside the strategy that
actually ran (`vector`, `hybrid`, `bm25`, or `mixed`) and a fallback reason, so
a run requested as `vector` that fell back to BM25 is never reported as a
vector result. Runs also persist top-k, the rerank flag, embedding and LLM
model identifiers, a question-set hash, and the code revision.

Two hashes describe the data. The corpus hash covers document content hashes,
which is source-byte identity. The chunk hash covers the chunks retrieval
actually saw — their text and byte offsets — together with the ingestion
settings that produced them (`chunk_size`, `overlap`, `chunker`,
`offset_basis`, and the OCR settings). Re-ingesting identical bytes at a
different chunk size changes retrieval while leaving the corpus hash
untouched, so the chunk hash is what makes that visible. For a controlled
comparison, hold both hashes and the question-set hash fixed and record which
retrieval or model settings intentionally differ.

Inside Docker the container has no `.git`, so the revision comes from the
`LOCALDOC_REVISION` environment variable; the `make eval*` targets pass the
current short SHA automatically.

The published results table, its corpus, and its limitations are documented in
[eval_corpus.md](eval_corpus.md) and under [Recorded results](#recorded-results).

Edit the question-set JSON for your own intake documents to track retrieval and answer quality over time.

Open-ended questions are answered and judged for answer quality but are excluded from the retrieval-rank and coverage denominators — they never count as automatic misses. When a run contains no labeled questions, `make eval` and the Evaluations page report those metrics as **n/a** instead of 0%.

The persisted `config` also snapshots `vector_min_score`, `vector_search_enabled`,
`answer_generation_enabled`, and `retrieval_only` before evaluation starts. This
distinguishes threshold experiments and runs that requested generation/judging
from retrieval-only runs. Flags describe configured behavior; actual strategy
and judged-answer counts still describe what executed. Older runs without this
snapshot display **Not recorded**; their settings are not inferred from the
current environment.

## Inspecting saved runs

Select **Inspect run** in the Evaluations history to load that run's summary.
The unrelated-query rejection rate shows its labeled-negative denominator; missing metrics
or a zero denominator show **n/a**, while a measured zero remains **0%**.
Expand **Reproducibility details** for requested mode, actual strategy, top-k,
reranking, model names, corpus identity/count, question-set identity/path, and
revision. Older runs without these fields show **Not recorded**. A fallback
reason is visible beside the selected run.

## Retrieval latency benchmark

Run inside the backend container, where the configured services are reachable:

```bash
docker compose exec -T backend python /scripts/benchmark_retrieval.py \
  --questions /data/eval_questions.json --collection "Eval Corpus" \
  --top-k 5 --runs 3 --rerank --json /data/retrieval_benchmark.json
```

For each requested mode the report includes mean, median, nearest-rank p95,
actual-strategy counts, fallback-reason counts, and empty-result counts. A
requested vector run that falls back to BM25 is labeled accordingly. The
collection option overrides per-question collections; without it, each row's
collection is honored. Reranking is off unless `--rerank` is supplied.
The report includes first-query startup costs and does not run a separate
warm-up; use the same question order, services, corpus, and cache conditions
when comparing it. These timings cover retrieval, which may call the embedding
model, and exclude answer generation and judging.

## Dense relevance floor

A vector store returns its nearest neighbours whether or not they are relevant,
so vector-only retrieval answers every question, including nonsense.
`VECTOR_MIN_SCORE` sets an optional cosine floor. It defaults to `0.0` (off)
because cosine scores are not comparable across embedding models or corpora.

On the shipped corpus, top-1 cosine scores separated unrelated questions
(max 0.348) from real ones (min 0.386) — a 0.04 gap over 16 questions, far too
narrow and too small a sample to hardcode. Measure your own corpus before
raising the floor.

## Performance

A full run makes two local LLM calls per question (answer generation, then judging), so total time is dominated by inference speed. Levers:

- `make eval-fast` / `--retrieval-only` — skip all LLM calls when iterating on retrieval.
- `LLM_MAX_ANSWER_TOKENS` (default 512) and `EVAL_JUDGE_MAX_TOKENS` (default 200) cap response lengths.
- `EVAL_JUDGE_MAX_CONTEXT_CHARS` (default 4000) truncates evidence sent to the judge.
- `OLLAMA_KEEP_ALIVE` (default 10m) keeps models loaded between questions, avoiding reload stalls.
- Progress output reports each stage (retrieved → generating → judging) with per-stage timings, and the summary includes average retrieval/generation/judging time.

## Hybrid fusion policy

New runs also record `config.hybrid_fusion="rrf"` and `config.rrf_rank_constant=60`. These describe the configured hybrid policy; actual strategy counts still show whether both retrievers contributed. Older runs without these keys have no recorded fusion policy. The historical README table used the earlier score-max merge and is not validation of RRF.

## Recorded results

These results were recorded during 1.1.0 development, using the previous score-max hybrid merge, before reciprocal rank fusion. They have not been rerun under the new fusion policy and do not establish its retrieval quality.

Corpus: the six documents in `data/eval_corpus/` (`corpus_hash f5f99450353c`, 6 documents, 6 chunks). Questions: `data/eval_questions.json` (`question_set_hash d56dca3dc280`, 16 questions, of which 6 relevant, 4 paraphrased, 3 ambiguous, and 3 unrelated). 10 questions carry an `expected_document`, 13 carry expected terms, and 3 expect no results. Models: `qwen3-embedding:0.6b` and `hf.co/unsloth/Qwen3-4B-Instruct-2507-GGUF:Q4_K_M`, top-k 5, rerank on, Apple M5 and macOS 27.0.

| Configuration | Recall@5 (n=10) | MRR (n=10) | Expected-term coverage (n=13) | Groundedness proxy (n=13) | Unrelated rejected (n=3) |
|---|---:|---:|---:|---:|---:|
| hybrid, no vector floor | 100% | 0.925 | 88.5% | 100% | 0% |
| vector only, no floor | 100% | 0.925 | 88.5% | 100% | 0% |
| BM25 only | 90% | 0.900 | 80.8% | 92.3% | 66.7% |
| hybrid, `VECTOR_MIN_SCORE=0.37` | 100% | 0.925 | 88.5% | 100% | 66.7% |
| vector only, `VECTOR_MIN_SCORE=0.37` | 100% | 0.925 | 84.6% | 100% | 66.7% |

A full run of the fourth row, including generation and judging, scored **77.5% answer quality over 16 judged answers**, at 1.1 s generation, 1.3 s judging, and 946 ms retrieval per question on that hardware. That is the only live-model evaluation recorded for this release.

On 2026-09-11 a retrieval-only rerun on the release candidate ran with the embedding service unavailable. It fell back to BM25 and matched the BM25-only row on the same corpus and question-set hashes. The dense, floor, and generation rows were not rerun.

Read the table for the shape of the differences, not for the absolute values. Six documents and 16 questions is a behavior fixture, not a benchmark. The sample is far too small for confidence intervals, and 100% recall over ten questions mostly says the corpus is easy. Three specifics are worth knowing:

1. A vector store always returns its nearest neighbours, so with no floor dense retrieval answers every question, including nonsense. That is why the unrelated-query rejection rate is 0% in the first two rows. See [Dense relevance floor](#dense-relevance-floor).
2. The remaining unrelated question leaks through the lexical path. BM25 drops query terms that appear in at least 90% of the corpus, but with only six chunks "of" sits at 83% and still matches. Document-frequency filtering needs a corpus large enough for document frequency to mean something. A floor on `score / max_score` cannot reject that question's best weak match, because that score always normalizes to 1.
3. BM25 alone loses one labeled question, at 90% recall against 100%. It is the paraphrased question that shares no vocabulary with its source document. That is the case hybrid retrieval exists for.
