# Readiness probes are bounded; slow machines can increase the attempt count.
LOCALDOC_WAIT_ATTEMPTS ?= 60
# Tag for images built by `make images` and used by the isolated smoke stack.
LOCALDOC_RELEASE_TAG ?= release-check
SMOKE_COMPOSE = LOCALDOC_RELEASE_TAG=$(LOCALDOC_RELEASE_TAG) docker compose -p localdoc-smoke -f docker-compose.yml -f compose.smoke.yml
PROD_COMPOSE = LOCALDOC_RELEASE_TAG=$(LOCALDOC_RELEASE_TAG) docker compose -p localdoc-prod -f docker-compose.yml -f compose.prod.yml
OFFLINE_COMPOSE = LOCALDOC_RELEASE_TAG=$(LOCALDOC_RELEASE_TAG) docker compose -p localdoc-offline -f docker-compose.yml -f compose.prod.yml -f compose.offline.yml
# make offline-check MODELS=live adds the containerized Ollama.
MODELS ?= hermetic
ifeq ($(MODELS),live)
OFFLINE_ENV = LOCALDOC_OFFLINE_MODELS=true LOCALDOC_OFFLINE_OLLAMA_URL=http://ollama:11434
OFFLINE_PROFILE = --profile models
else
OFFLINE_ENV =
OFFLINE_PROFILE =
endif

.PHONY: setup build up down migrate test lint format format-check migration-check ports-check privacy-check version-check smoke check dev launch wait wait-backend wait-backend-container wait-frontend wait-proxy launch-open backend-up frontend-dev frontend-test frontend-lint frontend-format frontend-build frontend-ci frontend-audit images prod-images prod-up prod-down prod-logs offline-check packaged-test smoke-isolated isolation-check release-check backend-dev cpp-build cpp-test demo-data ingest-demo eval-corpus eval-published eval eval-fast models env reset clean
env:
	@test -f .env || (cp .env.example .env && echo "Created .env from .env.example")

setup: env models
	docker compose up -d --build
	docker compose exec backend python manage.py migrate

models: env
	@set -a; . ./.env; set +a; \
	pulled=""; \
	for model in "$${EMBEDDING_MODEL:-qwen3-embedding:0.6b}" "$${LLM_MODEL:-hf.co/unsloth/Qwen3-4B-Instruct-2507-GGUF:Q4_K_M}" "$${EVAL_JUDGE_MODEL:-$${LLM_MODEL:-hf.co/unsloth/Qwen3-4B-Instruct-2507-GGUF:Q4_K_M}}"; do \
		case " $$pulled " in \
			*" $$model "*) ;; \
			*) ollama pull "$$model"; pulled="$$pulled $$model";; \
		esac; \
	done

build:
	docker compose build

up:
	docker compose up -d

down:
	docker compose down

migrate:
	docker compose exec backend python manage.py makemigrations
	docker compose exec backend python manage.py migrate

test:
	docker compose exec -T -e LOCALDOC_REQUIRE_CPP=1 backend pytest -c /pyproject.toml /app /tests -v

lint:
	docker compose exec backend ruff check .
	docker compose exec -T backend ruff check /scripts /tests
	npm --prefix frontend run lint

format:
	docker compose exec backend black .
	docker compose exec backend ruff check . --fix
	npm --prefix frontend run format

# Read-only formatting check for pre-release verification.
format-check:
	docker compose exec -T backend black --check /app /scripts /tests

# Fails when a model change has no matching migration.
migration-check:
	docker compose exec -T backend python manage.py makemigrations --check --dry-run

# Fails when any published Compose port is reachable from outside the host.
ports-check:
	python3 scripts/check_compose_ports.py
	python3 scripts/check_compose_ports.py -f docker-compose.yml -f compose.smoke.yml
	python3 scripts/check_compose_ports.py -f docker-compose.yml -f compose.prod.yml
	python3 scripts/check_compose_ports.py -f docker-compose.yml -f compose.prod.yml -f compose.offline.yml

