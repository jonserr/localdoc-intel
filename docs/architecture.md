# Architecture

LocalDoc Intel uses a Next.js frontend, Django REST Framework backend, PostgreSQL metadata store, Redis broker/cache, Celery worker, Qdrant vector database, and Ollama local model runtime.

The backend keeps ingestion, OCR, chunking, retrieval, answer generation, and evaluation in separate modules so local-first behavior can be tested without live model calls.
