FROM python:3.11-slim as builder

WORKDIR /app

# Install uv for fast dependency management
RUN pip install uv

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install dependencies
RUN uv sync --frozen --no-dev

# Production stage
FROM python:3.11-slim

WORKDIR /app

# Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser appuser

# Install system dependencies for AI libraries
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Copy Python dependencies from builder
COPY --from=builder /app/.venv .venv
ENV PATH="/app/.venv/bin:$PATH"

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p /app/logs && chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD celery -A src.main.celery inspect ping -d celery@$HOSTNAME || exit 1

# Run Celery worker
CMD ["celery", "-A", "src.main.celery", "worker", "--loglevel=info"]