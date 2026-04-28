# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# fonts-dejavu-core for mission-card composition (Pillow needs a TTF on disk)
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY src ./src

# ----- prod stage (default; lean, no dev deps, no tests) -----
FROM base AS prod
RUN uv sync --frozen --no-dev
COPY alembic.ini ./alembic.ini
COPY alembic ./alembic
COPY frontend ./frontend
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
CMD ["uvicorn", "dispatchzero.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]

# ----- test stage (includes dev deps + tests/) -----
FROM base AS test
RUN uv sync --frozen
COPY alembic.ini ./alembic.ini
COPY alembic ./alembic
COPY frontend ./frontend
COPY tests ./tests
ENV PATH="/app/.venv/bin:$PATH"
CMD ["pytest", "-v"]
