# Stage 1 — builder: install dependencies with uv
FROM python:3.12-slim AS builder

WORKDIR /app

# Install uv for fast dependency resolution
RUN pip install --no-cache-dir uv==0.10.0

# Copy only dependency files first (layer cache optimization)
COPY pyproject.toml uv.lock* ./

# Install production dependencies only, no editable install
RUN uv sync --frozen --no-dev --no-editable

# Stage 2 — runtime: minimal image, non-root user
FROM python:3.12-slim AS runtime

# Create non-root user before copying anything
RUN groupadd --system appgroup \
    && useradd --system --gid appgroup --no-create-home appuser

WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder /app/.venv .venv

# Copy application source and config
COPY src/ src/
COPY config/ config/

# Set ownership (single layer)
RUN chown -R appuser:appgroup /app

USER appuser

# Add venv to PATH
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import httpx; httpx.get('http://localhost:8000/health').raise_for_status()"

CMD ["uvicorn", "agent.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
