# Stage 1 — builder: install dependencies with uv
FROM python:3.12-slim AS builder

WORKDIR /app

RUN pip install --no-cache-dir uv==0.10.0

COPY pyproject.toml uv.lock* README.md ./
COPY src/ src/

# Install production dependencies (fastembed = ONNX, no PyTorch/CUDA)
RUN uv sync --frozen --no-dev --no-editable

# Stage 2 — runtime: minimal image, non-root user
FROM python:3.12-slim AS runtime

WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder /app/.venv .venv
COPY config/ config/

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FASTEMBED_CACHE_PATH=/app/.fastembed_cache

# Pre-download fastembed ONNX model as root (avoids /tmp permission issues)
# Model is ~66 MB; cached in image so container starts instantly
RUN python -c "from fastembed import TextEmbedding; list(TextEmbedding('BAAI/bge-small-en-v1.5').embed(['warmup']))"

# Create non-root user and fix all permissions in one layer
RUN groupadd --system appgroup \
    && useradd --system --gid appgroup --no-create-home appuser \
    && chown -R appuser:appgroup /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import httpx; httpx.get('http://localhost:8000/health').raise_for_status()"

CMD ["uvicorn", "agent.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
