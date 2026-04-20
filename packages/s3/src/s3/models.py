"""Data models for S3/R2 operations."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast
from enum import Enum


class FileType(str, Enum):
    """Supported file types."""

    PDF = "pdf"
    DOCX = "docx"
    TXT = "txt"
    CSV = "csv"
    JSON = "json"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    OTHER = "other"


def get_file_type_from_content_type(content_type: str) -> FileType:
    """
    Map a content type string to a FileType enum value.

    Args:
        content_type: The MIME type/content type string

    Returns:
        FileType enum value
    """
    if not content_type:
        return FileType.OTHER

    content_type_lower = content_type.lower()

    # First check exact MIME type mappings (most specific)
    mime_mappings = {
        # PDF
        "application/pdf": FileType.PDF,
        "application/x-pdf": FileType.PDF,
        # Document types
        "application/msword": FileType.DOCX,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": FileType.DOCX,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": FileType.CSV,
        "application/vnd.ms-excel": FileType.CSV,
        # Text types
        "text/plain": FileType.TXT,
        "text/html": FileType.TXT,
        "text/xml": FileType.TXT,
        "text/markdown": FileType.TXT,
        # CSV types
        "text/csv": FileType.CSV,
        "application/csv": FileType.CSV,
        "text/tab-separated-values": FileType.CSV,
        # JSON types
        "application/json": FileType.JSON,
        "text/json": FileType.JSON,
        # Image types
        "image/jpeg": FileType.IMAGE,
        "image/png": FileType.IMAGE,
        "image/gif": FileType.IMAGE,
        "image/webp": FileType.IMAGE,
        "image/svg+xml": FileType.IMAGE,
        "image/bmp": FileType.IMAGE,
        "image/tiff": FileType.IMAGE,
        "image/x-icon": FileType.IMAGE,
        # Audio types
        "audio/mpeg": FileType.AUDIO,
        "audio/wav": FileType.AUDIO,
        "audio/ogg": FileType.AUDIO,
        "audio/webm": FileType.AUDIO,
        "audio/aac": FileType.AUDIO,
        "audio/flac": FileType.AUDIO,
        "audio/x-wav": FileType.AUDIO,
        # Video types
        "video/mp4": FileType.VIDEO,
        "video/webm": FileType.VIDEO,
        "video/ogg": FileType.VIDEO,
        "video/x-msvideo": FileType.VIDEO,
        "video/quicktime": FileType.VIDEO,
        "video/x-matroska": FileType.VIDEO,
    }

    # Check exact match first
    if content_type_lower in mime_mappings:
        return mime_mappings[content_type_lower]

    return FileType.OTHER


@dataclass
class FileMetadata:
    """Metadata for a stored file."""

    key: str
    bucket: str
    size: int
    content_type: str
    last_modified: datetime | None
    etag: str
    file_type: FileType
    metadata: dict[str, str] | None

    @classmethod
    def from_s3_upload_response(
        cls,
        response: dict[str, Any],
        bucket: str,
        content_type: str,
        key: str,
        metadata: dict[str, str] | None,
    ) -> "FileMetadata":
        """Create FileMetadata from S3 response."""
        # Determine file type from content type or extension
        file_type = get_file_type_from_content_type(content_type)

        etag = cast(str, response.get("Etag", ""))
        size = cast(int, response.get("Size", 0))
        file_type = get_file_type_from_content_type(content_type)

        return cls(
            key=key,
            bucket=bucket,
            size=size,
            content_type=content_type,
            etag=etag,
            file_type=file_type,
            last_modified=datetime.now(),
            metadata=metadata,
        )


@dataclass
class UploadResponse:
    """Response from file upload operation."""

    success: bool
    metadata: FileMetadata
    message: str | None = None

    @property
    def key(self) -> str:
        """Get the file key from metadata."""
        return self.metadata.key

    @property
    def bucket(self) -> str:
        """Get the bucket name from metadata."""
        return self.metadata.bucket

    @property
    def etag(self) -> str:
        """Get the ETag from metadata."""
        return self.metadata.etag

    @property
    def size(self) -> int:
        """Get the file size from metadata."""
        return self.metadata.size


@dataclass
class DownloadResponse:
    """Response from file download operation."""

    success: bool
    content: bytes
    metadata: FileMetadata
    message: Optional[str] = None

    @property
    def key(self) -> str:
        """Get the file key from metadata."""
        return self.metadata.key

    @property
    def bucket(self) -> str:
        """Get the bucket name from metadata."""
        return self.metadata.bucket


@dataclass
class ListResponse:
    """Response from file listing operation."""

    success: bool
    bucket: str
    files: List[FileMetadata]
    prefix: Optional[str] = None
    continuation_token: Optional[str] = None
    is_truncated: bool = False
    message: Optional[str] = None


@dataclass
class DeleteResponse:
    """Response from file deletion operation."""

    success: bool
    key: str
    bucket: str
    message: Optional[str] = None


@dataclass
class PresignedUrlResponse:
    """Response from presigned URL generation."""

    success: bool
    key: str
    bucket: str
    url: str
    expires_in: int  # seconds
    method: str  # GET, PUT, etc.
    message: Optional[str] = None

