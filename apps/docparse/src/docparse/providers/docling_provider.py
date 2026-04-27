"""Docling provider implementation for document parsing."""

import logging
from pathlib import Path

from docling.document_converter import DocumentConverter

from .base import BaseProvider

logger = logging.getLogger(__name__)


class DoclingProvider(BaseProvider):
    """Document parsing provider using Docling."""

    def __init__(self):
        """Initialize the Docling provider."""
        self.converter = DocumentConverter()
        logger.info("DoclingProvider initialized")

    async def parse_document(self, file_path: Path) -> str:
        """
        Parse a document using Docling and return markdown content.

        Args:
            file_path: Path to the document file to parse

        Returns:
            Document content in markdown format

        Raises:
            FileNotFoundError: If the file does not exist
            ValueError: If the file format is not supported
            Exception: For other parsing errors
        """
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        if not self.is_supported(file_path):
            raise ValueError(
                f"Unsupported file format: {file_path.suffix}. "
                f"Supported formats: {', '.join(self.get_supported_formats())}"
            )

        try:
            logger.info(f"Parsing document: {file_path}")

            # Convert the document
            result = self.converter.convert(str(file_path))

            # Export to markdown
            markdown_content = result.document.export_to_markdown()

            logger.info(f"Successfully parsed document: {file_path}")
            return markdown_content

        except Exception as e:
            logger.error(f"Error parsing document {file_path}: {str(e)}")
            raise Exception(f"Failed to parse document: {str(e)}") from e

    def get_supported_formats(self) -> list[str]:
        """
        Get list of supported file formats by Docling.

        Returns:
            List of supported file extensions
        """
        # Docling supports various document formats
        return [
            "pdf",
            "docx",
            "pptx",
            "xlsx",
            "html",
            "md",
            "txt",
            "asciidoc",
            "xml",
        ]
