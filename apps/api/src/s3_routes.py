"""S3/R2 CRUD operations routes for the API."""

import io
import json
import os
from typing import Annotated, Optional, List

from fastapi import APIRouter, Form, HTTPException, UploadFile, File, Query
from s3 import R2Client
from s3.exceptions import S3Error

# Create router for S3 operations
router = APIRouter(prefix="/s3", tags=["S3 Operations"])


# Initialize R2 client with default bucket
def get_s3_client(bucket_name: Optional[str] = None) -> R2Client:
    """Get S3/R2 client instance."""
    bucket = bucket_name or os.getenv("S3_BUCKET_NAME", "documents")
    try:
        return R2Client(bucket_name=bucket)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to initialize S3 client: {str(e)}"
        )


# ==================== CREATE (Upload) Operations ====================


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    key: Optional[str] = Query(None),
    bucket_name: Optional[str] = Query(None),
):
    """
    Upload a file to S3/R2.

    - **file**: The file to upload
    - **key**: S3 object key/path (defaults to filename if not provided)
    - **bucket_name**: Target bucket name (defaults to S3_BUCKET_NAME env var)
    """
    try:
        client = get_s3_client(bucket_name)

        # Use provided key or filename
        object_key = key or file.filename
        if not object_key:
            raise HTTPException(status_code=400, detail="Key or filename is required")

        # Read file content
        content = await file.read()

        # Upload to S3
        response = client.upload_bytes(
            data=content,
            key=object_key,
            bucket_name=bucket_name,
            content_type=file.content_type,
        )

        return {
            "success": True,
            "message": "File uploaded successfully",
            "bucket": response.metadata.bucket,
            "key": response.metadata.key,
            "size": response.metadata.size,
            "content_type": response.metadata.content_type,
            "last_modified": response.metadata.last_modified.isoformat()
            if response.metadata.last_modified
            else None,
        }
    except S3Error as e:
        raise HTTPException(status_code=400, detail=f"S3 operation failed: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")


# ==================== READ Operations ====================


@router.get("/download/{key:path}")
async def download_file(
    key: str,
    bucket_name: Optional[str] = Query(None),
):
    """
    Download a file from S3/R2.

    - **key**: S3 object key/path
    - **bucket_name**: Source bucket name

    Returns the file content as bytes.
    """
    try:
        client = get_s3_client(bucket_name)

        response = client.download_bytes(
            key=key,
            bucket_name=bucket_name,
        )

        return {
            "success": True,
            "message": "File downloaded successfully",
            "bucket": response.metadata.bucket,
            "key": response.metadata.key,
            "size": response.metadata.size,
            "content": response.content.decode("utf-8", errors="replace")
            if response.content
            else None,
            "content_type": response.metadata.content_type,
        }
    except S3Error as e:
        raise HTTPException(status_code=400, detail=f"S3 operation failed: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")


