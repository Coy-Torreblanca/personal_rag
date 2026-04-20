"""Custom exceptions for S3/R2 operations."""


class S3Error(Exception):
    """Base exception for S3 operations."""
    pass


class R2Error(Exception):
    """Base exception for R2 operations."""
    pass


class ConfigurationError(S3Error, R2Error):
    """Raised when configuration is invalid."""
    pass


class BucketError(S3Error, R2Error):
    """Raised when bucket operations fail."""
    pass


class FileNotFoundError(S3Error, R2Error):
    """Raised when a file is not found in storage."""
    pass


class UploadError(S3Error, R2Error):
    """Raised when file upload fails."""
    pass


class DownloadError(S3Error, R2Error):
    """Raised when file download fails."""
    pass


class DeleteError(S3Error, R2Error):
    """Raised when file deletion fails."""
    pass


class ListError(S3Error, R2Error):
    """Raised when listing files fails."""
    pass


class PresignedUrlError(S3Error, R2Error):
    """Raised when generating presigned URLs fails."""
    pass