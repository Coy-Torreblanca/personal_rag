# ==========================================
# STAGE 1: The Builder
# ==========================================
FROM python:3.11-slim as builder

WORKDIR /app

# Install uv for fast dependency management
RUN pip install uv

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install dependencies
# CRITICAL FIX: Force uv to copy files, not symlink them to a cache
ENV UV_LINK_MODE=copy
# Best practice: pre-compile python to bytecode for faster startup
ENV UV_COMPILE_BYTECODE=1
RUN uv sync --frozen --no-dev

# ==========================================
# STAGE 2: Production
# ==========================================
FROM python:3.11-slim

WORKDIR /app

# Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser appuser

# Install system dependencies for AI libraries (if still needed here)
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Copy Python dependencies from the builder stage above
COPY --from=builder /app/.venv /app/.venv

# Set environment variables so Python uses the virtual environment
ENV PATH="/app/.venv/bin:$PATH"
ENV VIRTUAL_ENV="/app/.venv"
ENV PYTHONUNBUFFERED=1

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p /app/logs && chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Health check using the python module flag
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -m celery -A src.main.celery inspect ping -d celery@$HOSTNAME || exit 1

# Run Celery worker using the python module flag
CMD ["/app/.venv/bin/python", "-m", "celery", "-A", "src.main.celery", "worker", "--loglevel=info"]
