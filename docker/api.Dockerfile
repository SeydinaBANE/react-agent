# Stage 1 — deps: install only dependencies (cached independently of src/)
FROM python:3.12-slim AS deps

WORKDIR /app
RUN pip install --no-cache-dir uv==0.10.0
COPY pyproject.toml uv.lock* README.md ./

# Install deps without the local package (src not available yet)
# --no-install-project skips building the react-agent wheel
RUN uv sync --frozen --no-dev --no-install-project

# Stage 2 — builder: add source and build the package wheel
FROM deps AS builder

COPY src/ src/
RUN uv sync --frozen --no-dev --no-editable

# Stage 3 — runtime: minimal image, pre-warm fastembed, non-root user
FROM python:3.12-slim AS runtime

WORKDIR /app

# Copy virtual environment from builder (includes installed package + deps)
COPY --from=builder /app/.venv .venv
COPY config/ config/

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FASTEMBED_CACHE_PATH=/app/.fastembed_cache

# Pre-download fastembed ONNX model (~66 MB) — run as root, chown later
# This layer is cached as long as the model version doesn't change
RUN python -c "from fastembed import TextEmbedding; list(TextEmbedding('BAAI/bge-small-en-v1.5').embed(['warmup']))"

# Create non-root user and fix permissions in one layer
RUN groupadd --system appgroup \
    && useradd --system --gid appgroup --no-create-home appuser \
    && chown -R appuser:appgroup /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import httpx; httpx.get('http://localhost:8000/health').raise_for_status()"

CMD ["uvicorn", "agent.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
