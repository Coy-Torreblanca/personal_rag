"""Main FastAPI application for DocParse."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .models import ErrorResponse, HealthResponse, ParseRequest, ParseResponse
from .providers import BaseProvider, get_provider

# Configure logging
logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)

# Global provider instance
provider: BaseProvider | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    global provider

    # Startup
    logger.info("Starting DocParse application")
    try:
        provider = get_provider()
        logger.info(f"Provider initialized: {settings.docparse_provider}")
        logger.info(f"Supported formats: {', '.join(provider.get_supported_formats())}")
    except Exception as e:
        logger.error(f"Failed to initialize provider: {str(e)}")
        raise

    yield

    # Shutdown
    logger.info("Shutting down DocParse application")


# Create FastAPI application
app = FastAPI(
    title=settings.api_title,
    description=settings.api_description,
    version=settings.api_version,
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    description="Check the health status of the DocParse service",
)
async def health_check() -> HealthResponse:
    """Health check endpoint."""
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Provider not initialized",
        )

    return HealthResponse(
        status="healthy",
        provider=settings.docparse_provider,
        supported_formats=provider.get_supported_formats(),
    )


@app.post(
    "/parse",
    response_model=ParseResponse,
    responses={
        404: {"model": ErrorResponse, "description": "File not found"},
        400: {"model": ErrorResponse, "description": "Invalid file format"},
        500: {"model": ErrorResponse, "description": "Parsing error"},
    },
    summary="Parse document",
    description="Parse a document and return its content in markdown format",
)
async def parse_document(request: ParseRequest) -> ParseResponse:
    """
    Parse a document and return markdown content.

    Args:
        request: ParseRequest containing the S3 presigned URL

    Returns:
        ParseResponse with markdown content and S3 presigned URL

    Raises:
        HTTPException: If URL is invalid, format not supported, or parsing fails
    """
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Provider not initialized",
        )

    url = request.s3_presigned_http_url
    try:
        markdown_content = await provider.parse_document(url)

        return ParseResponse(markdown=markdown_content, s3_presigned_http_url=url)

    except FileNotFoundError as e:
        logger.error(f"Document not found at S3 URL: {url}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )

    except ValueError as e:
        logger.error(f"Invalid document format from S3 URL: {url}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    except Exception as e:
        logger.error(f"Error parsing document: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to parse document: {str(e)}",
        )


@app.get(
    "/",
    summary="API information",
    description="Get basic information about the DocParse API",
)
async def root():
    """Root endpoint with API information."""
    return {
        "name": settings.api_title,
        "version": settings.api_version,
        "description": settings.api_description,
        "endpoints": {
            "health": "/health",
            "parse": "/parse",
            "docs": "/docs",
        },
    }
