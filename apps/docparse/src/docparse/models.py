"""API models for DocParse."""

from pydantic import BaseModel, Field, HttpUrl


class ParseRequest(BaseModel):
    """Request model for document parsing."""

    s3_presigned_http_url: HttpUrl = Field(
        ...,
        description="Presigned URL to download file from S3.",
        examples=["https://bucket.s3.amazonaws.com/document.pdf?AWSAccessKeyId=...", "https://bucket.s3.amazonaws.com/document.docx?AWSAccessKeyId=..."],
    )


class ParseResponse(BaseModel):
    """Response model for document parsing."""

    markdown: str = Field(
        ...,
        description="Document content in markdown format",
    )
    s3_presigned_http_url: HttpUrl = Field(
        ...,
        description="S3 presigned URL of the parsed document",
    )


class ErrorResponse(BaseModel):
    """Error response model."""

    error: str = Field(
        ...,
        description="Error message",
    )
    detail: str | None = Field(
        None,
        description="Additional error details",
    )


class HealthResponse(BaseModel):
    """Health check response model."""

    status: str = Field(
        ...,
        description="Service status",
        examples=["healthy"],
    )
    provider: str = Field(
        ...,
        description="Active document parsing provider",
        examples=["docling"],
    )
    supported_formats: list[str] = Field(
        ...,
        description="List of supported document formats",
    )
