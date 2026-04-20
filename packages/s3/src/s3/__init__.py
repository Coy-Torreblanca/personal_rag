"""30ai R2 package for Cloudflare R2 storage operations."""

from .client import R2Client
from .config import R2Config
from .exceptions import (
    S3Error, ConfigurationError, BucketError, FileNotFoundError,
    UploadError, DownloadError, DeleteError, ListError, PresignedUrlError
)
from .models import (
    FileMetadata, UploadResponse, DownloadResponse, ListResponse,
    DeleteResponse, PresignedUrlResponse, FileType
)
from .factory import create_r2_client
from .utils import (
    guess_content_type, get_file_type_from_extension, generate_key,
    parse_key, validate_file_size, get_file_size, sanitize_filename,
    format_file_size
)

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
    
    # Factory functions
    "create_r2_client",
    
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
