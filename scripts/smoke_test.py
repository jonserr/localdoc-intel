#!/usr/bin/env python
"""End-to-end smoke test through the Next.js proxy against the local stack.

Checks the path that component tests cannot reach: browser -> Next.js route
handler -> Django. It uploads a small generated document, confirms the chunks
persisted with their line/byte provenance, and confirms an unrelated question
returns no passages.

Requires the local services started by `make launch`. Against a normal
developer stack, uploads and related questions may call the configured models.
`make smoke-isolated` runs this test on a separate stack with indexing, vector
search, answer generation, async indexing, and OCR disabled.

Usage:
    python scripts/smoke_test.py [--base-url http://127.0.0.1:3000]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import urllib.error
import urllib.request
import uuid
from http.client import HTTPResponse

COLLECTION = "Smoke test"
DOCUMENT_TEXT = (
    "Smoke test fixture for the LocalDoc Intel release checks.\n"
    "The quarterly ledger reconciliation runs on the fourth business day.\n"
    "Escalate a failed reconciliation to the finance platform rota.\n"
)
UNRELATED_QUESTION = "platypus astronomy quasar redshift"


class SmokeFailure(RuntimeError):
    pass


def request_json(
    url: str,
    method: str = "GET",
    body: bytes | None = None,
    content_type: str = "application/json",
) -> dict:
    request = urllib.request.Request(url, data=body, method=method)
    if body is not None:
        request.add_header("Content-Type", content_type)
    try:
        response: HTTPResponse = urllib.request.urlopen(request, timeout=60)
    except urllib.error.HTTPError as exc:
        raise SmokeFailure(
            f"{method} {url} returned {exc.code}: {exc.read()[:400]!r}"
        ) from exc
    except urllib.error.URLError as exc:
        raise SmokeFailure(
            f"{method} {url} failed: {exc.reason}. Start the stack with make launch."
        ) from exc
    with response:
        payload = response.read()
    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise SmokeFailure(
            f"{method} {url} returned non-JSON: {payload[:200]!r}"
        ) from exc


def multipart_body(
    filename: str, content: bytes, fields: dict[str, str]
) -> tuple[bytes, str]:
    boundary = f"----localdoc{uuid.uuid4().hex}"
    parts = []
    for name, value in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'
            f"{value}\r\n".encode()
        )
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="files"; '
        f'filename="{filename}"\r\nContent-Type: text/plain\r\n\r\n'.encode()
        + content
        + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def check(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)
    print(f"  ok: {message}")


def validate_unrelated_response(
    response: dict, *, vector_search_on: bool, vector_floor: float
) -> None:
    """Check a vector-mode query with reranking off, allowing lexical fallback.

    Empty lexical results are required for the controlled nonsense query.
    A dense score floor is not a semantic guarantee of unrelatedness.
    """
    metadata = response["metadata"]
    citations = response["citations"]
    strategy = metadata.get("retrieval_strategy")
    check(strategy in {"bm25", "vector"}, "the requested strategy is reported")
    if strategy == "bm25" or not vector_search_on:
        check(strategy == "bm25", "disabled vector search uses the lexical path")
        check(not citations, "the lexical path returned no unrelated passages")
    else:
        check(metadata.get("rerank") is False, "dense scores were not reranked")
        for citation in citations:
            score = citation.get("score")
            check(
                citation.get("retrieval_source") == "vector"
                and isinstance(score, (int, float))
                and not isinstance(score, bool)
                and math.isfinite(score)
                and score >= vector_floor,
                "every dense citation meets the configured relevance floor",
            )
        print(
            "  note: dense threshold compliance does not establish relevance; "
            "unrelated passages may still exceed the configured floor."
        )
    if not citations:
        check(
            metadata.get("answer_mode") == "no_results",
            "empty retrieval reports no_results",
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", default="http://127.0.0.1:3000")
    args = parser.parse_args()
    proxy = f"{args.base_url.rstrip('/')}/api/backend"

    print("1. frontend proxy reaches the backend")
    health = request_json(f"{proxy}/health")
    check(
        health.get("status") in {"ok", "degraded"},
        f"health reports {health.get('status')}",
    )
    check(health.get("database") == "ok", "database is reachable through the proxy")

    print("2. upload through the proxy")
    filename = f"smoke-{uuid.uuid4().hex[:8]}.txt"
    body, content_type = multipart_body(
        filename, DOCUMENT_TEXT.encode(), {"collection": COLLECTION}
    )
    upload = request_json(
        f"{proxy}/documents/upload", method="POST", body=body, content_type=content_type
    )
    check(
        not upload.get("errors"), f"upload reported no errors: {upload.get('errors')}"
    )
    documents = upload.get("documents") or []
    check(len(documents) == 1, "one document was ingested")
    document = documents[0]["document"]
    check(document["status"] == "indexed", "text ingestion completed")
    check(
        document["metadata"].get("offset_basis") == "source_bytes",
        "byte offsets address the uploaded file's own bytes",
    )

    print("3. chunks persisted with provenance")
    chunks = request_json(f"{proxy}/documents/{document['id']}/chunks")
    check(len(chunks) >= 1, f"{len(chunks)} chunk(s) persisted")
    first = chunks[0]
    check(first["start_line"] == 1, "first chunk starts at line 1")
    check(first["byte_start"] == 0, "first chunk starts at byte 0")
    check(first["token_count"] > 0, "chunk token count was computed")
    check(
        "reconciliation" in " ".join(c["text"] for c in chunks),
        "chunk text is searchable",
    )

    print("4. a related question retrieves the uploaded document")
    related = request_json(
        f"{proxy}/chat/query",
        method="POST",
        body=json.dumps(
            {
                "question": "When does the quarterly ledger reconciliation run?",
                "collection": COLLECTION,
                "retrieval_mode": "hybrid",
                "top_k": 3,
            }
        ).encode(),
    )
    check(len(related["citations"]) >= 1, "the related question returned citations")
    check(
        related["citations"][0]["document"] == filename,
        "the top citation is the uploaded document",
    )

    print("5. an unrelated question")
    local_settings = request_json(f"{proxy}/settings")
    vector_search_on = local_settings["features"]["vector_search"] == "enabled"
    vector_floor = float(local_settings.get("vector_min_score") or 0.0)
    unrelated = request_json(
        f"{proxy}/chat/query",
        method="POST",
        body=json.dumps(
            {
                "question": UNRELATED_QUESTION,
                "collection": COLLECTION,
                "retrieval_mode": "vector",
                "rerank": False,
                "top_k": 5,
            }
        ).encode(),
    )

    validate_unrelated_response(
        unrelated, vector_search_on=vector_search_on, vector_floor=vector_floor
    )

    print("6. citation validation is reported")
    check(
        "citation_status" in unrelated["metadata"],
        "the API reports a citation validation outcome",
    )

    print("\nSmoke test passed.")
    print(
        f"Fixture document id: {document['id']}. Remove it through the direct backend "
        f"API: DELETE /api/documents/{document['id']}/ (the frontend proxy forwards "
        "GET and POST only)."
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SmokeFailure as failure:
        print(f"\nSmoke test failed: {failure}", file=sys.stderr)
        sys.exit(1)
