"""Main R2 client implementation."""

import logging

import boto3
from botocore.exceptions import ClientError
from typing import Any

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
)

logger = logging.getLogger(__name__)


class R2Client:
    """Client for Cloudflare R2 operations."""

    config: R2Config
    _client: Any | None
    _resource: Any | None

    def __init__(self, bucket_name: str):
        self.config = R2Config.from_env(bucket_name=bucket_name)
        self._client = None
        self._resource = None
        self.config.validate()
        logger.debug("R2Client initialized for bucket %s", bucket_name)

    @property
    def client(self) -> Any:
        """Lazy-loaded boto3 client."""
        if self._client is None:
            self._client = self._create_client()
        return self._client

    @property
    def resource(self) -> Any:
        """Lazy-loaded boto3 resource."""
        if self._resource is None:
            self._resource = self._create_resource()
        return self._resource

    def _create_client(self) -> Any:
        """Create boto3 client for R2."""
        return boto3.client(
            "s3",
            aws_access_key_id=self.config.access_key_id,
            aws_secret_access_key=self.config.secret_access_key,
            region_name="auto",  # R2 uses "auto" region
            endpoint_url=self.config.endpoint_url,
        )

    def _create_resource(self) -> Any:
        """Create boto3 resource for R2."""
        return boto3.resource(
            "s3",
            aws_access_key_id=self.config.access_key_id,
            aws_secret_access_key=self.config.secret_access_key,
            region_name="auto",  # R2 uses "auto" region
            endpoint_url=self.config.endpoint_url,
        )

    def _validate_bucket(self) -> str:
        """Validate and return bucket name from config."""
        if not self.config.bucket_name:
            raise ConfigurationError("Bucket name is required")
        return self.config.bucket_name

    def _handle_client_error(self, error: ClientError, operation: str) -> None:
        """Handle boto3 ClientError and raise appropriate exception."""
        error_code: str = error.response.get("Error", {}).get("Code", "")
        error_message: str = error.response.get("Error", {}).get("Message", "")

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
        content_type: str,
        metadata: dict[str, str] | None = None,
    ) -> UploadResponse:
        """Upload a file from local path."""
        bucket = self._validate_bucket()

        logger.info("Uploading file %s -> s3://%s/%s", file_path, bucket, key)

        try:
            extra_args = {}
            if content_type:
                extra_args["ContentType"] = content_type
            if metadata:
                extra_args["Metadata"] = metadata

            # upload_file doesn't return a response, so we need to get metadata separately
            self.client.upload_file(file_path, bucket, key, ExtraArgs=extra_args)

            # Get the uploaded file metadata
            response = self.client.head_object(Bucket=bucket, Key=key)

            file_metadata = FileMetadata.from_s3_object_response(
                response=response,
                bucket=bucket,
                key=key,
            )

            logger.info("Uploaded file s3://%s/%s (%d bytes)", bucket, key, file_metadata.size)

            return UploadResponse(metadata=file_metadata, success=True)
        except ClientError as e:
            logger.error("Upload failed for s3://%s/%s: %s", bucket, key, e)
            self._handle_client_error(e, "Upload")
            raise
        except Exception as e:
            logger.exception("Upload failed unexpectedly for s3://%s/%s", bucket, key)
            raise UploadError(f"Upload failed: {str(e)}") from e

    def upload_bytes(
        self,
        data: bytes,
        key: str,
        content_type: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> UploadResponse:
        """Upload bytes data."""
        bucket = self._validate_bucket()

        logger.info("Uploading %d bytes -> s3://%s/%s", len(data), bucket, key)

        try:
            extra_args = {}
            if content_type:
                extra_args["ContentType"] = content_type
            if metadata:
                extra_args["Metadata"] = metadata

            self.client.put_object(Bucket=bucket, Key=key, Body=data, **extra_args)

            # put_object returns minimal response, need to get full metadata
            head_response = self.client.head_object(Bucket=bucket, Key=key)

            file_metadata = FileMetadata.from_s3_object_response(
                response=head_response,
                bucket=bucket,
                key=key,
            )

            logger.info("Uploaded %d bytes to s3://%s/%s", len(data), bucket, key)

            return UploadResponse(metadata=file_metadata, success=True)
        except ClientError as e:
            logger.error("Bytes upload failed for s3://%s/%s: %s", bucket, key, e)
            self._handle_client_error(e, "Upload")
            raise
        except Exception as e:
            logger.exception("Bytes upload failed unexpectedly for s3://%s/%s", bucket, key)
            raise UploadError(f"Upload failed: {str(e)}") from e

    def download_file(
        self,
        key: str,
        file_path: str,
    ) -> DownloadResponse:
        """Download a file to local path."""
        bucket = self._validate_bucket()

        logger.info("Downloading s3://%s/%s -> %s", bucket, key, file_path)

        try:
            self.client.download_file(bucket, key, file_path)

            # Get object metadata
            response = self.client.head_object(Bucket=bucket, Key=key)
            file_metadata = FileMetadata.from_s3_object_response(
                response=response,
                bucket=bucket,
                key=key,
            )

            # Read the downloaded file content
            with open(file_path, "rb") as f:
                content = f.read()

            logger.info("Downloaded s3://%s/%s (%d bytes)", bucket, key, len(content))

            return DownloadResponse(
                success=True,
                content=content,
                metadata=file_metadata,
            )
        except ClientError as e:
            self._handle_client_error(e, "Download")
            raise
        except Exception as e:
            logger.exception("Download failed for s3://%s/%s", bucket, key)
            raise DownloadError(f"Download failed: {str(e)}") from e

    def download_bytes(
        self,
        key: str,
    ) -> DownloadResponse:
        """Download file as bytes."""
        bucket = self._validate_bucket()

        logger.debug("Downloading s3://%s/%s as bytes", bucket, key)

        try:
            response = self.client.get_object(Bucket=bucket, Key=key)
            data = response["Body"].read()

            file_metadata = FileMetadata.from_s3_object_response(
                response=response,
                bucket=bucket,
                key=key,
            )

            logger.debug("Downloaded %d bytes from s3://%s/%s", len(data), bucket, key)

            return DownloadResponse(
                success=True,
                content=data,
                metadata=file_metadata,
            )
        except ClientError as e:
            self._handle_client_error(e, "Download")
            raise
        except Exception as e:
            logger.exception("Bytes download failed for s3://%s/%s", bucket, key)
            raise DownloadError(f"Download failed: {str(e)}") from e

    def delete_file(
        self,
        key: str,
    ) -> DeleteResponse:
        """Delete a file."""
        bucket = self._validate_bucket()

        logger.info("Deleting s3://%s/%s", bucket, key)

        try:
            response = self.client.delete_object(Bucket=bucket, Key=key)

            # Parse delete response
            version_id = response.get("VersionId")
            delete_marker = response.get("DeleteMarker", False)
            request_charged = response.get("RequestCharged")

            logger.info("Deleted s3://%s/%s", bucket, key)

            return DeleteResponse(
                success=True,
                key=key,
                bucket=bucket,
                message=f"File deleted successfully{', version: ' + version_id if version_id else ''}",
                version_id=version_id,
                delete_marker=delete_marker,
            )
        except ClientError as e:
            self._handle_client_error(e, "Delete")
            raise
        except Exception as e:
            logger.exception("Delete failed for s3://%s/%s", bucket, key)
            raise DeleteError(f"Delete failed: {str(e)}") from e

    def list_files(
        self,
        prefix: str | None = None,
        max_keys: int = 1000,
        continuation_token: str | None = None,
    ) -> ListResponse:
        """List files in bucket."""
        bucket = self._validate_bucket()

        logger.debug("Listing files in s3://%s with prefix=%r", bucket, prefix)

        try:
            params = {"Bucket": bucket, "Prefix": prefix or "", "MaxKeys": max_keys}

            if continuation_token:
                params["ContinuationToken"] = continuation_token

            response = self.client.list_objects_v2(**params)

            files = [
                FileMetadata.from_s3_list_object(obj=obj, bucket=bucket)
                for obj in response.get("Contents", [])
            ]
            is_truncated = response.get("IsTruncated", False)
            continuation_token = response.get("NextContinuationToken")

            logger.debug("Listed %d files in s3://%s with prefix=%r", len(files), bucket, prefix)

            return ListResponse(
                success=True,
                bucket=bucket,
                files=files,
                prefix=prefix,
                continuation_token=continuation_token,
                is_truncated=is_truncated,
            )
        except ClientError as e:
            self._handle_client_error(e, "List")
            raise
        except Exception as e:
            logger.exception("List failed for prefix %r", prefix)
            raise ListError(f"List failed for prefix '{prefix}': {str(e)}") from e

    def generate_presigned_url(
        self,
        key: str,
        expiration: int = 3600,
        method: str = "GET",
        inline: bool = False,
        content_type: str | None = None,
    ) -> PresignedUrlResponse:
        """Generate a presigned URL for temporary access."""
        bucket = self._validate_bucket()

        logger.debug("Generating presigned %s URL for s3://%s/%s", method, bucket, key)

        try:
            # Map method to appropriate client method
            client_method = "get_object" if method.upper() == "GET" else "put_object"

            params = {"Bucket": bucket, "Key": key}

            if content_type:
                params["ContentType"] = content_type

            if inline:
                params["ResponseContentDisposition"] = "inline"

            url = self.client.generate_presigned_url(
                client_method,
                Params=params,
                ExpiresIn=expiration,
            )

            return PresignedUrlResponse(
                success=True,
                key=key,
                bucket=bucket,
                url=url,
                expires_in=expiration,
                method=method.upper(),
                message=f"Presigned URL generated for {method.upper()} operation",
            )
        except ClientError as e:
            self._handle_client_error(e, "Generate presigned URL")
            raise
        except Exception as e:
            logger.exception("Presigned URL generation failed for s3://%s/%s", bucket, key)
            raise PresignedUrlError(f"Generate presigned URL failed: {str(e)}") from e

    def file_exists(
        self,
        key: str,
    ) -> bool:
        """Check if a file exists."""
        bucket = self._validate_bucket()

        try:
            self.client.head_object(Bucket=bucket, Key=key)
            return True
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "404":
                return False
            logger.error("Error checking file existence for s3://%s/%s: %s", bucket, key, e)
            raise
        except Exception:
            logger.exception("Unexpected error checking file existence for s3://%s/%s", bucket, key)
            return False
