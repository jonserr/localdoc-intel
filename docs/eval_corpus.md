# Redistributable evaluation corpus

The corpus lives in `data/eval_corpus/`. This file documents it and is kept
outside that folder so it is never ingested as a corpus document.

Six short synthetic documents written for this repository, plus a labeled
question set. Nothing here is downloaded, licensed from a third party, or
derived from personal data, so `make eval-corpus` loads the same source corpus without `make demo-data`.
The published results used the earlier score-max hybrid merge. Current hybrid
retrieval uses RRF; repeat the evaluation to measure its results.

The corpus is deliberately small. It is a regression and behavior fixture, not
a benchmark: six documents cannot support claims about retrieval quality at
scale, and the sample sizes below are far too small for confidence intervals.

The question set (`data/eval_questions.json`) covers four question kinds:

| Kind | What it tests | Count |
|---|---|---|
| `relevant` | Direct lookup with one clearly correct source | 6 |
| `paraphrased` | Same facts, none of the document's wording | 4 |
| `ambiguous` | Terms that appear in more than one document | 3 |
| `unrelated` | Nothing in the corpus answers it | 3 |

`unrelated` rows set `"expect_no_results": true`. They are the denominator of
the unrelated-query rejection rate: retrieval must return nothing. They carry
no `expected_document`, so they never enter the recall or MRR denominators.

Reproduce a run:

```bash
make eval-corpus   # ingest data/eval_corpus into the "Eval Corpus" collection
docker compose exec -T backend python manage.py run_eval \
  --questions /data/eval_questions.json --collection "Eval Corpus" \
  --mode hybrid --top-k 5
```

Each run persists its retrieval mode, actual strategy, top-k, rerank flag,
model identifiers, corpus hash, question-set hash, and code revision, so two
runs can be compared only when those match.
