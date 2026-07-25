"""30ai R2 package for Cloudflare R2 storage operations."""

import logging

from .client import R2Client
from .config import R2Config
from .exceptions import (
    S3Error,
    ConfigurationError,
    BucketError,
    FileNotFoundError,
    UploadError,
    DownloadError,
    DeleteError,
    ListError,
    PresignedUrlError,
)
from .models import (
    FileMetadata,
    UploadResponse,
    DownloadResponse,
    ListResponse,
    DeleteResponse,
    PresignedUrlResponse,
    FileType,
)
from .utils import (
    guess_content_type,
    get_file_type_from_extension,
    generate_key,
    parse_key,
    validate_file_size,
    get_file_size,
    sanitize_filename,
    format_file_size,
)

logging.getLogger(__name__).addHandler(logging.NullHandler())

__all__ = [
    # Client
    "R2Client",
    # Configuration
    "R2Config",
    # Exceptions
    "S3Error",
    "ConfigurationError",
    "BucketError",
    "FileNotFoundError",
    "UploadError",
    "DownloadError",
    "DeleteError",
    "ListError",
    "PresignedUrlError",
    # Models
    "FileMetadata",
    "UploadResponse",
    "DownloadResponse",
    "ListResponse",
    "DeleteResponse",
    "PresignedUrlResponse",
    "FileType",
    # Utilities
    "guess_content_type",
    "get_file_type_from_extension",
    "generate_key",
    "parse_key",
    "validate_file_size",
    "get_file_size",
    "sanitize_filename",
    "format_file_size",
]
