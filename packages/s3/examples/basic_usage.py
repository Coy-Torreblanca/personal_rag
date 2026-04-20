#!/usr/bin/env python3
"""Basic usage examples for the S3/R2 package."""

import os
import tempfile
from datetime import datetime

# Add parent directory to path for local development
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from s3 import (
    create_s3_client,
    create_r2_client,
    create_storage_client,
    get_default_client,
    generate_key,
    FileType
)


def example_basic_operations():
    """Demonstrate basic CRUD operations."""
    print("=== Basic CRUD Operations ===\n")
    
    # Create a client (auto-detects from environment)
    try:
        client = get_default_client()
        print(f"Created client: {client.__class__.__name__}")
    except Exception as e:
        print(f"Could not create default client: {e}")
        print("Falling back to demonstration mode...")
        return
    
    # Create a test file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write("Hello, this is a test file for S3/R2 operations!\n")
        f.write("This is line 2 of the test file.\n")
        test_file = f.name
    
    try:
        # 1. Upload file
        print("\n1. Uploading file...")
        upload_response = client.upload_file(
            file_path=test_file,
            key="test/example.txt",
            content_type="text/plain",
            metadata={"source": "example", "purpose": "demonstration"}
        )
        print(f"   Uploaded: {upload_response.key}")
        print(f"   URL: {upload_response.url}")
        print(f"   Size: {upload_response.size} bytes")
        print(f"   ETag: {upload_response.etag}")
        
        # 2. Check if file exists
        print("\n2. Checking file existence...")
        exists = client.file_exists(key="test/example.txt")
        print(f"   File exists: {exists}")
        
        # 3. Get file metadata
        print("\n3. Getting file metadata...")
        metadata = client.get_file_metadata(key="test/example.txt")
        if metadata:
            print(f"   Key: {metadata.key}")
            print(f"   Size: {metadata.size} bytes")
            print(f"   Content Type: {metadata.content_type}")
            print(f"   File Type: {metadata.file_type}")
            print(f"   Last Modified: {metadata.last_modified}")
        
        # 4. Download file as bytes
        print("\n4. Downloading file as bytes...")
        download_response = client.download_bytes(key="test/example.txt")
        print(f"   Downloaded {len(download_response.content)} bytes")
        print(f"   Content preview: {download_response.content[:50]}...")
        
        # 5. List files
        print("\n5. Listing files...")
        list_response = client.list_files(prefix="test/")
        print(f"   Found {len(list_response.files)} files:")
        for file in list_response.files:
            print(f"   - {file.key} ({file.size} bytes)")
        
        # 6. Generate presigned URL
        print("\n6. Generating presigned URL...")
        presigned_response = client.generate_presigned_url(
            key="test/example.txt",
            method="get_object",
            expires_in=300  # 5 minutes
        )
        print(f"   Presigned URL: {presigned_response.url}")
        print(f"   Expires in: {presigned_response.expires_in} seconds")
        
        # 7. Delete file
        print("\n7. Deleting file...")
        delete_response = client.delete_file(key="test/example.txt")
        print(f"   Delete successful: {delete_response.success}")
        
        # 8. Verify deletion
        print("\n8. Verifying deletion...")
        exists = client.file_exists(key="test/example.txt")
        print(f"   File still exists: {exists}")
        
    finally:
        # Clean up test file
        os.unlink(test_file)
    
    print("\n=== Basic operations completed ===\n")


def example_structured_keys():
    """Demonstrate structured key generation."""
    print("=== Structured Key Generation ===\n")
    
    # Generate a structured key
    key = generate_key(
        filename="business_plan.pdf",
        prefix="documents",
        organization_id="org_123",
        user_id="user_456",
        timestamp=datetime.now()
    )
    
    print(f"Generated key: {key}")
    print(f"Key components:")
    print(f"  - Prefix: documents")
    print(f"  - Organization: org_123")
    print(f"  - User: user_456")
    print(f"  - Timestamp: current datetime")
    print(f"  - Filename: business_plan.pdf")
    
    print("\n=== Key generation completed ===\n")


def example_file_type_detection():
    """Demonstrate file type detection."""
    print("=== File Type Detection ===\n")
    
    test_files = [
        "document.pdf",
        "report.docx",
        "data.csv",
        "config.json",
        "image.jpg",
        "audio.mp3",
        "video.mp4",
        "unknown.xyz"
    ]
    
    for filename in test_files:
        file_type = FileType(get_file_type_from_extension(filename))
        print(f"{filename:20} -> {file_type.value:10} ({file_type.name})")
    
    print("\n=== File type detection completed ===\n")


def example_client_creation():
    """Demonstrate different ways to create clients."""
    print("=== Client Creation Methods ===\n")
    
    # Method 1: Auto-detect from environment
    print("1. Auto-detection from environment:")
    try:
        client1 = get_default_client()
        print(f"   Created: {client1.__class__.__name__}")
    except Exception as e:
        print(f"   Failed: {e}")
    
    # Method 2: Create specific client from environment
    print("\n2. Create S3 client from environment:")
    try:
        client2 = create_s3_client(bucket_name="test-bucket")
        print(f"   Created: {client2.__class__.__name__}")
    except Exception as e:
        print(f"   Failed: {e}")
    
    print("\n3. Create R2 client from environment:")
    try:
        client3 = create_r2_client(bucket_name="test-bucket")
        print(f"   Created: {client3.__class__.__name__}")
    except Exception as e:
        print(f"   Failed: {e}")
    
    # Method 3: Create with explicit configuration
    print("\n4. Create with explicit configuration (demonstration):")
    print("   (This would fail without actual credentials)")
    
    print("\n=== Client creation examples completed ===\n")


def main():
    """Run all examples."""
    print("S3/R2 Package Examples")
    print("=" * 50 + "\n")
    
    # Check environment variables
    print("Environment check:")
    env_vars = [
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "R2_ACCOUNT_ID",
        "R2_ACCESS_ID",
        "R2_SECRET_ACCESS_KEY"
    ]
    
    for var in env_vars:
        value = os.getenv(var)
        if value:
            masked = value[:4] + "..." + value[-4:] if len(value) > 8 else "***"
            print(f"  {var}: {masked}")
        else:
            print(f"  {var}: Not set")
    
    print("\n" + "=" * 50 + "\n")
    
    # Run examples
    example_client_creation()
    example_structured_keys()
    example_file_type_detection()
    example_basic_operations()
    
    print("\nAll examples completed!")


if __name__ == "__main__":
    main()