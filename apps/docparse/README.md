# DocParse

DocParse is a small, container-hosted application that ingests documents of various formats and outputs text in markdown format for AI ingestion.

## Features

- **Asynchronous API** - Fast, non-blocking document processing using FastAPI
- **Multiple Format Support** - PDF, DOCX, PPTX, XLSX, HTML, Markdown, TXT, AsciiDoc, XML
- **Extensible Provider System** - Easy to add new parsing providers
- **Container Ready** - Docker support for easy deployment
- **Type Safe** - Full type hints and Pydantic validation

## Quick Start

### Using Docker (Recommended)

```bash
# Build the image
docker build -t docparse:latest .

# Run the container
docker run -p 8001:8001 docparse:latest
```

Access the API at http://localhost:8001/docs

### Local Development

```bash
# Install dependencies
uv venv
source .venv/bin/activate
make install-dev

# Run the application
make run
```

## API Usage

### Health Check

```bash
curl http://localhost:8001/health
```

### Parse Document

```bash
curl -X POST http://localhost:8001/parse \
  -H "Content-Type: application/json" \
  -d '{"s3_presigned_http_url": "https://bucket.s3.amazonaws.com/documents/example.pdf?AWSAccessKeyId=..."}'
```

Response:
```json
{
  "markdown": "# Document Title\n\nDocument content...",
  "s3_presigned_http_url": "https://bucket.s3.amazonaws.com/documents/example.pdf?AWSAccessKeyId=..."
}
```

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DOCPARSE_PROVIDER` | Document parsing provider | `docling` |
| `API_PORT` | API port | `8001` |
| `LOG_LEVEL` | Logging level | `INFO` |

### Providers

DocParse is extensible through a provider system. The active provider is selected via the `DOCPARSE_PROVIDER` environment variable.

**Available Providers:**
- **Docling** (default) - Supports PDF, DOCX, PPTX, XLSX, HTML, MD, TXT, AsciiDoc, XML

See [DEVELOPMENT.md](DEVELOPMENT.md) for information on adding new providers.

## Architecture

### API Endpoints

- `GET /` - API information
- `GET /health` - Health check and provider status
- `POST /parse` - Parse document to markdown
- `GET /docs` - Interactive API documentation

### Provider Pattern

The application uses an abstract provider pattern:

```python
from src.providers import BaseProvider
from pydantic import HttpUrl

class CustomProvider(BaseProvider):
    async def parse_document(self, s3_presigned_http_url: HttpUrl) -> str:
        # Your implementation - download and parse from S3 URL
        pass
    
    def get_supported_formats(self) -> list[str]:
        return ["pdf", "docx"]
```

## Development

See [DEVELOPMENT.md](DEVELOPMENT.md) for comprehensive development guide.

### Common Commands

```bash
make install-dev  # Install dependencies
make test        # Run tests
make lint        # Lint code
make format      # Format code
make run         # Run locally
```

## Testing

```bash
# Run all tests
make test

# Run specific tests
pytest tests/test_api.py -v

# Run with coverage
pytest --cov=src tests/
```

## Infrastructure

### Current: Local/Docker

The application currently runs locally or in Docker containers. See the included `Dockerfile` for production deployment.

### Future: Modal

Plans to migrate to [Modal](https://modal.com) for serverless deployment. The codebase is structured to support this migration with minimal changes.

## License

MIT

## Documentation

- [Development Guide](DEVELOPMENT.md) - Comprehensive development documentation
- [API Documentation](http://localhost:8001/docs) - Interactive API docs (when running)

