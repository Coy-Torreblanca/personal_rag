"""Factory functions for creating R2 clients."""

import os
from typing import Optional

from .client import R2Client
from .config import R2Config
from .exceptions import ConfigurationError


def create_r2_client(
    account_id: Optional[str] = None,
    access_key_id: Optional[str] = None,
    secret_access_key: Optional[str] = None,
    s3_api_endpoint: Optional[str] = None,
    bucket_name: Optional[str] = None,
    from_env: bool = True,
) -> R2Client:
    """Create an R2 client.

    Args:
        account_id: Cloudflare R2 account ID
        access_key_id: R2 access key ID
        secret_access_key: R2 secret access key
        s3_api_endpoint: Custom S3-compatible API endpoint for R2
        bucket_name: Default bucket name
        from_env: Whether to read missing values from environment variables

    Returns:
        R2Client instance
    """
    if from_env:
        config = R2Config.from_env(bucket_name)

        # Override with provided values
        if account_id:
            config.account_id = account_id
        if access_key_id:
            config.access_key_id = access_key_id
        if secret_access_key:
            config.secret_access_key = secret_access_key
        if s3_api_endpoint:
            config.s3_api_endpoint = s3_api_endpoint
        if bucket_name:
            config.bucket_name = bucket_name
    else:
        if not account_id or not access_key_id or not secret_access_key:
            raise ConfigurationError(
                "account_id, access_key_id and secret_access_key are required when from_env=False"
            )

        config = R2Config(
            account_id=account_id,
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
            s3_api_endpoint=s3_api_endpoint,
            bucket_name=bucket_name,
        )

    return R2Client(config)