# Fails when a service would send vendor telemetry with its default settings.
privacy-check:
	python3 scripts/check_privacy_defaults.py
	python3 scripts/check_privacy_defaults.py -f docker-compose.yml -f compose.smoke.yml
	python3 scripts/check_privacy_defaults.py -f docker-compose.yml -f compose.prod.yml
	python3 scripts/check_privacy_defaults.py -f docker-compose.yml -f compose.prod.yml -f compose.offline.yml

# Fails when the version differs between project metadata and the API.
version-check:
	python3 scripts/check_version_sync.py

check: lint format-check migration-check ports-check privacy-check version-check cpp-test frontend-audit frontend-test frontend-build test

# Local release gate: make check plus both images, the packaged suite, and the
# isolated smoke stack. No target pulls a model or runs inference.
release-check: isolation-check check images packaged-test smoke-isolated prod-images offline-check

dev: env backend-up frontend-dev

launch: env
	docker compose up -d --build backend celery frontend
	@$(MAKE) wait-backend-container
	docker compose exec -T backend python manage.py migrate --noinput
	@$(MAKE) wait-frontend
	@$(MAKE) wait-proxy
	@$(MAKE) launch-open

wait: wait-backend wait-frontend wait-proxy

wait-backend-container:
	@echo "Waiting for backend container readiness"; \
	ready=""; \
	attempt=0; \
	while [ "$$attempt" -lt "$(LOCALDOC_WAIT_ATTEMPTS)" ]; do \
		if docker compose exec -T backend python manage.py check >/dev/null 2>&1; then ready="yes"; break; fi; \
		attempt=$$((attempt + 1)); sleep 1; \
	done; \
	if [ "$$ready" != "yes" ]; then \
		echo "Backend container did not become ready. Check logs with: docker compose logs backend" >&2; \
		exit 1; \
	fi; \
	echo "Backend container is ready."

wait-backend:
	@url="$${LOCALDOC_BACKEND_HEALTH_URL:-http://localhost:8000/api/health/}"; \
	echo "Waiting for backend at $$url"; \
	ready=""; \
	attempt=0; \
	while [ "$$attempt" -lt "$(LOCALDOC_WAIT_ATTEMPTS)" ]; do \
		if curl --connect-timeout 2 --max-time 5 -fsS "$$url" >/dev/null 2>&1; then ready="yes"; break; fi; \
		attempt=$$((attempt + 1)); sleep 1; \
	done; \
	if [ "$$ready" != "yes" ]; then \
		echo "Backend did not become ready at $$url. Check logs with: docker compose logs backend" >&2; \
		exit 1; \
	fi; \
	echo "Backend is ready."

wait-frontend:
	@url="$${LOCALDOC_FRONTEND_URL:-http://localhost:3000}"; \
	echo "Waiting for frontend at $$url"; \
	ready=""; \
	attempt=0; \
	while [ "$$attempt" -lt "$(LOCALDOC_WAIT_ATTEMPTS)" ]; do \
		if curl --connect-timeout 2 --max-time 5 -fsS "$$url" >/dev/null 2>&1; then ready="yes"; break; fi; \
		attempt=$$((attempt + 1)); sleep 1; \
	done; \
	if [ "$$ready" != "yes" ]; then \
		echo "Frontend did not become ready at $$url. Check logs with: docker compose logs frontend" >&2; \
		exit 1; \
	fi; \
	echo "Frontend is ready."

wait-proxy:
	@url="$${LOCALDOC_FRONTEND_BACKEND_HEALTH_URL:-http://localhost:3000/api/backend/health}"; \
	echo "Waiting for frontend backend proxy at $$url"; \
	ready=""; \
	attempt=0; \
	while [ "$$attempt" -lt "$(LOCALDOC_WAIT_ATTEMPTS)" ]; do \
		if curl --connect-timeout 2 --max-time 5 -fsS "$$url" >/dev/null 2>&1; then ready="yes"; break; fi; \
		attempt=$$((attempt + 1)); sleep 1; \
	done; \
	if [ "$$ready" != "yes" ]; then \
		echo "Frontend backend proxy did not become ready at $$url. Check logs with: docker compose logs frontend backend" >&2; \
		exit 1; \
	fi; \
	echo "Frontend backend proxy is ready."

