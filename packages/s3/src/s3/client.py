"""Main R2 client implementation."""

import boto3
from botocore.exceptions import ClientError
from datetime import datetime
from typing import Optional, Dict, Any

from .config import R2Config
from .exceptions import (
    ConfigurationError,
    BucketError,
    FileNotFoundError,
    UploadError,
    DownloadError,
    DeleteError,
    ListError,
    PresignedUrlError,
    S3Error,
)
from .models import (
    FileMetadata,
    UploadResponse,
    DownloadResponse,
    ListResponse,
    DeleteResponse,
    PresignedUrlResponse,
    FileType,
)


class R2Client:
    """Client for Cloudflare R2 operations."""

    config: R2Config

    def __init__(self, config: R2Config):
        self.config = config
        self._client = None
        self._resource = None
        config.validate()

    @property
    def client(self):
        """Lazy-loaded boto3 client."""
        if self._client is None:
            self._client = self._create_client()
        return self._client

    @property
    def resource(self):
        """Lazy-loaded boto3 resource."""
        if self._resource is None:
            self._resource = self._create_resource()
        return self._resource

    def _create_client(self):
        """Create boto3 client for R2."""
        return boto3.client(
            "s3",
            aws_access_key_id=self.config.access_key_id,
            aws_secret_access_key=self.config.secret_access_key,
            region_name="auto",  # R2 uses "auto" region
            endpoint_url=self.config.endpoint_url,
        )

    def _create_resource(self):
        """Create boto3 resource for R2."""
        return boto3.resource(
            "s3",
            aws_access_key_id=self.config.access_key_id,
            aws_secret_access_key=self.config.secret_access_key,
            region_name="auto",  # R2 uses "auto" region
            endpoint_url=self.config.endpoint_url,
        )

    def validate_bucket(self, bucket_name: Optional[str] = None) -> str:
        """Validate and return bucket name."""
        bucket = bucket_name or self.config.bucket_name
        if not bucket:
            raise ConfigurationError("Bucket name is required")
        return bucket

    def _handle_client_error(self, error: ClientError, operation: str) -> None:
        """Handle boto3 ClientError and raise appropriate exception."""
        error_code = error.response.get("Error", {}).get("Code", "")
        error_message = error.response.get("Error", {}).get("Message", "")

        if error_code == "NoSuchBucket":
            raise BucketError(f"Bucket does not exist: {error_message}")
        elif error_code == "NoSuchKey":
            raise FileNotFoundError(f"File not found: {error_message}")
        elif error_code == "AccessDenied":
            raise ConfigurationError(f"Access denied: {error_message}")
        else:
            # Map operation to specific error class
            error_map = {
                "Upload": UploadError,
                "Download": DownloadError,
                "Delete": DeleteError,
                "List": ListError,
                "Generate presigned URL": PresignedUrlError,
            }

            # Default to S3Error if operation not in map
            error_class = error_map.get(operation, S3Error)
            raise error_class(f"{operation} failed: {error_message}")

    def upload_file(
        self,
        file_path: str,
        key: str,
        bucket_name: str,
        content_type: str,
        metadata: dict[str, str] | None = None,
    ) -> UploadResponse | None:
        """Upload a file from local path."""
        bucket = self.validate_bucket(bucket_name)

        try:
            extra_args = {}
            if content_type:
                extra_args["ContentType"] = content_type
            if metadata:
                extra_args["Metadata"] = metadata

            response  = self.client.upload_file(file_path, bucket, key, ExtraArgs=extra_args)

            file_metadata = FileMetadata.from_s3_upload_response(response, bucket, content_type, key, metadata)

            return UploadResponse(
                metadata=file_metadata,
                success=True
            )
        except ClientError as e:
            self._handle_client_error(e, "Upload")
        except Exception as e:
            raise UploadError(f"Upload failed: {str(e)}") from e

    def upload_bytes(
        self,
        data: bytes,
        key: str,
        bucket_name: Optional[str] = None,
        content_type: Optional[str] = None,
        metadata: Optional[Dict[str, str]] = None,
    ) -> UploadResponse | None:
        """Upload bytes data."""
        bucket = self.validate_bucket(bucket_name)

        try:
            extra_args = {}
            if content_type:
                extra_args["ContentType"] = content_type
            if metadata:
                extra_args["Metadata"] = metadata

            response: dict[str, Any] = self.client.put_object(
                Bucket=bucket, Key=key, Body=data, **extra_args
            )

            etag: str | None = response.get("ETag")
            size: int | None = response.get("Size")

            if not etag or not size:
                raise ValueError(f"response did have required data: {response!r}")

            FileMetadata = 

            return UploadResponse(
                key=key,
                bucket=bucket,
                metadata=metadata or {},
                etag=etag,
                size=size,
                success=True,
            )
        except ClientError as e:
            self._handle_client_error(e, "Upload")
        except Exception as e:
            raise UploadError(f"Upload failed: {str(e)}") from e

    def download_file(
        self,
        key: str,
        file_path: str,
        bucket_name: Optional[str] = None,
    ) -> DownloadResponse:
        """Download a file to local path."""
        bucket = self.validate_bucket(bucket_name)

        try:
            self.client.download_file(bucket, key, file_path)

            # Get object metadata
            response = self.client.head_object(Bucket=bucket, Key=key)
            metadata = response.get("Metadata", {})
            content_type = response.get("ContentType")
            size = response.get("ContentLength", 0)

            return DownloadResponse(
                key=key,
                bucket=bucket,
                file_path=file_path,
                metadata=metadata,
                content_type=content_type,
                size=size,
            )
        except ClientError as e:
            self._handle_client_error(e, "Download")
        except Exception as e:
            raise DownloadError(f"Download failed: {str(e)}") from e

    def download_bytes(
        self,
        key: str,
        bucket_name: Optional[str] = None,
    ) -> DownloadResponse:
        """Download file as bytes."""
        bucket = self.validate_bucket(bucket_name)

        try:
            response = self.client.get_object(Bucket=bucket, Key=key)
            data = response["Body"].read()

            metadata = response.get("Metadata", {})
            content_type = response.get("ContentType")
            size = len(data)

            return DownloadResponse(
                key=key,
                bucket=bucket,
                data=data,
                metadata=metadata,
                content_type=content_type,
                size=size,
            )
        except ClientError as e:
            self._handle_client_error(e, "Download")
        except Exception as e:
            raise DownloadError(f"Download failed: {str(e)}") from e

    def delete_file(
        self,
        key: str,
        bucket_name: Optional[str] = None,
    ) -> DeleteResponse:
        """Delete a file."""
        bucket = self.validate_bucket(bucket_name)

        try:
            self.client.delete_object(Bucket=bucket, Key=key)

            return DeleteResponse(
                key=key,
                bucket=bucket,
                deleted=True,
            )
        except ClientError as e:
            self._handle_client_error(e, "Delete")
        except Exception as e:
            raise DeleteError(f"Delete failed: {str(e)}") from e

    def list_files(
        self,
        prefix: Optional[str] = None,
        bucket_name: Optional[str] = None,
        max_keys: int = 1000,
    ) -> ListResponse:
        """List files in bucket."""
        bucket = self.validate_bucket(bucket_name)

        try:
            paginator = self.client.get_paginator("list_objects_v2")
            files = []

            for page in paginator.paginate(
                Bucket=bucket,
                Prefix=prefix or "",
                PaginationConfig={"MaxItems": max_keys},
            ):
                for obj in page.get("Contents", []):
                    files.append(
                        FileMetadata(
                            key=obj["Key"],
                            size=obj["Size"],
                            last_modified=obj["LastModified"],
                            etag=obj["ETag"],
                        )
                    )

            return ListResponse(
                bucket=bucket,
                prefix=prefix,
                files=files,
                count=len(files),
            )
        except ClientError as e:
            self._handle_client_error(e, "List")
        except Exception as e:
            raise ListError(f"List failed: {str(e)}") from e

    def generate_presigned_url(
        self,
        key: str,
        expiration: int = 3600,
        bucket_name: Optional[str] = None,
    ) -> PresignedUrlResponse:
        """Generate a presigned URL for temporary access."""
        bucket = self.validate_bucket(bucket_name)

        try:
            url = self.client.generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket, "Key": key},
                ExpiresIn=expiration,
            )

            return PresignedUrlResponse(
                key=key,
                bucket=bucket,
                url=url,
                expiration=expiration,
            )
        except ClientError as e:
            self._handle_client_error(e, "Generate presigned URL")
        except Exception as e:
            raise PresignedUrlError(f"Generate presigned URL failed: {str(e)}") from e

    def file_exists(
        self,
        key: str,
        bucket_name: Optional[str] = None,
    ) -> bool:
        """Check if a file exists."""
        bucket = self.validate_bucket(bucket_name)

        try:
            self.client.head_object(Bucket=bucket, Key=key)
            return True
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "404":
                return False
            raise
        except Exception:
            return False
