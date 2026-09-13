#!/usr/bin/env python
"""Prove that the stack works with no internet access.

The offline Compose project (see compose.offline.yml) attaches every service
to an internal network, so no container has a route off the host and no port
is published. This check confirms three things:

1. No container can reach the internet: Docker reports the network as
   internal, public DNS resolution fails, and a direct TCP connection to a
   public address fails from the services that can run code.
2. The services still reach each other: the request flow runs inside the
   isolated network, from the backend container through the frontend proxy
   back to the backend, PostgreSQL, Redis, and Qdrant.
3. The application still works: an upload is parsed, chunked, and stored, and
   a question returns the uploaded document.

Default mode keeps model-backed features disabled. Live mode (`--mode live`)
uses the containerized Ollama in the same isolated network and requires an
embedded, retrieved, and cited answer from the local model.

Usage:
    python scripts/offline_check.py --mode hermetic --json report.json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILES = ("docker-compose.yml", "compose.prod.yml", "compose.offline.yml")
PROJECT = "localdoc-offline"
# Public address reached without DNS, so a refusal cannot be a name-service artifact.
PUBLIC_IP = "1.1.1.1"
PUBLIC_NAME = "pypi.org"
PROXY = "http://frontend:3000/api/backend"


class CheckFailed(RuntimeError):
    pass


def compose(
    *args: str, check: bool = True, timeout: int = 300, stdin: str | None = None
):
    command = ["docker", "compose", "-p", PROJECT]
    for name in COMPOSE_FILES:
        command.extend(["-f", str(ROOT / name)])
    command.extend(args)
    return subprocess.run(
        command,
        check=check,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=ROOT,
        input=stdin,
    )


def report(passed: bool, message: str) -> bool:
    print(f"  {'ok' if passed else 'FAILED'}: {message}")
    return passed


def require(passed: bool, message: str) -> None:
    if not report(passed, message):
        raise CheckFailed(message)


def network_is_internal() -> dict:
    """Docker itself reports whether the network has a route off the host."""
    name = f"{PROJECT}_default"
    result = subprocess.run(
        ["docker", "network", "inspect", name, "--format", "{{.Internal}} {{.Driver}}"],
        check=True,
        capture_output=True,
        text=True,
    )
    internal, driver = result.stdout.split()
    return {"network": name, "internal": internal == "true", "driver": driver}


PYTHON_EGRESS_PROBE = f"""
import socket, json
results = {{}}
try:
    socket.gethostbyname("{PUBLIC_NAME}")
    results["dns"] = "resolved"
except Exception as exc:
    results["dns"] = f"blocked: {{type(exc).__name__}}"
try:
    socket.create_connection(("{PUBLIC_IP}", 443), timeout=5).close()
    results["tcp"] = "connected"
except Exception as exc:
    results["tcp"] = f"blocked: {{type(exc).__name__}}"
