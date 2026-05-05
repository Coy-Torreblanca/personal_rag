FROM python:3.13-slim as builder

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

FROM python:3.13-slim

WORKDIR /app/apps/api

# Install group/user
RUN groupadd -r appuser && useradd -r -g appuser appuser

# 1. Copy dependencies
COPY --from=builder /app/apps/api/.venv .venv
COPY --from=builder /app/packages /app/packages

# 2. Copy source code
COPY apps/api/src ./src

# 3. FIX PERMISSIONS (Perform this while still ROOT)
# This grants appuser ownership and ensures everything in bin is executable
RUN chown -R appuser:appuser /app && \
    chmod -R +x .venv/bin/

# Set environment variables
ENV PATH="/app/apps/api/.venv/bin:$PATH"
ENV VIRTUAL_ENV="/app/apps/api/.venv"
ENV PYTHONUNBUFFERED=1

# Now safe to switch
USER appuser

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
