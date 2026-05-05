# ──────────────────────────────────────────────
# Stage 1: Builder
# ──────────────────────────────────────────────
FROM python:3.12-alpine AS builder

WORKDIR /build

# Install build dependencies for asyncpg (Cython) and cryptography
RUN apk add --no-cache gcc musl-dev libffi-dev openssl-dev python3-dev

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# ──────────────────────────────────────────────
# Stage 2: Runtime
# ──────────────────────────────────────────────
FROM python:3.12-alpine AS runtime

# Non-root user for security
RUN addgroup -S appgroup && adduser -S appuser -G appgroup

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /build/.venv /app/.venv

# Copy application source
COPY app/ ./app/
COPY utils/ ./utils/
COPY alembic/ ./alembic/
COPY alembic.ini .

# Ensure non-root ownership
RUN chown -R appuser:appgroup /app

USER appuser

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
