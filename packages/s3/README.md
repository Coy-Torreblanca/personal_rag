# S3/R2 Package

A comprehensive Python package for AWS S3 and Cloudflare R2 operations with support for basic CRUD operations, file management, and utilities.

## Features

- **Unified Interface**: Same API for both AWS S3 and Cloudflare R2
- **Basic CRUD Operations**: Upload, download, delete, list files
- **File Metadata**: Rich metadata tracking with file type detection
- **Presigned URLs**: Generate temporary access URLs
- **Structured Keys**: Organized file storage with automatic key generation
- **Error Handling**: Comprehensive exception hierarchy
- **Environment Configuration**: Automatic configuration from environment variables
- **Type Hints**: Full type annotations for better IDE support

## Installation

```bash
# Install from local package
pip install -e ./packages/s3

# Or add to your project dependencies
# In pyproject.toml:
# dependencies = ["s3 @ file://./packages/s3"]
```

## Environment Variables

### For AWS S3:
```bash
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key
AWS_REGION=us-east-1
AWS_S3_BUCKET=your-bucket-name
AWS_S3_ENDPOINT=  # Optional: custom endpoint
```

### For Cloudflare R2:
```bash
R2_ACCOUNT_ID=your_account_id
R2_ACCESS_ID=your_access_key
R2_SECRET_ACCESS_KEY=your_secret_key
R2_S3_API=  # Optional: custom S3 API endpoint
```

## Quick Start

### Basic Usage

```python
from s3 import create_storage_client, get_default_client

# Auto-detect from environment (S3 or R2)
client = get_default_client()

# Or create specific client
from s3 import create_s3_client, create_r2_client

# S3 client
s3_client = create_s3_client(bucket_name="my-bucket")

# R2 client  
r2_client = create_r2_client(bucket_name="my-r2-bucket")
```

### Upload Files

```python
# Upload from file path
response = client.upload_file(
    file_path="/path/to/file.pdf",
    key="documents/file.pdf",
    content_type="application/pdf",
    metadata={"author": "John Doe", "category": "documents"}
)

print(f"Uploaded to: {response.url}")
print(f"File size: {response.size} bytes")
print(f"ETag: {response.etag}")

# Upload bytes data
with open("/path/to/file.pdf", "rb") as f:
    data = f.read()

response = client.upload_bytes(
    data=data,
    key="documents/file.pdf",
    content_type="application/pdf"
)
```

### Download Files

```python
# Download to file
response = client.download_file(
    key="documents/file.pdf",
    file_path="/path/to/downloaded.pdf"
)

# Download as bytes
response = client.download_bytes(key="documents/file.pdf")
content = response.content
metadata = response.metadata
```

### List Files

```python
# List all files
response = client.list_files()

# List with prefix
response = client.list_files(prefix="documents/")

# List with pagination
response = client.list_files(max_keys=50)
if response.is_truncated:
    next_response = client.list_files(
        prefix="documents/",
        continuation_token=response.continuation_token
    )

for file in response.files:
    print(f"{file.key} - {file.size} bytes - {file.last_modified}")
```

### Delete Files

```python
# Delete single file
response = client.delete_file(key="documents/file.pdf")

# Batch delete (example)
files_to_delete = ["documents/file1.pdf", "documents/file2.pdf"]
for key in files_to_delete:
    client.delete_file(key=key)
```

### Generate Presigned URLs

```python
# Generate download URL (valid for 1 hour)
response = client.generate_presigned_url(
    key="documents/file.pdf",
    method="get_object",
    expires_in=3600
)
print(f"Download URL: {response.url}")

# Generate upload URL
response = client.generate_presigned_url(
    key="uploads/new-file.pdf",
    method="put_object",
    expires_in=1800,
    content_type="application/pdf"
)
```

### Check File Existence