@router.get("/list")
async def list_files(
    prefix: Optional[str] = Query(None),
    bucket_name: Optional[str] = Query(None),
    max_keys: int = Query(1000, ge=1, le=1000),
    continuation_token: Optional[str] = Query(None),
):
    """
    List files in S3/R2 bucket.

    - **prefix**: Filter by key prefix (e.g., "documents/")
    - **bucket_name**: Target bucket name
    - **max_keys**: Maximum number of keys to return (1-1000)
    - **continuation_token**: Token for pagination
    """
    try:
        client = get_s3_client(bucket_name)

        response = client.list_files(
            prefix=prefix,
            bucket_name=bucket_name,
            max_keys=max_keys,
            continuation_token=continuation_token,
        )

        files_info = [
            {
                "key": f.key,
                "size": f.size,
                "last_modified": f.last_modified.isoformat()
                if f.last_modified
                else None,
                "etag": f.etag,
                "content_type": f.content_type,
            }
            for f in response.files
        ]

        return {
            "success": True,
            "bucket": response.bucket,
            "prefix": prefix,
            "files": files_info,
            "count": len(files_info),
            "is_truncated": response.is_truncated,
            "continuation_token": response.continuation_token,
        }
    except S3Error as e:
        raise HTTPException(status_code=400, detail=f"S3 operation failed: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"List operation failed: {str(e)}")


@router.get("/metadata/{key:path}")
async def get_file_metadata(
    key: str,
    bucket_name: Optional[str] = Query(None),
):
    """
    Get metadata for a file in S3/R2.

    - **key**: S3 object key/path
    - **bucket_name**: Source bucket name
    """
    try:
        client = get_s3_client(bucket_name)

        # Use head_object to get metadata without downloading the file
        response = client.client.head_object(
            Bucket=bucket_name or client.config.bucket_name,
            Key=key,
        )

        return {
            "success": True,
            "bucket": bucket_name or client.config.bucket_name,
            "key": key,
            "size": response.get("ContentLength", 0),
            "content_type": response.get("ContentType"),
            "last_modified": response.get("LastModified").isoformat()
            if response.get("LastModified")
            else None,
            "etag": response.get("ETag"),
            "storage_class": response.get("StorageClass"),
            "metadata": response.get("Metadata", {}),
        }
    except S3Error as e:
        raise HTTPException(status_code=400, detail=f"S3 operation failed: {str(e)}")
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Metadata retrieval failed: {str(e)}"
        )


@router.get("/presigned-url/{key:path}")
async def generate_presigned_url(
    key: str,
    bucket_name: Optional[str] = Query(None),
    expiration: int = Query(3600, ge=1, le=604800),
    method: str = Query("GET", pattern="^(GET|PUT)$"),
    inline: bool = Query(False),
):
    """
    Generate a presigned URL for temporary access to a file.

    - **key**: S3 object key/path
    - **bucket_name**: Target bucket name
    - **expiration**: URL expiration time in seconds (1 - 604800, default 3600)
    - **method**: HTTP method (GET or PUT)
    - **inline**: Whether to return the file inline (for GET requests)
    """
    try:
        client = get_s3_client(bucket_name)

        response = client.generate_presigned_url(
            key=key,
            expiration=expiration,
            bucket_name=bucket_name,
            method=method,
            inline=inline,
        )

        return {
            "success": True,
            "url": response.url,
            "bucket": response.bucket,
            "key": response.key,
            "method": response.method,
            "expires_in": response.expires_in,
            "message": response.message,
        }
    except S3Error as e:
        raise HTTPException(status_code=400, detail=f"S3 operation failed: {str(e)}")
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Presigned URL generation failed: {str(e)}"
        )


# ==================== UPDATE Operations ====================


@router.put("/update/{key:path}")
async def update_file(
    key: str,
    file: UploadFile = File(...),
    bucket_name: Optional[str] = Query(None),
    metadata: Annotated[
        str | None,
        Form(
            description="A JSON-encoded string of metadata tags",
            examples=['{"version": "1.0", "project": "30ai"}'],
        ),
    ] = None,
):
    """
    Update a file in S3/R2 (replaces existing file).

    - **key**: S3 object key/path
    - **file**: The new file content
    - **bucket_name**: Target bucket name
    - **metadata**: Optional metadata dict as JSON string
    """
    try:
        json_metadata = None
        if metadata:
            try:
                json_metadata = json.loads(metadata)

            except json.JSONDecodeError:
                raise HTTPException(status_code=400, detail="Invalid JSON in metadata")

        client = get_s3_client(bucket_name)

        content = await file.read()

        # Upload file (this will overwrite if key exists)
        response = client.upload_bytes(
            data=content,
            key=key,
            bucket_name=bucket_name,
            content_type=file.content_type,
            metadata=json_metadata or None,
        )

        return {
            "success": True,
            "message": "File updated successfully",
            "bucket": response.metadata.bucket,
            "key": response.metadata.key,
            "size": response.metadata.size,
            "content_type": response.metadata.content_type,
        }
    except S3Error as e:
        raise HTTPException(status_code=400, detail=f"S3 operation failed: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Update failed: {str(e)}")


