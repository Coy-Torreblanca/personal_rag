#!/usr/bin/env python3
"""
Test script for R2Client operations: upload, download, and delete files.

This script demonstrates the basic operations of the R2Client:
1. Upload a file (from path and from bytes)
2. Download a file (to path and as bytes)
3. List files in bucket
4. Check if file exists
5. Generate presigned URL
6. Delete files

Usage:
    Set the required environment variables:
    - R2_ACCOUNT_ID
    - R2_ACCESS_ID
    - R2_SECRET_ACCESS_KEY
    - R2_S3_API (endpoint URL)

    Then run: python test_r2_operations.py
"""

import os
import tempfile
import sys
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

# Add the src directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from s3.client import R2Client


def print_header(title: str) -> None:
    """Print a formatted header."""
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)


def print_success(message: str) -> None:
    """Print a success message."""
    print(f"✅ {message}")


def print_error(message: str) -> None:
    """Print an error message."""
    print(f"❌ {message}")


def print_info(message: str) -> None:
    """Print an info message."""
    print(f"ℹ️  {message}")


def check_environment_variables() -> bool:
    """Check if required environment variables are set."""
    required_vars = [
        "R2_ACCOUNT_ID",
        "R2_ACCESS_ID",
        "R2_SECRET_ACCESS_KEY",
        "R2_S3_API",
    ]

    missing_vars = []
    for var in required_vars:
        if not os.getenv(var):
            missing_vars.append(var)

    if missing_vars:
        print_error("Missing required environment variables:")
        for var in missing_vars:
            print(f"  - {var}")
        print("\nPlease set these variables before running the test.")
        return False

    return True


def create_test_file(file_path: str, content: str = "Hello, R2!") -> None:
    """Create a test file with the given content."""
    with open(file_path, "w") as f:
        f.write(content)
    print_info(f"Created test file: {file_path} ({len(content)} bytes)")


def test_upload_file(client: R2Client, bucket_name: str) -> str:
    """Test uploading a file from local path."""
    print_header("Testing upload_file()")

    # Create a temporary test file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as tmp:
        tmp.write("This is a test file for R2 upload.\n")
        tmp.write("It contains multiple lines of text.\n")
        tmp.write("Testing file upload functionality.\n")
        tmp_path = tmp.name

    try:
        key = "test-upload-file.txt"
        content_type = "text/plain"
        metadata = {"test": "true", "created_by": "test_r2_operations.py"}

        print_info(f"Uploading file: {tmp_path} -> {key}")
        print_info(f"Bucket: {bucket_name}")
        print_info(f"Content-Type: {content_type}")
        print_info(f"Metadata: {metadata}")

        response = client.upload_file(
            file_path=tmp_path,
            key=key,
            bucket_name=bucket_name,
            content_type=content_type,
            metadata=metadata,
        )

        print_success(f"File uploaded successfully!")
        print_info(f"File metadata:")
        print_info(f"  - Key: {response.metadata.key}")
        print_info(f"  - Size: {response.metadata.size} bytes")
        print_info(f"  - Content-Type: {response.metadata.content_type}")
        print_info(f"  - Last Modified: {response.metadata.last_modified}")
        print_info(f"  - ETag: {response.metadata.etag}")

        return key
    finally:
        # Clean up the temporary file
        os.unlink(tmp_path)


def test_upload_bytes(client: R2Client, bucket_name: str) -> str:
    """Test uploading bytes data."""
    print_header("Testing upload_bytes()")

    key = "test-upload-bytes.txt"
    content = b"This is binary data uploaded as bytes.\nLine 2 of bytes data.\nLine 3 of bytes data."
    content_type = "text/plain"
    metadata = {"test": "true", "upload_method": "bytes"}

    print_info(f"Uploading bytes data -> {key}")
    print_info(f"Bucket: {bucket_name}")
    print_info(f"Content length: {len(content)} bytes")
    print_info(f"Content-Type: {content_type}")
    print_info(f"Metadata: {metadata}")

    response = client.upload_bytes(
        data=content,
        key=key,
        bucket_name=bucket_name,
        content_type=content_type,
        metadata=metadata,
    )

    print_success(f"Bytes uploaded successfully!")
    print_info(f"File metadata:")
    print_info(f"  - Key: {response.metadata.key}")
    print_info(f"  - Size: {response.metadata.size} bytes")
    print_info(f"  - Content-Type: {response.metadata.content_type}")

    return key


