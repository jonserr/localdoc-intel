import sys
from pathlib import Path

import environ

from config.resources import runtime_profile

BASE_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = BASE_DIR.parent
RUNTIME_PROFILE = runtime_profile()

# Keep automated tests hermetic: a developer's .env (which may enable vector
# search, generation, or point at live services) must not leak into pytest.
# Explicit environment variables (CI, Docker env_file) still take effect.
RUNNING_TESTS = "pytest" in sys.modules

env = environ.Env(
    DJANGO_DEBUG=(bool, False),
    DJANGO_ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
    QDRANT_VECTOR_SIZE=(int, 1024),
    VECTOR_INDEXING_ENABLED=(bool, False),
    VECTOR_SEARCH_ENABLED=(bool, False),
    ANSWER_GENERATION_ENABLED=(bool, False),
    ASYNC_INDEXING_ENABLED=(bool, False),
    OCR_ENABLED=(bool, True),
    OCR_TIMEOUT_SECONDS=(float, RUNTIME_PROFILE.ocr_timeout_seconds),
    OCR_PDF_DPI=(int, RUNTIME_PROFILE.ocr_pdf_dpi),
    OCR_TESSERACT_PSM=(int, 6),
    INGESTION_MAX_WORKERS=(int, RUNTIME_PROFILE.ingest_max_workers),
    CELERY_WORKER_CONCURRENCY=(int, RUNTIME_PROFILE.celery_concurrency),
    OLLAMA_TIMEOUT_SECONDS=(float, 30.0),
    LLM_TIMEOUT_SECONDS=(float, 120.0),
    LLM_TEMPERATURE=(float, 0.1),
    LLM_MAX_ANSWER_TOKENS=(int, 512),
    EVAL_JUDGE_MAX_TOKENS=(int, 200),
    EVAL_JUDGE_MAX_CONTEXT_CHARS=(int, 4000),
)
if (ROOT_DIR / ".env").exists() and not RUNNING_TESTS:
    env.read_env(ROOT_DIR / ".env")

SECRET_KEY = env("DJANGO_SECRET_KEY", default="localdoc-dev-secret")
DEBUG = env("DJANGO_DEBUG")
ALLOWED_HOSTS = env("DJANGO_ALLOWED_HOSTS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "documents",
    "retrieval",
    "chat",
    "evaluations",
    "users",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": env.db(
        "DATABASE_URL",
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
    )
}

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.MultiPartParser",
        "rest_framework.parsers.FormParser",
    ],
}

REDIS_URL = env("REDIS_URL", default="redis://localhost:6379/0")
QDRANT_URL = env("QDRANT_URL", default="http://localhost:6333")
QDRANT_COLLECTION = env("QDRANT_COLLECTION", default="localdoc_chunks")
QDRANT_VECTOR_SIZE = env("QDRANT_VECTOR_SIZE")
OLLAMA_BASE_URL = env("OLLAMA_BASE_URL", default="http://localhost:11434")
OLLAMA_TIMEOUT_SECONDS = env("OLLAMA_TIMEOUT_SECONDS")

# Local models. Defaults are Hugging Face-sourced models served through
# Ollama; override in .env to swap models without code changes.
# - Embeddings: Qwen/Qwen3-Embedding-0.6B (1024-dim, Apache-2.0)
# - LLM: Qwen/Qwen3-4B-Instruct-2507, GGUF pulled directly from Hugging Face
EMBEDDING_MODEL = env("EMBEDDING_MODEL", default="qwen3-embedding:0.6b")
LLM_MODEL = env(
    "LLM_MODEL",
    default="hf.co/unsloth/Qwen3-4B-Instruct-2507-GGUF:Q4_K_M",
)
EVAL_JUDGE_MODEL = env("EVAL_JUDGE_MODEL", default=LLM_MODEL)
LLM_TIMEOUT_SECONDS = env("LLM_TIMEOUT_SECONDS")
LLM_TEMPERATURE = env("LLM_TEMPERATURE")
# Response-length caps keep local inference latency predictable; raise them in
# .env if you want longer answers or judge rationales.
LLM_MAX_ANSWER_TOKENS = env("LLM_MAX_ANSWER_TOKENS")
EVAL_JUDGE_MAX_TOKENS = env("EVAL_JUDGE_MAX_TOKENS")
EVAL_JUDGE_MAX_CONTEXT_CHARS = env("EVAL_JUDGE_MAX_CONTEXT_CHARS")
# How long Ollama keeps models loaded between requests (avoids reload cost).
OLLAMA_KEEP_ALIVE = env("OLLAMA_KEEP_ALIVE", default="10m")
VECTOR_INDEXING_ENABLED = env("VECTOR_INDEXING_ENABLED")
VECTOR_SEARCH_ENABLED = env("VECTOR_SEARCH_ENABLED")
ANSWER_GENERATION_ENABLED = env("ANSWER_GENERATION_ENABLED")
ASYNC_INDEXING_ENABLED = env("ASYNC_INDEXING_ENABLED")
OCR_ENABLED = env("OCR_ENABLED")
OCR_TIMEOUT_SECONDS = env("OCR_TIMEOUT_SECONDS")
OCR_PDF_DPI = env("OCR_PDF_DPI")
OCR_TESSERACT_PSM = env("OCR_TESSERACT_PSM")
INGESTION_MAX_WORKERS = env("INGESTION_MAX_WORKERS")

CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_WORKER_CONCURRENCY = env("CELERY_WORKER_CONCURRENCY")
