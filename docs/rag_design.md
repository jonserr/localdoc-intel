# RAG Design

RAG stages:

1. Parse documents, including OCR for image files and scanned PDFs when enabled.
2. Chunk source text.
3. Preserve source metadata.
4. Generate embeddings locally with Ollama when vector indexing/search is enabled.
5. Store vectors and chunk metadata in Qdrant.
6. Retrieve relevant chunks with dense, BM25, metadata-filtered, or hybrid retrieval.
7. Apply collection scoping and metadata filters.
8. Optionally rerank through a pluggable reranker interface.
9. Generate cited answers with the local Ollama LLM using numbered source context, inline [n] citations, and an extractive fallback when the model is unavailable.
10. Store query metadata for review.
11. Run local LLM answer-quality judging during evaluations.