def test_download_file(client: R2Client, bucket_name: str, key: str) -> str:
    """Test downloading a file to local path."""
    print_header("Testing download_file()")

    # Create a temporary directory for downloads
    with tempfile.TemporaryDirectory() as temp_dir:
        download_path = os.path.join(temp_dir, "downloaded-file.txt")

        print_info(f"Downloading file: {key} -> {download_path}")
        print_info(f"Bucket: {bucket_name}")

        response = client.download_file(
            key=key, file_path=download_path, bucket_name=bucket_name
        )

        print_success(f"File downloaded successfully!")
        print_info(f"Downloaded to: {download_path}")
        print_info(f"File size: {len(response.content)} bytes")
        print_info(f"Content-Type: {response.metadata.content_type}")

        # Read and display the first few lines of the downloaded file
        with open(download_path, "r") as f:
            content = f.read()
            print_info(f"File content (first 100 chars): {content[:100]}...")

        return download_path


def test_download_bytes(client: R2Client, bucket_name: str, key: str) -> None:
    """Test downloading a file as bytes."""
    print_header("Testing download_bytes()")

    print_info(f"Downloading file as bytes: {key}")
    print_info(f"Bucket: {bucket_name}")

    response = client.download_bytes(key=key, bucket_name=bucket_name)

    print_success(f"Bytes downloaded successfully!")
    print_info(f"Downloaded {len(response.content)} bytes")
    print_info(f"Content-Type: {response.metadata.content_type}")

    # Display the downloaded content
    content_str = response.content.decode("utf-8", errors="ignore")
    print_info(f"Content (first 100 chars): {content_str[:100]}...")


def test_list_files(client: R2Client, bucket_name: str, prefix: str = "test-") -> None:
    """Test listing files in the bucket."""
    print_header("Testing list_files()")

    print_info(f"Listing files with prefix: '{prefix}'")
    print_info(f"Bucket: {bucket_name}")

    response = client.list_files(prefix=prefix, bucket_name=bucket_name, max_keys=10)

    print_success(f"List operation successful!")
    print_info(f"Found {len(response.files)} files:")

    for i, file_metadata in enumerate(response.files, 1):
        print_info(
            f"  {i}. {file_metadata.key} ({file_metadata.size} bytes, {file_metadata.last_modified})"
        )

    if response.is_truncated:
        print_info("Note: Result was truncated (more files available)")
    if response.continuation_token:
        print_info(f"Continuation token: {response.continuation_token}")


def test_file_exists(client: R2Client, bucket_name: str, key: str) -> None:
    """Test checking if a file exists."""
    print_header("Testing file_exists()")

    print_info(f"Checking if file exists: {key}")
    print_info(f"Bucket: {bucket_name}")

    exists = client.file_exists(key=key, bucket_name=bucket_name)

    if exists:
        print_success(f"File '{key}' exists in bucket '{bucket_name}'")
    else:
        print_error(f"File '{key}' does not exist in bucket '{bucket_name}'")

    # Also test with a non-existent file
    non_existent_key = "non-existent-file-12345.txt"
    exists = client.file_exists(key=non_existent_key, bucket_name=bucket_name)

    if not exists:
        print_success(f"Correctly identified that '{non_existent_key}' does not exist")
    else:
        print_error(f"Incorrectly identified that '{non_existent_key}' exists")


