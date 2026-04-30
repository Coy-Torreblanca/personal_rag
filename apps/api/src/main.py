import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from database.session import get_db
from .s3_routes import router as s3_router
from .database_routes import router as database_router

# Celery integration
from celery import Celery

# Create Celery application for API
celery = Celery(
    "30ai_api",
    broker=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    backend=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
)

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

# Include routers
app.include_router(s3_router)
app.include_router(database_router)


@app.get("/")
def read_root():
    """Root endpoint."""
    return {"message": "Welcome to 30ai API"}


@app.get("/health")
def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
