"""Tests for the DocParse API."""

import pytest
from fastapi.testclient import TestClient

from src.main import app


@pytest.fixture
def client():
    """Create a test client."""
    return TestClient(app)


def test_health_check(client):
    """Test the health check endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "provider" in data
    assert "supported_formats" in data


def test_root_endpoint(client):
    """Test the root endpoint."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "name" in data
    assert "version" in data
    assert "endpoints" in data


def test_parse_nonexistent_file(client):
    """Test parsing a non-existent file."""
    response = client.post(
        "/parse",
        json={"file_path": "/path/to/nonexistent/file.pdf"},
    )
    assert response.status_code == 404


def test_parse_unsupported_format(client, tmp_path):
    """Test parsing an unsupported file format."""
    # Create a temporary file with unsupported extension
    test_file = tmp_path / "test.unsupported"
    test_file.write_text("test content")

    response = client.post(
        "/parse",
        json={"file_path": str(test_file)},
    )
    assert response.status_code == 400