```python
if client.file_exists(key="documents/file.pdf"):
    print("File exists")
    
# Get file metadata
metadata = client.get_file_metadata(key="documents/file.pdf")
if metadata:
    print(f"File size: {metadata.size}")
    print(f"Content type: {metadata.content_type}")
    print(f"Last modified: {metadata.last_modified}")
```

## Advanced Usage

### Structured Key Generation

```python
from s3 import generate_key, parse_key
from datetime import datetime

# Generate structured key
key = generate_key(
    filename="business_plan.pdf",
    prefix="documents",
    organization_id="org_123",
    user_id="user_456",
    timestamp=datetime.now()
)
# Result: documents/org_123/user_456/2024/01/15/143022/business_plan.pdf

# Parse key back to components
components = parse_key(key)
print(components)
# {'filename': 'business_plan.pdf', 'timestamp': '143022', 
#  'user_id': 'user_456', 'organization_id': 'org_123', 
#  'prefix': 'documents'}
```

### File Type Detection

```python
from s3 import get_file_type_from_extension, FileType

file_type = get_file_type_from_extension("document.pdf")
# FileType.PDF

if file_type == FileType.PDF:
    print("This is a PDF file")
```

### R2-Specific Features

```python
from s3 import create_r2_client

r2_client = create_r2_client(bucket_name="my-bucket")

# Get public URL (R2-specific)
public_url = r2_client.get_public_url(key="documents/file.pdf")
print(f"Public URL: {public_url}")
```

## Error Handling

```python
from s3 import (
    FileNotFoundError, UploadError, ConfigurationError,
    BucketError, DownloadError
)

try:
    response = client.download_file(key="non-existent-file.pdf", file_path="/tmp/file.pdf")
except FileNotFoundError as e:
    print(f"File not found: {e}")
except DownloadError as e:
    print(f"Download failed: {e}")
except Exception as e:
    print(f"Unexpected error: {e}")
```

## Configuration Classes

```python
from s3 import S3Config, R2Config

# Manual configuration
s3_config = S3Config(
    access_key_id="your_key",
    secret_access_key="your_secret",
    region="us-east-1",
    bucket_name="my-bucket"
)

r2_config = R2Config(
    account_id="your_account_id",
    access_key_id="your_key",
    secret_access_key="your_secret",
    s3_api_endpoint="https://your-endpoint.r2.cloudflarestorage.com",
    bucket_name="my-bucket"
)

# From environment
s3_config = S3Config.from_env()
r2_config = R2Config.from_env()
```

## Integration with 30ai Project

The package is designed to work seamlessly with the 30ai monorepo structure:

```python
# In your FastAPI application
from fastapi import FastAPI, UploadFile, File, HTTPException
from s3 import get_default_client

app = FastAPI()
client = get_default_client()

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    try:
        # Read file content
        content = await file.read()
        
        # Generate structured key
        key = f"uploads/{file.filename}"
        
        # Upload to S3/R2
        response = client.upload_bytes(
            data=content,
            key=key,
            content_type=file.content_type
        )
        
        return {
            "success": True,
            "url": response.url,
            "key": response.key,
            "size": response.size
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/download/{key}")
async def download_file(key: str):
    try:
        response = client.download_bytes(key=key)
        return {
            "content": response.content.decode("utf-8"),
            "metadata": {
                "size": response.metadata.size,
                "content_type": response.metadata.content_type,
                "last_modified": response.metadata.last_modified.isoformat()
            }
        }
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")
```

## Testing

```python
# Example test with pytest
import pytest
from s3 import create_s3_client
from moto import mock_s3

@mock_s3
def test_upload_file():
    client = create_s3_client(
        access_key_id="test",
        secret_access_key="test",
        region="us-east-1",
        from_env=False
    )
    
    # Create test bucket
    client.client.create_bucket(Bucket="test-bucket")
    
    # Test upload
    response = client.upload_bytes(
        data=b"test content",
        key="test.txt",
        bucket_name="test-bucket"
    )
    
    assert response.success
    assert response.key == "test.txt"
```

## License

Part of the 30ai project. See main project license for details.