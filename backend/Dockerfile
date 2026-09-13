# Stage 1: build the C++ offset chunker for the container's own platform.
# A macOS-built binary from the host cannot run inside the Linux image, and
# the bind-mounted cpp/ directory of a fresh clone has no build artifact.
FROM python:3.14-slim AS chunker-build

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential cmake \
    && rm -rf /var/lib/apt/lists/*

COPY cpp/chunker /src/chunker
RUN cmake -S /src/chunker -B /build -DCMAKE_BUILD_TYPE=Release \
    && cmake --build /build --config Release \
    && ctest --test-dir /build --output-on-failure

# Stage 2: the runtime image for everyday use. Runtime dependencies only:
# no test or lint tooling, no compiler, no source mounts, and a non-root user.
FROM python:3.14-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=config.settings \
    LOCALDOC_CHUNKER_PATH=/usr/local/bin/localdoc_chunker

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        poppler-utils \
        tesseract-ocr \
        tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml /tmp/localdoc-intel/pyproject.toml
WORKDIR /tmp/localdoc-intel
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir "."

# Install the chunker outside the /app and /cpp bind mounts so development
# volumes never hide it.
COPY --from=chunker-build /build/localdoc_chunker /usr/local/bin/localdoc_chunker

WORKDIR /app
COPY backend /app
COPY data/demo_questions.json data/eval_questions.json /data/
COPY data/eval_corpus /data/eval_corpus

# Collect static files during the build so the container needs no write access
# to the image, and create the upload directory the runtime user owns.
RUN python manage.py collectstatic --noinput \
    && useradd --create-home --uid 10001 localdoc \
    && mkdir -p /app/media \
    && chown -R localdoc:localdoc /app/media /data

EXPOSE 8000
USER localdoc
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", \
     "--workers", "3", "--timeout", "120", "--access-logfile", "-"]

# Stage 3: the development and test image, and the default build target.
# It adds the dev dependencies, the project layout pytest expects, and the
# release-check scripts and tests.
FROM runtime AS dev

USER root
COPY pyproject.toml /tmp/localdoc-intel/pyproject.toml
WORKDIR /tmp/localdoc-intel
RUN pip install --no-cache-dir -e ".[dev]"

WORKDIR /app

# Preserve the project layout for pytest and the root release-check tests.
# /app remains the development bind mount; /backend is its project-root alias.
COPY pyproject.toml package.json /
COPY frontend/package.json frontend/package-lock.json /frontend/
COPY scripts /scripts
COPY tests /tests
RUN ln -s /app /backend

EXPOSE 8000
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