launch-open:
	@url="$${LOCALDOC_FRONTEND_URL:-http://localhost:3000}"; \
	echo "Opening $$url"; \
	if command -v open >/dev/null 2>&1; then \
		open "$$url"; \
	elif command -v xdg-open >/dev/null 2>&1; then \
		xdg-open "$$url"; \
	elif command -v cmd.exe >/dev/null 2>&1; then \
		cmd.exe /C start "$$url"; \
	else \
		echo "Open $$url in your browser."; \
	fi

backend-up:
	docker compose up -d backend celery

frontend-dev:
	NEXT_TELEMETRY_DISABLED=1 npm --prefix frontend run dev

frontend-test:
	NEXT_TELEMETRY_DISABLED=1 npm --prefix frontend run test

frontend-lint:
	NEXT_TELEMETRY_DISABLED=1 npm --prefix frontend run lint

frontend-format:
	npm --prefix frontend run format

frontend-build:
	NEXT_TELEMETRY_DISABLED=1 npm --prefix frontend run build

# Reinstalls frontend/node_modules exactly from the committed lockfile.
frontend-ci:
	npm --prefix frontend ci

# Blocking: fails when a runtime dependency has a high or critical advisory.
# Needs network access to the npm registry.
frontend-audit:
	npm --prefix frontend audit --omit=dev --audit-level=high

isolation-check:
	python3 scripts/check_release_isolation.py

images:
	docker build -f backend/Dockerfile -t localdoc-intel-backend:$(LOCALDOC_RELEASE_TAG) .
	docker build -f frontend/Dockerfile -t localdoc-intel-frontend:$(LOCALDOC_RELEASE_TAG) frontend

# Complete backend and root suite inside the built image, real C++ binary required.
packaged-test:
	docker run --rm -w /app -e LOCALDOC_REQUIRE_CPP=1 localdoc-intel-backend:$(LOCALDOC_RELEASE_TAG) \
		pytest -c /pyproject.toml /app /tests -q -p no:cacheprovider

# Runtime images for everyday use: no test tooling, no source mounts.
prod-images:
	docker build -f backend/Dockerfile --target runtime -t localdoc-intel-backend-runtime:$(LOCALDOC_RELEASE_TAG) .
	docker build -f frontend/Dockerfile --target runner -t localdoc-intel-frontend-runtime:$(LOCALDOC_RELEASE_TAG) frontend

# Everyday-use stack on the runtime images. Stop the development stack first:
# both publish 127.0.0.1:3000 and 127.0.0.1:8000.
prod-up: env prod-images
	$(PROD_COMPOSE) up -d --no-build backend celery frontend
	@set -e; \
	echo "Waiting for the runtime backend"; \
	attempt=0; \
	until curl --connect-timeout 2 --max-time 5 -fsS http://127.0.0.1:8000/api/health/ >/dev/null 2>&1; do \
		attempt=$$((attempt + 1)); \
		if [ "$$attempt" -ge "$(LOCALDOC_WAIT_ATTEMPTS)" ]; then $(PROD_COMPOSE) logs --tail 100 backend; exit 1; fi; \
		sleep 1; \
	done; \
	$(PROD_COMPOSE) exec -T backend python manage.py migrate --noinput; \
	echo "Waiting for the runtime frontend and its backend proxy"; \
	attempt=0; \
	until curl --connect-timeout 2 --max-time 5 -fsS http://127.0.0.1:3000/api/backend/health >/dev/null 2>&1; do \
		attempt=$$((attempt + 1)); \
		if [ "$$attempt" -ge "$(LOCALDOC_WAIT_ATTEMPTS)" ]; then $(PROD_COMPOSE) logs --tail 100 frontend backend; exit 1; fi; \
		sleep 1; \
	done; \
	echo "Runtime stack ready on http://127.0.0.1:3000"

prod-down:
	$(PROD_COMPOSE) down

prod-logs:
	$(PROD_COMPOSE) logs --tail 100 -f

