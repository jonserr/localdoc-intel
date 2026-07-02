.PHONY: setup build up down migrate test lint format check dev launch wait wait-backend wait-backend-container wait-frontend wait-proxy launch-open backend-up frontend-dev frontend-test frontend-lint frontend-format frontend-build backend-dev cpp-build cpp-test demo-data ingest-demo eval eval-fast models env reset clean
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
	docker compose exec backend pytest -v

lint:
	docker compose exec backend ruff check .
	npm --prefix frontend run lint

format:
	docker compose exec backend black .
	docker compose exec backend ruff check . --fix
	npm --prefix frontend run format

check: lint frontend-test frontend-build test

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
	for attempt in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31 32 33 34 35 36 37 38 39 40 41 42 43 44 45 46 47 48 49 50 51 52 53 54 55 56 57 58 59 60; do \
		if docker compose exec -T backend python manage.py check >/dev/null 2>&1; then ready="yes"; break; fi; \
		sleep 1; \
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
	for attempt in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31 32 33 34 35 36 37 38 39 40 41 42 43 44 45 46 47 48 49 50 51 52 53 54 55 56 57 58 59 60; do \
		if curl -fsS "$$url" >/dev/null 2>&1; then ready="yes"; break; fi; \
		sleep 1; \
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
	for attempt in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31 32 33 34 35 36 37 38 39 40 41 42 43 44 45 46 47 48 49 50 51 52 53 54 55 56 57 58 59 60; do \
		if curl -fsS "$$url" >/dev/null 2>&1; then ready="yes"; break; fi; \
		sleep 1; \
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
	for attempt in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31 32 33 34 35 36 37 38 39 40 41 42 43 44 45 46 47 48 49 50 51 52 53 54 55 56 57 58 59 60; do \
		if curl -fsS "$$url" >/dev/null 2>&1; then ready="yes"; break; fi; \
		sleep 1; \
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
	npm --prefix frontend run dev

frontend-test:
	npm --prefix frontend run test

frontend-lint:
	npm --prefix frontend run lint

frontend-format:
	npm --prefix frontend run format

frontend-build:
	npm --prefix frontend run build

backend-dev:
	cd backend && python manage.py runserver 0.0.0.0:8000

cpp-build:
	cmake -S cpp/chunker -B cpp/chunker/build
	cmake --build cpp/chunker/build

cpp-test: cpp-build
	ctest --test-dir cpp/chunker/build --output-on-failure

demo-data: env
	docker compose run --rm --no-deps --build backend python manage.py download_demo_data

ingest-demo: env
	docker compose exec -T backend python manage.py ingest_demo

eval:
	docker compose exec -T backend python manage.py run_eval

# Retrieval metrics only (no LLM generation/judging) — runs in seconds.
eval-fast:
	docker compose exec -T backend python manage.py run_eval --retrieval-only

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

# clean: return the repository to a pristine, push-ready state. Removes everything
# reset removes PLUS containers and their volumes (Postgres/Qdrant data), installed
# node_modules, demo intake/external data, media uploads, local databases, and .env.
# Recreate the local environment afterwards with: make setup && make demo-data
clean:
	@echo "Full cleanup: containers, volumes, caches, builds, demo data, and .env"
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
