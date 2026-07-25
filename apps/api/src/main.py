from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .auth_routes import router as auth_router
from .document_routes import router as document_router

from logutil import get_logger, setup_logging, add_logging_middleware

# Configure structured logging
setup_logging()
logger = get_logger(__name__)

logger.info("Starting 30ai API server")

app = FastAPI(
    title="30ai API",
    description="AI-powered business intelligence platform",
    version="0.1.0",
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # Frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add request logging middleware
add_logging_middleware(app)

# Include routers
app.include_router(auth_router)
app.include_router(document_router)


@app.get("/")
def read_root():
    """Root endpoint."""
    logger.info("Root endpoint called")
    return {"message": "Welcome to 30ai API"}


@app.get("/health")
def health_check():
    """Health check endpoint."""
    logger.debug("Health check endpoint called")
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn

    logger.info("Running uvicorn server on 0.0.0.0:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)