print(json.dumps(results))
"""

NODE_EGRESS_PROBE = f"""
const dns = require("node:dns");
const net = require("node:net");
const results = {{}};
const done = () => {{ if (results.dns && results.tcp) {{ console.log(JSON.stringify(results)); process.exit(0); }} }};
dns.lookup("{PUBLIC_NAME}", (error) => {{ results.dns = error ? `blocked: ${{error.code}}` : "resolved"; done(); }});
const socket = net.connect({{ host: "{PUBLIC_IP}", port: 443, timeout: 5000 }});
socket.on("connect", () => {{ results.tcp = "connected"; socket.destroy(); done(); }});
socket.on("timeout", () => {{ results.tcp = "blocked: timeout"; socket.destroy(); done(); }});
socket.on("error", (error) => {{ results.tcp = `blocked: ${{error.code}}`; done(); }});
"""

# The Ollama image has no Python; bash reaches the network the same way.
BASH_EGRESS_PROBE = f"""
dns=blocked; tcp=blocked
getent hosts {PUBLIC_NAME} >/dev/null 2>&1 && dns=resolved
timeout 5 bash -c 'exec 3<>/dev/tcp/{PUBLIC_IP}/443' >/dev/null 2>&1 && tcp=connected
printf '{{"dns":"%s","tcp":"%s"}}\\n' "$dns" "$tcp"
"""


def egress_probe(service: str, runner: list[str], script: str) -> dict:
    result = compose("exec", "-T", service, *runner, script, check=False, timeout=120)
    if result.returncode != 0:
        raise CheckFailed(
            f"{service}: egress probe did not run: {result.stderr.strip()[:200]}"
        )
    return json.loads(result.stdout.strip().splitlines()[-1])


def check_egress_blocked(service: str, runner: list[str], script: str) -> dict:
    probe = egress_probe(service, runner, script)
    require(
        probe["dns"].startswith("blocked"),
        f"{service}: public DNS name is not resolvable ({probe['dns']})",
    )
    require(
        probe["tcp"].startswith("blocked"),
        f"{service}: TCP to {PUBLIC_IP}:443 is refused ({probe['tcp']})",
    )
    return probe


def application_flow(mode: str, secret: str, timeout: int) -> dict:
    """Run the request flow from inside the isolated network and return its report."""
    script = APPLICATION_FLOW.replace("__MODE__", mode).replace("__SECRET__", secret)
    result = compose(
        "exec",
        "-T",
        "backend",
        "python",
        "-",
        check=False,
        timeout=timeout,
        stdin=script,
    )
    if result.returncode != 0:
        raise CheckFailed(f"in-network flow failed: {result.stderr.strip()[-400:]}")
    return json.loads(result.stdout.strip().splitlines()[-1])


APPLICATION_FLOW = """
import json, sys, time, urllib.request, uuid

MODE = "__MODE__"
SECRET = "__SECRET__"
PROXY = "http://frontend:3000/api/backend"
DOCUMENT = (
    "Offline verification note.\\n"
    f"The isolated launch code is {SECRET}.\\n"
    "Quote the launch code exactly when asked for it.\\n"
)


def call(path, body=None, content_type="", timeout=900):
    request = urllib.request.Request(f"{PROXY}{path}", data=body)
    if content_type:
        request.add_header("Content-Type", content_type)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def wait_for_proxy(attempts=120):
    last = ""
    for _ in range(attempts):
        try:
            return call("/health", timeout=10)
        except Exception as exc:
            last = f"{type(exc).__name__}: {exc}"
            time.sleep(1)
    raise RuntimeError(f"frontend proxy never answered: {last}")


def upload(filename):
    boundary = uuid.uuid4().hex
    body = "".join(
        [
            f"--{boundary}\\r\\nContent-Disposition: form-data; name=\\"collection\\"\\r\\n\\r\\nOffline check\\r\\n",
            f"--{boundary}\\r\\nContent-Disposition: form-data; name=\\"files\\"; "
            f'filename="{filename}"\\r\\nContent-Type: text/plain\\r\\n\\r\\n{DOCUMENT}\\r\\n',
            f"--{boundary}--\\r\\n",
        ]
    ).encode("utf-8")
    return call(
        "/documents/upload", body, f"multipart/form-data; boundary={boundary}"
    )


out = {}
out["health"] = wait_for_proxy()
out["status"] = call("/status", timeout=60)
uploaded = upload(f"offline-{SECRET.lower()}.txt")
out["upload_errors"] = uploaded.get("errors")
documents = uploaded.get("documents") or []
out["documents"] = documents
if documents:
    # Each upload entry wraps the serialized document.
    document = documents[0].get("document", documents[0])
    out["document"] = document
    out["chunks"] = call(f"/documents/{document['id']}/chunks", timeout=60)
    if MODE == "live":
        question = {
            "question": "What is the isolated launch code?",
            "retrieval_mode": "vector",
            "top_k": 1,
            "rerank": False,
        }
    else:
        question = {
            "question": f"What is the isolated launch code {SECRET}?",
            "retrieval_mode": "hybrid",
            "top_k": 3,
        }
    out["answer"] = call(
        "/chat/query", json.dumps(question).encode("utf-8"), "application/json"
    )
