# Model configuration and limitations

The application uses Ollama for embeddings, answer generation, and optional answer-quality judging. Models are downloaded during setup; weights are not distributed with this repository. The configured defaults are:

| Role | Default identifier | Application configuration |
|---|---|---|
| Embeddings | `qwen3-embedding:0.6b` | Qdrant vector size defaults to 1024. |
| Answers | `hf.co/unsloth/Qwen3-4B-Instruct-2507-GGUF:Q4_K_M` | Temperature 0.1 and an answer-token limit of 512 by default. |
| Evaluation judge | Defaults to the answer model | Judge output is capped at 200 tokens; context is limited separately. |

These are configuration choices, not claims of best-in-class retrieval or guaranteed hardware requirements. Latency, memory use, retrieval scores, and citation behavior depend on the model, quantization, context size, hardware, and corpus. Model licenses and distribution terms must be checked with the respective model publisher when choosing weights.

## Changing models

Set `EMBEDDING_MODEL`, `LLM_MODEL`, and optionally `EVAL_JUDGE_MODEL` in `.env`, then pull the configured models with `make models`. Set `QDRANT_VECTOR_SIZE` to the embedding output dimension. A dimension change requires a compatible/new Qdrant collection, and any embedding-model change requires reindexing the stored chunks; existing vectors are not interchangeable between models.

Ollama can serve models from its own cloud. A model name tagged `:cloud` is rejected when the application starts, and `/api/status/` lists any cloud-backed entry the local Ollama reports. Set `OLLAMA_NO_CLOUD=1` on the host runtime to disable the feature itself.

Changing `OLLAMA_BASE_URL` changes where text is sent. The defaults point at the local runtime, but the application does not enforce an offline network sandbox.

## Reliability boundaries

- No retrieved evidence bypasses generation. Disabled/unavailable generation uses source excerpts.
- Citation validation checks source numbers, not whether each claim follows from the source.
- A judge score is model-generated feedback, not independently established correctness. Sharing the answer and judge model can share their biases.
- Dense cosine scores are not calibrated confidence values. `VECTOR_MIN_SCORE=0.0` remains the default; tune rejection behavior using a suitable labeled corpus.
- OCR errors can change the evidence before the model sees it. Automated parser tests do not establish real-world OCR accuracy.

The recorded evaluation uses a small synthetic corpus. Its results and limitations are in [Evaluation](evaluation.md); they should not be generalized to other document domains. Automated tests replace model calls with fakes and do not require inference. Run-specific model identifiers and data hashes are available in the Evaluations page's reproducibility details.
