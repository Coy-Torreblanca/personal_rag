# DocParse Examples

This directory contains example usage of the DocParse API.

## Prerequisites

Make sure the DocParse API is running:

```bash
# From the apps/docparse directory
make run

# Or using Docker
docker-compose up docparse
```

Install the client dependencies:

```bash
pip install httpx
```

## Examples

### 1. Basic Usage (`example_usage.py`)

Demonstrates basic API usage including health checks and single document parsing.

```bash
python examples/example_usage.py
```

### 2. Batch Processing (`batch_processing.py`)

Shows how to parse multiple documents concurrently and save them as markdown files.

```bash
# Place your documents in the ./documents directory
python examples/batch_processing.py
```

This will:
- Scan the `./documents` directory for supported files
- Parse them concurrently (max 5 at a time)
- Save the results to `./output/*.md`

## API Client Pattern

Here's a reusable client pattern:

```python
import httpx
from pathlib import Path

class DocParseClient:
    def __init__(self, base_url: str = "http://localhost:8001"):
        self.base_url = base_url
        self.client = httpx.AsyncClient(base_url=base_url, timeout=120.0)
    
    async def parse(self, file_path: str | Path) -> str:
        response = await self.client.post(
            "/parse",
            json={"file_path": str(file_path)}
        )
        response.raise_for_status()
        return response.json()["markdown"]
    
    async def health(self) -> dict:
        response = await self.client.get("/health")
        response.raise_for_status()
        return response.json()
    
    async def close(self):
        await self.client.aclose()

# Usage
async with DocParseClient() as client:
    markdown = await client.parse("/path/to/document.pdf")
```

## Error Handling

Always handle potential errors:

```python
try:
    markdown = await parse_document("/path/to/doc.pdf")
except httpx.HTTPStatusError as e:
    if e.response.status_code == 404:
        print("File not found")
    elif e.response.status_code == 400:
        print("Unsupported file format")
    else:
        print(f"API error: {e}")
except httpx.RequestError as e:
    print(f"Network error: {e}")
```

## Performance Tips

1. **Use connection pooling** - Reuse the same `httpx.AsyncClient` instance
2. **Limit concurrency** - Don't overwhelm the API with too many concurrent requests
3. **Set appropriate timeouts** - Large documents may take time to process
4. **Batch similar documents** - Group documents by type for better processing

## Integration Examples

### FastAPI Integration

```python
from fastapi import FastAPI
import httpx

app = FastAPI()
docparse_client = httpx.AsyncClient(base_url="http://docparse:8001")

@app.post("/process")
async def process_document(file_path: str):
    response = await docparse_client.post(
        "/parse",
        json={"file_path": file_path}
    )
    return response.json()
```

### Celery Task Integration

```python
from celery import Celery
import httpx

app = Celery('tasks')

@app.task
def parse_document_task(file_path: str):
    with httpx.Client(base_url="http://docparse:8001", timeout=300.0) as client:
        response = client.post("/parse", json={"file_path": file_path})
        return response.json()["markdown"]
```
