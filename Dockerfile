# syntax=docker/dockerfile:1

# --- build: resolve and install dependencies into an isolated virtualenv ---------------------------
FROM python:3.12-slim AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
COPY pyproject.toml README.md ./
COPY src ./src
COPY eval ./eval
RUN python -m venv /venv && /venv/bin/pip install .

# --- runtime: no build tools, non-root user, writable state confined to one volume -----------------
FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/venv/bin:$PATH" \
    PYTHONPATH=/app \
    SQLITE_DB_PATH=/app/state/support.db \
    CHECKPOINT_DB_PATH=/app/state/checkpoints.db

RUN groupadd --gid 10001 app && useradd --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app
WORKDIR /app
COPY --from=build /venv /venv
COPY src ./src
COPY eval ./eval
COPY scripts ./scripts
COPY data/corpus ./data/corpus
RUN mkdir -p /app/state && chown -R app:app /app/state

USER app
VOLUME ["/app/state"]
EXPOSE 8000

# Liveness only; orchestrators should route traffic on /ready.
HEALTHCHECK --interval=15s --timeout=4s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status == 200 else 1)"

# One worker: conversation locks are in-process and state is SQLite. See README, "Production notes", for scaling out.
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
