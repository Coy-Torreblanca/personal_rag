#!/usr/bin/env python3
"""
Basic example of R2Client operations.

This example shows the minimal code needed to:
1. Upload a file
2. Download a file  
3. Delete a file

Make sure to set the required environment variables before running.
"""

import os
import tempfile
import sys

# Add the src directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from s3.client import R2Client


def main():
    """Basic example of R2 operations."""
    print("=== R2 Client Basic Example ===\n")
    
    # Check for required environment variables
    required_vars = ["R2_ACCOUNT_ID", "R2_ACCESS_ID", "R2_SECRET_ACCESS_KEY", "R2_S3_API"]
    for var in required_vars:
        if not os.getenv(var):
            print(f"❌ Error: {var} environment variable is not set")
            print("Please set the following environment variables:")
            print("  - R2_ACCOUNT_ID: Your Cloudflare R2 account ID")
            print("  - R2_ACCESS_ID: Your R2 access key ID")
            print("  - R2_SECRET_ACCESS_KEY: Your R2 secret access key")
            print("  - R2_S3_API: Your R2 S3 API endpoint URL")
            return
    
    # Use bucket from environment or default
    bucket_name = os.getenv("R2_BUCKET_NAME", "my-test-bucket")
    print(f"Using bucket: {bucket_name}")
    
    # Initialize client
    try:
        client = R2Client(bucket_name=bucket_name)
        print("✅ Client initialized successfully")
    except Exception as e:
        print(f"❌ Failed to initialize client: {e}")
        return
    
    # Create a test file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("Hello from R2 Client!\n")
        f.write("This is a test file.\n")
        f.write("Upload, download, and delete example.\n")
        test_file_path = f.name
    
    test_key = "example-test-file.txt"
    
    try:
        print(f"\n1. Uploading file: {test_file_path} -> {test_key}")
        
        # Upload the file
        upload_response = client.upload_file(
            file_path=test_file_path,
            key=test_key,
            bucket_name=bucket_name,
            content_type="text/plain",
            metadata={"example": "true", "purpose": "demo"}
        )
        
        print(f"✅ Upload successful!")
        print(f"   File size: {upload_response.metadata.size} bytes")
        print(f"   Content-Type: {upload_response.metadata.content_type}")
        print(f"   ETag: {upload_response.metadata.etag}")
        
        print(f"\n2. Checking if file exists...")
        exists = client.file_exists(key=test_key, bucket_name=bucket_name)
        print(f"✅ File exists: {exists}")
        
        print(f"\n3. Downloading file as bytes...")
        download_response = client.download_bytes(
            key=test_key,
            bucket_name=bucket_name
        )
        
        print(f"✅ Download successful!")
        print(f"   Downloaded {len(download_response.content)} bytes")
        
        # Show the downloaded content
        content = download_response.content.decode('utf-8')
        print(f"   Content:\n{'-'*40}")
        print(content.rstrip())
        print(f"{'-'*40}")
        
        print(f"\n4. Listing files in bucket...")
        list_response = client.list_files(
            prefix="example-",
            bucket_name=bucket_name
        )
        
        print(f"✅ Found {len(list_response.files)} file(s):")
        for file_meta in list_response.files:
            print(f"   - {file_meta.key} ({file_meta.size} bytes)")
        
        print(f"\n5. Deleting file: {test_key}")
        delete_response = client.delete_file(
            key=test_key,
            bucket_name=bucket_name
        )
        
        print(f"✅ Delete successful!")
        print(f"   Message: {delete_response.message}")
        
        print(f"\n6. Verifying file is deleted...")
        exists = client.file_exists(key=test_key, bucket_name=bucket_name)
        print(f"✅ File exists after deletion: {exists} (should be False)")
        
        if not exists:
            print("\n🎉 All operations completed successfully!")
        else:
            print("\n⚠️  File still exists after deletion!")
            
    except Exception as e:
        print(f"\n❌ Error during operations: {e}")
        import traceback
        traceback.print_exc()
        
    finally:
        # Clean up the temporary file
        if os.path.exists(test_file_path):
            os.unlink(test_file_path)
            print(f"\nCleaned up temporary file: {test_file_path}")


if __name__ == "__main__":
    main()