# Offline proof: the runtime images on an internal network with no route off
# the host. Default mode keeps model features off. MODELS=live adds the
# containerized Ollama and requires an embedded, retrieved, cited answer.
# REPORT=<path> writes a JSON report. The stack is removed on exit.
offline-check: env prod-images
	@trap '$(OFFLINE_ENV) $(OFFLINE_COMPOSE) $(OFFLINE_PROFILE) down -v --remove-orphans >/dev/null 2>&1' EXIT; \
	set -e; \
	$(OFFLINE_ENV) $(OFFLINE_COMPOSE) $(OFFLINE_PROFILE) up -d --no-build; \
	echo "Waiting for the offline backend container"; \
	attempt=0; \
	until $(OFFLINE_ENV) $(OFFLINE_COMPOSE) exec -T backend python manage.py check >/dev/null 2>&1; do \
		attempt=$$((attempt + 1)); \
		if [ "$$attempt" -ge "$(LOCALDOC_WAIT_ATTEMPTS)" ]; then $(OFFLINE_ENV) $(OFFLINE_COMPOSE) logs --tail 100 backend; exit 1; fi; \
		sleep 1; \
	done; \
	$(OFFLINE_ENV) $(OFFLINE_COMPOSE) exec -T backend python manage.py migrate --noinput; \
	python3 scripts/offline_check.py --mode $(MODELS) $(if $(REPORT),--json $(REPORT)) \
		|| { $(OFFLINE_ENV) $(OFFLINE_COMPOSE) logs --tail 200; exit 1; }

# End-to-end smoke test on the separate localdoc-smoke project (see
# compose.smoke.yml). The stack and its volumes are removed on exit.
smoke-isolated: env images
	@trap '$(SMOKE_COMPOSE) down -v --remove-orphans >/dev/null 2>&1' EXIT; \
	set -e; \
	$(SMOKE_COMPOSE) up -d --no-build backend frontend; \
	echo "Waiting for isolated backend container readiness"; \
	attempt=0; \
	until $(SMOKE_COMPOSE) exec -T backend python manage.py check >/dev/null 2>&1; do \
		attempt=$$((attempt + 1)); \
		if [ "$$attempt" -ge "$(LOCALDOC_WAIT_ATTEMPTS)" ]; then $(SMOKE_COMPOSE) logs --tail 100 backend; exit 1; fi; \
		sleep 1; \
	done; \
	$(SMOKE_COMPOSE) exec -T backend python manage.py migrate --noinput; \
	wait_url() { \
		echo "Waiting for $$1"; \
		attempt=0; \
		until curl --connect-timeout 2 --max-time 5 -fsS "$$1" >/dev/null 2>&1; do \
			attempt=$$((attempt + 1)); \
			if [ "$$attempt" -ge "$(LOCALDOC_WAIT_ATTEMPTS)" ]; then $(SMOKE_COMPOSE) logs --tail 100 backend frontend; exit 1; fi; \
			sleep 1; \
		done; \
	}; \
	wait_url http://127.0.0.1:3900; \
	wait_url http://127.0.0.1:3900/api/backend/health; \
	python3 scripts/smoke_test.py --base-url http://127.0.0.1:3900 \
		|| { $(SMOKE_COMPOSE) logs --tail 200 backend frontend; exit 1; }

backend-dev:
	cd backend && python manage.py runserver 0.0.0.0:8000

cpp-build:
	@if command -v cmake >/dev/null 2>&1; then \
		cmake -S cpp/chunker -B cpp/chunker/build -DCMAKE_BUILD_TYPE=Release; \
		cmake --build cpp/chunker/build --config Release; \
	else \
		echo "cmake not found; compiling C++ chunker directly"; \
		mkdir -p cpp/chunker/build; \
		$(CXX) -O2 -std=c++17 -Wall -Wextra -Wpedantic -o cpp/chunker/build/localdoc_chunker cpp/chunker/src/main.cpp; \
	fi

cpp-test: cpp-build
	@if command -v ctest >/dev/null 2>&1 && test -f cpp/chunker/build/CTestTestfile.cmake; then \
		ctest --test-dir cpp/chunker/build --output-on-failure; \
	else \
		python3 cpp/chunker/tests/validate_output.py \
			cpp/chunker/build/localdoc_chunker \
			cpp/chunker/tests/sample_input.txt; \
	fi

# Ingest the small redistributable corpus used by the published results table.
eval-corpus: env
	docker compose exec -T backend python manage.py ingest_eval_corpus

