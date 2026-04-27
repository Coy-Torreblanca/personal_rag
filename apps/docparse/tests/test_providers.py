"""Tests for document parsing providers."""

import pytest
from pathlib import Path

from src.providers import get_provider
from src.providers.base import BaseProvider
from src.providers.docling_provider import DoclingProvider


def test_get_provider_docling():
    """Test getting the Docling provider."""
    provider = get_provider()
    assert isinstance(provider, DoclingProvider)
    assert isinstance(provider, BaseProvider)


def test_docling_supported_formats():
    """Test Docling supported formats."""
    provider = DoclingProvider()
    formats = provider.get_supported_formats()
    assert isinstance(formats, list)
    assert len(formats) > 0
    assert "pdf" in formats
    assert "docx" in formats


def test_is_supported():
    """Test file format support checking."""
    provider = DoclingProvider()
    
    assert provider.is_supported(Path("test.pdf"))
    assert provider.is_supported(Path("test.docx"))
    assert not provider.is_supported(Path("test.unsupported"))


@pytest.mark.asyncio
async def test_parse_nonexistent_file():
    """Test parsing a non-existent file."""
    provider = DoclingProvider()
    
    with pytest.raises(FileNotFoundError):
        await provider.parse_document(Path("/path/to/nonexistent/file.pdf"))


@pytest.mark.asyncio
async def test_parse_unsupported_file(tmp_path):
    """Test parsing an unsupported file format."""
    provider = DoclingProvider()
    
    # Create a temporary file with unsupported extension
    test_file = tmp_path / "test.unsupported"
    test_file.write_text("test content")
    
    with pytest.raises(ValueError) as exc_info:
        await provider.parse_document(test_file)
    
    assert "Unsupported file format" in str(exc_info.value)
