"""Base provider interface for document parsing."""

from abc import ABC, abstractmethod
from pathlib import Path


class BaseProvider(ABC):
    """Abstract base class for document parsing providers."""

    @abstractmethod
    async def parse_document(self, file_path: Path) -> str:
        """
        Parse a document and return its content in markdown format.

        Args:
            file_path: Path to the document file to parse

        Returns:
            Document content in markdown format

        Raises:
            FileNotFoundError: If the file does not exist
            ValueError: If the file format is not supported
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

    def is_supported(self, file_path: Path) -> bool:
        """
        Check if a file format is supported.

        Args:
            file_path: Path to the file to check

        Returns:
            True if the file format is supported, False otherwise
        """
        extension = file_path.suffix.lstrip(".").lower()
        return extension in self.get_supported_formats()
