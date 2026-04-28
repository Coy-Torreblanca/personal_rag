"""Base provider interface for document parsing."""

from abc import ABC, abstractmethod

from pydantic import HttpUrl


class BaseProvider(ABC):
    """Abstract base class for document parsing providers."""

    @abstractmethod
    async def parse_document(self, s3_presigned_http_url: HttpUrl) -> str:
        """
        Parse a document from S3 and return its content in markdown format.

        Args:
            s3_presigned_http_url: S3 presigned URL to download the document

        Returns:
            Document content in markdown format

        Raises:
            FileNotFoundError: If the document cannot be retrieved from S3
            ValueError: If the document format is not supported
            Exception: For other parsing errors
        """
        pass

    @abstractmethod
    def get_supported_formats(self) -> list[str]:
        """
        Get list of supported file formats.

        Returns:
            List of supported file extensions (e.g., ['pdf', 'docx', 'txt'])
        """
        pass