def test_generate_presigned_url(client: R2Client, bucket_name: str, key: str) -> None:
    """Test generating a presigned URL."""
    print_header("Testing generate_presigned_url()")

    print_info(f"Generating presigned URL for: {key}")
    print_info(f"Bucket: {bucket_name}")

    # Test GET URL
    response = client.generate_presigned_url(
        key=key,
        bucket_name=bucket_name,
        expiration=3600,  # 1 hour
        method="GET",
        inline=True,
    )

    print_success(f"Presigned URL generated successfully!")
    print_info(f"URL: {response.url}")
    print_info(f"Method: {response.method}")
    print_info(f"Expires in: {response.expires_in} seconds")
    print_info(f"Key: {response.key}")

    # Test PUT URL
    put_response = client.generate_presigned_url(
        key="test-upload-via-url.txt",
        bucket_name=bucket_name,
        expiration=1800,  # 30 minutes
        method="PUT",
    )

    print_info(f"\nPUT URL (for uploads): {put_response.url}")
    print_info(f"Method: {put_response.method}")


def test_delete_file(client: R2Client, bucket_name: str, key: str) -> None:
    """Test deleting a file."""
    print_header("Testing delete_file()")

    print_info(f"Deleting file: {key}")
    print_info(f"Bucket: {bucket_name}")

    # First verify the file exists
    if client.file_exists(key=key, bucket_name=bucket_name):
        print_info(f"File '{key}' exists, proceeding with deletion...")

        response = client.delete_file(key=key, bucket_name=bucket_name)

        print_success(f"File deleted successfully!")
        print_info(f"Message: {response.message}")
        print_info(f"Key: {response.key}")
        print_info(f"Bucket: {response.bucket}")

        # Verify the file is gone
        if not client.file_exists(key=key, bucket_name=bucket_name):
            print_success(f"Verified: File '{key}' no longer exists")
        else:
            print_error(f"File '{key}' still exists after deletion!")
    else:
        print_error(f"Cannot delete: File '{key}' does not exist")


def main():
    """Main test function."""
    print_header("R2 Client Test Suite")

    # Check environment variables
    if not check_environment_variables():
        sys.exit(1)

    # Get bucket name from environment or use default
    bucket_name = os.getenv("R2_BUCKET_NAME", "30aidev")
    print_info(f"Using bucket: {bucket_name}")
    print_info(f"R2 Account ID: {os.getenv('R2_ACCOUNT_ID')}")
    print_info(f"R2 Endpoint: {os.getenv('R2_S3_API')}")

    # Initialize the client
    try:
        print_info("Initializing R2Client...")
        client = R2Client(bucket_name=bucket_name)
        print_success("R2Client initialized successfully!")
    except Exception as e:
        print_error(f"Failed to initialize R2Client: {e}")
        sys.exit(1)

    # Run tests
    uploaded_files = []

    try:
        # Test 1: Upload file from path
        key1 = test_upload_file(client, bucket_name)
        uploaded_files.append(key1)

        # Test 2: Upload bytes
        key2 = test_upload_bytes(client, bucket_name)
        uploaded_files.append(key2)

        # Test 3: List files
        test_list_files(client, bucket_name)

        # Test 4: Check file existence
        test_file_exists(client, bucket_name, key1)

        # Test 5: Download file to path
        test_download_file(client, bucket_name, key1)

        # Test 6: Download file as bytes
        test_download_bytes(client, bucket_name, key2)

        # Test 7: Generate presigned URL
        test_generate_presigned_url(client, bucket_name, key1)

        # Test 8: Delete files (cleanup)
        print_header("Cleaning up test files")
        for key in uploaded_files:
            test_delete_file(client, bucket_name, key)

        # Final list to confirm cleanup
        test_list_files(client, bucket_name)

        print_header("All Tests Completed Successfully! 🎉")

    except Exception as e:
        print_error(f"Test failed with error: {e}")
        import traceback

        traceback.print_exc()

        # Try to clean up any uploaded files
        print_info("\nAttempting to clean up uploaded files...")
        for key in uploaded_files:
            try:
                if client.file_exists(key=key, bucket_name=bucket_name):
                    client.delete_file(key=key, bucket_name=bucket_name)
                    print_info(f"Cleaned up: {key}")
            except Exception as cleanup_error:
                print_error(f"Failed to clean up {key}: {cleanup_error}")

        sys.exit(1)


if __name__ == "__main__":
    main()

