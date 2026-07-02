# Model Card

Default local models (Hugging Face-sourced, served by Ollama, pulled during setup, swappable in `.env`):

| Role | Model | Source | Dim / Size | License |
|---|---|---|---|---|
| Embeddings | `qwen3-embedding:0.6b` | [Qwen/Qwen3-Embedding-0.6B](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B) | 1024-dim, ~640MB | Apache-2.0 |
| LLM | `hf.co/unsloth/Qwen3-4B-Instruct-2507-GGUF:Q4_K_M` | [unsloth/Qwen3-4B-Instruct-2507-GGUF](https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF) | 4B params, ~2.5GB quantized | Apache-2.0 |

`EVAL_JUDGE_MODEL` defaults to `LLM_MODEL`, so setup pulls one shared local model unless you configure a separate judge.

## Selection rationale

- **Qwen3-Embedding-0.6B**: among the strongest retrieval embeddings per parameter on MTEB, multilingual (100+ languages), permissive license, small enough for laptop-class hardware. Output dimension 1024 must match `QDRANT_VECTOR_SIZE`.
- **Qwen3-4B-Instruct-2507**: strong instruction-following at 4B, which matters for citation discipline because answers should include `[n]` markers for document-backed claims. The Q4_K_M quant runs comfortably on 8GB RAM. Pulled by Ollama directly from Hugging Face — no model weights are shipped in this repository.

## Swapping models

Set in `.env`:

```bash
LLM_MODEL=hf.co/<org>/<repo>-GGUF:<quant>   # or any Ollama library model
EVAL_JUDGE_MODEL=hf.co/<org>/<repo>-GGUF:<quant>
EMBEDDING_MODEL=<ollama-embedding-model>
QDRANT_VECTOR_SIZE=<embedding output dimension>
```

Re-index documents after changing the embedding model.

## Testing policy

Automated tests mock all model calls and must not require live inference. Generation degrades to an extractive answer when Ollama is unavailable.