# Run the default hybrid configuration against the redistributable corpus.
eval-published: env
	docker compose exec -T -e LOCALDOC_REVISION="$$(git rev-parse --short HEAD 2>/dev/null)" \
		backend python manage.py run_eval \
		--questions /data/eval_questions.json --collection "Eval Corpus" \
		--mode hybrid --top-k 5 --retrieval-only

demo-data: env
	docker compose run --rm --no-deps --build backend python manage.py download_demo_data

ingest-demo: env
	docker compose exec -T backend python manage.py ingest_demo

eval:
	docker compose exec -T -e LOCALDOC_REVISION="$$(git rev-parse --short HEAD 2>/dev/null)" \
		backend python manage.py run_eval

# Retrieval metrics only (no LLM generation/judging) — runs in seconds.
eval-fast:
	docker compose exec -T -e LOCALDOC_REVISION="$$(git rev-parse --short HEAD 2>/dev/null)" \
		backend python manage.py run_eval --retrieval-only

# End-to-end smoke test through the frontend proxy: upload a file, confirm the
# chunks persisted, and confirm an unrelated question returns no passages.
# Uses only local services already started by make launch.
smoke:
	python3 scripts/smoke_test.py

# reset: clear caches and intermediate build artifacts, then restart the app.
# Keeps containers' volumes (Postgres/Qdrant data), demo intake files, node_modules,
# and .env — use it to get a fresh start after debugging or code changes.
reset:
	@echo "Clearing caches and intermediate files (keeps data, volumes, and .env)"
	find . \( -path "./frontend/node_modules" -o -path "./.git" -o -path "./.venv" -o -path "./data" \) -prune -o -type d \( -name "__pycache__" -o -name ".pytest_cache" -o -name ".ruff_cache" -o -name ".mypy_cache" -o -name ".cache" -o -name "htmlcov" \) -prune -exec rm -rf {} +
	find backend scripts -type f \( -name "*.pyc" -o -name "*.pyo" -o -name ".coverage" \) -delete
	rm -rf frontend/.next frontend/dist frontend/build frontend/coverage
	rm -rf cpp/chunker/build
	find backend/staticfiles -mindepth 1 -not -name ".gitkeep" -delete 2>/dev/null || true
	-docker compose up -d backend celery frontend

# clean: DESTRUCTIVE local reset, not a release step. Deletes everything reset
# deletes PLUS containers and their volumes (all Postgres and Qdrant data),
# installed node_modules, demo intake/external data, media uploads, local
# databases, and your .env. Ingested documents and evaluation history are gone.
# It is not needed for a clean Git diff or a release; use it only to rebuild the
# local environment from scratch: make setup && make demo-data
clean:
	@echo "DESTRUCTIVE: deletes containers, volumes (Postgres/Qdrant data), caches, builds, demo data, media, and .env"
	@printf "Type 'delete' to continue: "; read answer; [ "$$answer" = "delete" ] || (echo "Aborted."; exit 1)
	-docker compose down -v --remove-orphans
	find . \( -path "./frontend/node_modules" -o -path "./.git" -o -path "./.venv" \) -prune -o -type d \( -name "__pycache__" -o -name ".pytest_cache" -o -name ".ruff_cache" -o -name ".mypy_cache" -o -name ".cache" -o -name "htmlcov" \) -prune -exec rm -rf {} +
	find backend scripts -type f \( -name "*.pyc" -o -name "*.pyo" -o -name ".coverage" \) -delete
	rm -rf frontend/.next frontend/dist frontend/build frontend/coverage frontend/node_modules
	rm -rf cpp/chunker/build
	rm -rf backend/media backend/db.sqlite3 localdoc_intel.egg-info
	rm -rf models model_cache embeddings vector_store chroma_db
	find backend/staticfiles -mindepth 1 -not -name ".gitkeep" -delete 2>/dev/null || true
	find data/demo_intake -mindepth 1 -delete 2>/dev/null || true
	find data/external -mindepth 1 -delete 2>/dev/null || true
	find . -name ".DS_Store" -not -path "./.git/*" -delete 2>/dev/null || true
	rm -f .env
