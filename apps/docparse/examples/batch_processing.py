"""Example of batch processing multiple documents with DocParse."""

import asyncio
from pathlib import Path

import httpx


async def parse_document(
    client: httpx.AsyncClient,
    file_path: Path,
    api_url: str = "http://localhost:8001",
) -> tuple[Path, str | None, str | None]:
    """
    Parse a single document.

    Args:
        client: HTTP client instance
        file_path: Path to the document
        api_url: Base URL of the DocParse API

    Returns:
        Tuple of (file_path, markdown_content, error_message)
    """
    try:
        response = await client.post(
            f"{api_url}/parse",
            json={"file_path": str(file_path)},
            timeout=120.0,
        )
        response.raise_for_status()
        data = response.json()
        return file_path, data["markdown"], None
    except Exception as e:
        return file_path, None, str(e)


async def batch_parse_documents(
    directory: Path,
    output_dir: Path,
    api_url: str = "http://localhost:8001",
    max_concurrent: int = 5,
) -> None:
    """
    Parse all documents in a directory and save as markdown files.

    Args:
        directory: Directory containing documents to parse
        output_dir: Directory to save markdown files
        api_url: Base URL of the DocParse API
        max_concurrent: Maximum number of concurrent requests
    """
    # Get supported formats from API
    async with httpx.AsyncClient() as client:
        health = await client.get(f"{api_url}/health")
        supported_formats = health.json()["supported_formats"]

    # Find all supported documents
    documents = []
    for ext in supported_formats:
        documents.extend(directory.glob(f"*.{ext}"))

    if not documents:
        print(f"No supported documents found in {directory}")
        return

    print(f"Found {len(documents)} documents to process")

    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)

    # Process documents with concurrency limit
    semaphore = asyncio.Semaphore(max_concurrent)

    async def process_with_limit(client: httpx.AsyncClient, doc: Path):
        async with semaphore:
            return await parse_document(client, doc, api_url)

    async with httpx.AsyncClient() as client:
        tasks = [process_with_limit(client, doc) for doc in documents]
        results = await asyncio.gather(*tasks)

    # Save results
    successful = 0
    failed = 0

    for file_path, markdown, error in results:
        if markdown:
            output_file = output_dir / f"{file_path.stem}.md"
            output_file.write_text(markdown)
            print(f"✓ {file_path.name} -> {output_file.name}")
            successful += 1
        else:
            print(f"✗ {file_path.name}: {error}")
            failed += 1

    print(f"\nProcessing complete: {successful} successful, {failed} failed")


async def main():
    """Main example function."""
    # Configuration
    documents_dir = Path("./documents")
    output_dir = Path("./output")
    api_url = "http://localhost:8001"

    if not documents_dir.exists():
        print(f"Documents directory not found: {documents_dir}")
        print("Creating directory...")
        documents_dir.mkdir(parents=True, exist_ok=True)
        print("Please add documents to parse in the ./documents directory")
        return

    await batch_parse_documents(
        directory=documents_dir,
        output_dir=output_dir,
        api_url=api_url,
        max_concurrent=5,
    )


if __name__ == "__main__":
    asyncio.run(main())
