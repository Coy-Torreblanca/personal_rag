"""API models for DocParse."""

from pydantic import BaseModel, Field


class ParseRequest(BaseModel):
    """Request model for document parsing."""

    file_path: str = Field(
        ...,
        description="Absolute or relative path to the document file",
        examples=["/path/to/document.pdf", "./document.docx"],
    )


class ParseResponse(BaseModel):
    """Response model for document parsing."""

    markdown: str = Field(
        ...,
        description="Document content in markdown format",
    )
    file_path: str = Field(
        ...,
        description="Path to the parsed document",
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