# ==================== DELETE Operations ====================


@router.delete("/delete/{key:path}")
async def delete_file(
    key: str,
    bucket_name: Optional[str] = Query(None),
):
    """
    Delete a file from S3/R2.

    - **key**: S3 object key/path
    - **bucket_name**: Target bucket name
    """
    try:
        client = get_s3_client(bucket_name)

        response = client.delete_file(
            key=key,
            bucket_name=bucket_name,
        )

        return {
            "success": True,
            "message": response.message,
            "bucket": response.bucket,
            "key": response.key,
            "version_id": response.version_id,
            "delete_marker": response.delete_marker,
        }
    except S3Error as e:
        raise HTTPException(status_code=400, detail=f"S3 operation failed: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Delete failed: {str(e)}")


@router.delete("/delete-multiple")
async def delete_multiple_files(
    keys: List[str] = Query(...),
    bucket_name: Optional[str] = Query(None),
):
    """
    Delete multiple files from S3/R2.

    - **keys**: List of S3 object keys to delete
    - **bucket_name**: Target bucket name
    """
    try:
        client = get_s3_client(bucket_name)

        results = []
        for key in keys:
            try:
                response = client.delete_file(
                    key=key,
                    bucket_name=bucket_name,
                )
                results.append(
                    {
                        "key": key,
                        "success": True,
                        "message": response.message,
                    }
                )
            except S3Error as e:
                results.append(
                    {
                        "key": key,
                        "success": False,
                        "error": str(e),
                    }
                )

        successful = sum(1 for r in results if r["success"])
        failed = len(results) - successful

        return {
            "success": failed == 0,
            "message": f"Deleted {successful}/{len(results)} files",
            "total": len(results),
            "successful": successful,
            "failed": failed,
            "results": results,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Batch delete failed: {str(e)}")


# ==================== Utility Operations ====================


@router.get("/bucket-info")
async def get_bucket_info(bucket_name: Optional[str] = Query(None)):
    """
    Get information about the S3/R2 bucket.

    - **bucket_name**: Target bucket name
    """
    try:
        client = get_s3_client(bucket_name)

        bucket = bucket_name or client.config.bucket_name

        # List all objects to get bucket stats
        response = client.list_files(bucket_name=bucket, max_keys=1)

        return {
            "success": True,
            "bucket": bucket,
            "endpoint": client.config.endpoint_url,
            "region": "auto",  # R2 uses auto region
        }
    except S3Error as e:
        raise HTTPException(status_code=400, detail=f"S3 operation failed: {str(e)}")
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Bucket info retrieval failed: {str(e)}"
        )


@router.post("/copy/{source_key:path}")
async def copy_file(
    source_key: str,
    destination_key: Optional[str] = Query(None),
    bucket_name: Optional[str] = Query(None),
):
    """
    Copy a file within S3/R2 (for same bucket or cross-bucket).

    - **source_key**: Source file key
    - **destination_key**: Destination file key (defaults to source_key if not provided)
    - **bucket_name**: Bucket name (uses same bucket for source and destination)
    """
    try:
        client = get_s3_client(bucket_name)
        bucket = bucket_name or client.config.bucket_name
        dest_key = destination_key or source_key

        # Copy object within bucket
        client.client.copy_object(
            Bucket=bucket,
            CopySource={"Bucket": bucket, "Key": source_key},
            Key=dest_key,
        )

        return {
            "success": True,
            "message": "File copied successfully",
            "bucket": bucket,
            "source_key": source_key,
            "destination_key": dest_key,
        }
    except S3Error as e:
        raise HTTPException(status_code=400, detail=f"S3 operation failed: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Copy operation failed: {str(e)}")
