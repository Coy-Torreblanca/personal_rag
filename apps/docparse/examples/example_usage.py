"""Example usage of the DocParse API."""

import asyncio
from pathlib import Path

import httpx


async def parse_document(file_path: str, api_url: str = "http://localhost:8001") -> str:
    """
    Parse a document using the DocParse API.

    Args:
        file_path: Path to the document to parse
        api_url: Base URL of the DocParse API

    Returns:
        Markdown content of the document
    """
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{api_url}/parse",
            json={"file_path": file_path},
            timeout=60.0,  # Some documents may take time to parse
        )
        response.raise_for_status()
        data = response.json()
        return data["markdown"]


async def check_health(api_url: str = "http://localhost:8001") -> dict:
    """
    Check the health status of the DocParse API.

    Args:
        api_url: Base URL of the DocParse API

    Returns:
        Health check response
    """
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{api_url}/health")
        response.raise_for_status()
        return response.json()


async def main():
    """Main example function."""
    api_url = "http://localhost:8001"

    # Check API health
    print("Checking API health...")
    health = await check_health(api_url)
    print(f"Status: {health['status']}")
    print(f"Provider: {health['provider']}")
    print(f"Supported formats: {', '.join(health['supported_formats'])}")
    print()

    # Parse a document
    # Replace with an actual file path
    document_path = "/path/to/your/document.pdf"

    if Path(document_path).exists():
        print(f"Parsing document: {document_path}")
        try:
            markdown = await parse_document(document_path, api_url)
            print("Successfully parsed document!")
            print(f"Preview (first 500 chars):\n{markdown[:500]}...")
        except httpx.HTTPStatusError as e:
            print(f"Error parsing document: {e}")
            print(f"Response: {e.response.text}")
    else:
        print(f"Document not found: {document_path}")
        print("Please update the document_path variable with a valid file path")


if __name__ == "__main__":
    asyncio.run(main())
