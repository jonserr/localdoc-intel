# API

API surface:

- `GET /api/health/`
- `GET /api/status/` — service and model availability
- `GET /api/stats/`
- `POST /api/documents/upload/`
- `POST /api/documents/ingest-folder/`
- `GET /api/documents/`
- `GET /api/documents/{id}/`
- `GET /api/documents/{id}/chunks/`
- `POST /api/chat/query/`
- `GET /api/chat/history/`
- `POST /api/evaluations/run/`
- `GET /api/evaluations/`
- `GET /api/settings/`

`POST /api/evaluations/run/` accepts:

```json
{
  "name": "Manual evaluation",
  "mode": "hybrid",
  "top_k": 5,
  "rerank": true
}
```

Every evaluation run generates answers and scores them with the configured local Ollama judge model.
