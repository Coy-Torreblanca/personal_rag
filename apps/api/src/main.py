import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .s3_routes import router as s3_router
from .auth_routes import router as auth_router
from .document_routes import router as document_router

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
app.include_router(auth_router)
app.include_router(document_router)


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
