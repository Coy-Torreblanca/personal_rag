"""FastAPI application entry point for the 30ai API service.

This module initializes the FastAPI application with:
- CORS middleware configured for the frontend origin
- Routers for authentication and document management
- Health check and root endpoints for service discovery

Environment variables expected:
- DATABASE_URL: PostgreSQL connection string (default: localhost)
- REDIS_URL: Redis connection string for Celery broker (default: localhost)
- BUCKET_NAME: S3/R2 bucket name for document storage
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .auth_routes import router as auth_router
from .document_routes import router as document_router

app = FastAPI(
    title="30ai API",
    description="AI-powered business intelligence platform — document ingestion, processing, and retrieval API",
    version="0.1.0",
)

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
# Restrict origins in production; wildcards allowed here for local development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # Frontend dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(auth_router)
app.include_router(document_router)


@app.get("/")
def read_root() -> dict[str, str]:
    """Root endpoint.

    Returns a welcome message for the API.

    Returns:
        dict: A simple greeting message.
    """
    return {"message": "Welcome to 30ai API"}


@app.get("/health")
def health_check() -> dict[str, str]:
    """Health check endpoint.

    Used by load balancers and orchestrators to verify the service is alive.

    Returns:
        dict: Status indicating the service is healthy.
    """
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
