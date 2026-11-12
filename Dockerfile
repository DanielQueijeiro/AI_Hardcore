# syntax=docker/dockerfile:1
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app \
    LLM_PROVIDER=heuristic

WORKDIR /app

# Copy packaging metadata and source files
COPY pyproject.toml README.md GLOS* SPEC.md ./
COPY src ./src
COPY data ./data
COPY scripts ./scripts
COPY tests ./tests

# Install runtime and test dependencies
RUN pip install --upgrade pip && \
    pip install ".[dev]"

# Pre-seed the deterministic SQLite store so container startup is instantaneous
RUN python -c "from src.db.support_store import ensure_seeded_database; ensure_seeded_database()"

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)" || exit 1

CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