print(json.dumps(out))
"""


def service_digests() -> dict:
    """Record what actually ran, so the report is reproducible."""
    result = compose("ps", "--format", "json", check=False, timeout=60)
    digests = {}
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        digests[row.get("Service", "?")] = row.get("Image", "?")
    return digests


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mode", choices=["hermetic", "live"], default="hermetic")
    parser.add_argument("--json", type=Path, default=None, help="write a report file")
    args = parser.parse_args()

    secret = f"OFFLINE-{uuid.uuid4().hex[:8].upper()}"
    result = {"mode": args.mode, "synthetic_only": True, "secret_document": secret}

    print("1. the Compose network has no route off the host")
    network = network_is_internal()
    require(network["internal"], f"{network['network']} is an internal network")
    result["network"] = network
    result["images"] = service_digests()

    print("2. containers cannot reach the internet")
    probes = {
        "backend": check_egress_blocked(
            "backend", ["python", "-c"], PYTHON_EGRESS_PROBE
        ),
        "frontend": check_egress_blocked("frontend", ["node", "-e"], NODE_EGRESS_PROBE),
    }
    if args.mode == "live":
        probes["ollama"] = check_egress_blocked(
            "ollama", ["bash", "-c"], BASH_EGRESS_PROBE
        )
    result["egress_probes"] = probes

    print("3. the local services still reach each other")
    flow = application_flow(
        args.mode, secret, timeout=1800 if args.mode == "live" else 600
    )
    require(
        flow["health"].get("database") == "ok",
        "the frontend proxy reaches the backend and its database",
    )
    services = flow["status"].get("services", {})
    for name in ("database", "redis", "qdrant"):
        require(
            services.get(name, {}).get("available") is True,
            f"the backend reaches {name}",
        )
    if args.mode == "live":
        require(
            services.get("ollama", {}).get("available") is True,
            "the backend reaches the isolated Ollama",
        )
        require(
            services["ollama"].get("configured_cloud_models") == [],
            "no configured model is served from a cloud",
        )
    result["services"] = {
        name: value.get("available") for name, value in services.items()
    }
    result["features"] = flow["status"].get("features", {})

    print("4. the application still works offline")
    require(
        not flow["upload_errors"], f"upload reported no errors: {flow['upload_errors']}"
    )
    require(len(flow["documents"]) == 1, "one document was ingested")
    document = flow["document"]
    require(document["status"] == "indexed", "text ingestion completed")
    require(len(flow["chunks"]) >= 1, "chunks persisted with provenance")
    result["document"] = {
        "status": document["status"],
        "vector_indexing": document.get("vector_indexing"),
        "chunk_count": document.get("chunk_count"),
    }

    answer = flow["answer"]
    metadata = answer.get("metadata", {})
    require(bool(answer.get("citations")), "the answer cites the uploaded document")
    require(
        answer["citations"][0]["document"] == document["title"],
        "the top citation is the uploaded document",
    )
    if args.mode == "live":
        require(
            document.get("vector_indexing") == "succeeded",
            "vector indexing succeeded offline",
        )
        require(
            metadata.get("retrieval_strategy") == "vector",
            "dense retrieval ran offline "
            f"(strategy={metadata.get('retrieval_strategy')!r}, "
            f"fallback={metadata.get('retrieval_fallback_reason')!r})",
        )
        require(
            secret in answer.get("answer", ""), f"the generated answer quotes {secret}"
        )
        require(
            metadata.get("answer_mode") == "generated",
            "the local model generated the answer",
        )
        require(
            metadata.get("citation_status") == "valid", "citation references are valid"
        )
    result["answer"] = {"answer": answer.get("answer"), "metadata": metadata}

    result["passed"] = True
    print(f"\nOffline check passed ({args.mode} mode).")
    if args.json:
        args.json.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(f"Report: {args.json}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (CheckFailed, subprocess.SubprocessError) as error:
        print(f"\nOffline check failed: {error}", file=sys.stderr)
        sys.exit(1)
