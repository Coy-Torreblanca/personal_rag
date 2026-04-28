"""Docling provider implementation for document parsing."""

import logging

from docling.document_converter import DocumentConverter
from pydantic import HttpUrl

from .base import BaseProvider

logger = logging.getLogger(__name__)


class DoclingProvider(BaseProvider):
    """Document parsing provider using Docling."""

    def __init__(self):
        """Initialize the Docling provider."""
        self.converter = DocumentConverter()
        logger.info("DoclingProvider initialized")

    async def parse_document(self, s3_presigned_http_url: HttpUrl) -> str:
        """
        Parse a document from S3 using Docling and return markdown content.

        Args:
            s3_presigned_http_url: S3 presigned URL to download the document

        Returns:
            Document content in markdown format

        Raises:
            FileNotFoundError: If the document cannot be retrieved from S3
            ValueError: If the file format is not supported
            Exception: For other parsing errors
        """

        try:
            logger.info("Parsing document from S3 URL")

            # Convert the document directly from the S3 URL
            result = self.converter.convert(str(s3_presigned_http_url))

            # Export to markdown
            markdown_content = result.document.export_to_markdown()

            logger.info("Successfully parsed document from S3")
            return markdown_content

        except Exception as e:
            logger.error(f"Error parsing document from S3: {str(e)}")
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
