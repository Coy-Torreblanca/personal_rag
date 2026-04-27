# DocParse Development Guide

## Quick Start

### Local Development

1. **Install dependencies:**
   ```bash
   cd apps/docparse
   uv venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   make install-dev
   ```

2. **Set up environment:**
   ```bash
   cp .env.example .env
   # Edit .env if needed (default settings should work)
   ```

3. **Run the application:**
   ```bash
   make run
   ```

4. **Access the API:**
   - API Documentation: http://localhost:8001/docs
   - Health Check: http://localhost:8001/health
   - Root: http://localhost:8001/

### Docker Development

1. **Build the Docker image:**
   ```bash
   make docker-build-dev
   ```

2. **Run the container:**
   ```bash
   make docker-run-dev
   ```

## API Usage

### Health Check

```bash
curl http://localhost:8001/health
```

Response:
```json
{
  "status": "healthy",
  "provider": "docling",
  "supported_formats": ["pdf", "docx", "pptx", "xlsx", "html", "md", "txt", "asciidoc", "xml"]
}
```

### Parse Document

```bash
curl -X POST http://localhost:8001/parse \
  -H "Content-Type: application/json" \
  -d '{"file_path": "/path/to/document.pdf"}'
```

Response:
```json
{
  "markdown": "# Document Title\n\nDocument content in markdown...",
  "file_path": "/path/to/document.pdf"
}
```

### Using Python Client

```python
import httpx

async def parse_document(file_path: str) -> str:
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:8001/parse",
            json={"file_path": file_path}
        )
        response.raise_for_status()
        return response.json()["markdown"]

# Usage
markdown = await parse_document("/path/to/document.pdf")
print(markdown)
```

## Architecture

### Project Structure

```
apps/docparse/
├── src/
│   ├── __init__.py           # Package initialization
│   ├── main.py               # FastAPI application
│   ├── config.py             # Configuration management
│   ├── models.py             # Pydantic models
│   └── providers/
│       ├── __init__.py       # Providers package
│       ├── base.py           # BaseProvider abstract class
│       ├── docling_provider.py  # Docling implementation
│       └── factory.py        # Provider factory
├── tests/
│   ├── __init__.py
│   ├── test_api.py           # API tests
│   └── test_providers.py     # Provider tests
├── Dockerfile                # Production Docker image
├── Dockerfile.dev            # Development Docker image
├── pyproject.toml            # Project dependencies
├── Makefile                  # Development commands
└── README.md                 # Project overview
```

### Provider System

The provider system is designed to be extensible:

1. **BaseProvider**: Abstract base class defining the interface
2. **DoclingProvider**: Implementation using Docling library
3. **Provider Factory**: Creates providers based on environment variable

To add a new provider:

1. Create a new file in `src/providers/` (e.g., `custom_provider.py`)
2. Implement the `BaseProvider` interface
3. Update `factory.py` to include the new provider
4. Update documentation with supported formats

Example:

```python
# src/providers/custom_provider.py
from pathlib import Path
from .base import BaseProvider

class CustomProvider(BaseProvider):
    async def parse_document(self, file_path: Path) -> str:
        # Your implementation
        pass
    
    def get_supported_formats(self) -> list[str]:
        return ["pdf", "docx"]

# src/providers/factory.py
def get_provider() -> BaseProvider:
    provider_name = settings.docparse_provider.lower()
    
    if provider_name == "docling":
        return DoclingProvider()
    elif provider_name == "custom":
        return CustomProvider()
    else:
        raise ValueError(f"Unsupported provider: {provider_name}")
```

## Configuration

All configuration is managed through environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `DOCPARSE_PROVIDER` | Document parsing provider to use | `docling` |
| `API_TITLE` | API title | `DocParse API` |
| `API_DESCRIPTION` | API description | Document parsing service... |
| `API_VERSION` | API version | `0.1.0` |
| `API_HOST` | API host | `0.0.0.0` |
| `API_PORT` | API port | `8001` |
| `LOG_LEVEL` | Logging level | `INFO` |

## Testing

Run all tests:
```bash
make test
```

Run specific test file:
```bash
pytest tests/test_api.py -v
```

Run with coverage:
```bash
pytest --cov=src tests/
```

## Code Quality

Format code:
```bash
make format
```

Lint code:
```bash
make lint
```

## Deployment

### Docker Production

Build and run production image:
```bash
make docker-build
docker run -p 8001:8001 -e DOCPARSE_PROVIDER=docling docparse:latest
```

### Docker Compose

Add to your `docker-compose.yml`:

```yaml
services:
  docparse:
    build:
      context: ./apps/docparse
      dockerfile: Dockerfile
    ports:
      - "8001:8001"
    environment:
      - DOCPARSE_PROVIDER=docling
      - LOG_LEVEL=INFO
    volumes:
      - /path/to/documents:/documents:ro
```

### Modal Deployment (Future)

The application is designed to be easily deployed to Modal:

1. Install Modal: `pip install modal`
2. Create `modal_app.py`:

```python
import modal

stub = modal.Stub("docparse")

image = modal.Image.debian_slim().pip_install_from_pyproject("pyproject.toml")

@stub.function(image=image)
@modal.asgi_app()
def fastapi_app():
    from src.main import app
    return app
```

3. Deploy: `modal deploy modal_app.py`

## Troubleshooting

### Common Issues

**Issue**: "Provider not initialized"
- **Solution**: Check that `DOCPARSE_PROVIDER` is set correctly and the provider is available

**Issue**: "Unsupported file format"
- **Solution**: Check supported formats at `/health` endpoint and verify file extension

**Issue**: Docling installation fails
- **Solution**: Ensure you have system dependencies installed (build-essential, git)

### Logs

Enable debug logging:
```bash
export LOG_LEVEL=DEBUG
make run
```

## Contributing

1. Follow the existing code structure
2. Add tests for new features
3. Run `make lint` and `make format` before committing
4. Update documentation for API changes
