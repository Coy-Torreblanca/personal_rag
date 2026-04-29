FROM python:3.11-slim as builder

WORKDIR /app

# Install uv for fast dependency management
RUN pip install uv

# Copy the entire project structure to maintain relative paths
COPY apps/api apps/api
COPY packages packages

# Install dependencies from the api directory
# CRITICAL FIX: Force uv to copy files, not symlink them to a cache
ENV UV_LINK_MODE=copy
# Best practice: pre-compile python to bytecode for faster startup
ENV UV_COMPILE_BYTECODE=1
RUN cd apps/api && uv sync --frozen --no-dev

# Production stage
FROM python:3.11-slim

WORKDIR /app

# Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser appuser

# Copy Python dependencies from builder
COPY --from=builder /app/apps/api/.venv .venv
ENV PATH="/app/.venv/bin:$PATH"
ENV VIRTUAL_ENV="/app/.venv"
ENV PYTHONUNBUFFERED=1

# Copy application code
COPY apps/api/src ./src

# Create necessary directories
RUN mkdir -p /app/logs && chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run the application
CMD ["python", "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
