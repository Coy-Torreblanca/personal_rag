"""Configuration class for R2 client."""

import os
from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass
class R2Config:
    """Configuration for Cloudflare R2 client."""

    account_id: str
    access_key_id: str
    secret_access_key: str
    endpoint_url: str
    bucket_name: str | None = None

    @classmethod
    def from_env(cls, bucket_name: str | None = None) -> "R2Config":
        """Create R2Config from environment variables."""
        account_id = os.getenv("R2_ACCOUNT_ID", "")
        s3_api_endpoint = os.getenv("R2_S3_API", "")

        return cls(
            account_id=account_id,
            access_key_id=os.getenv("R2_ACCESS_ID", ""),
            secret_access_key=os.getenv("R2_SECRET_ACCESS_KEY", ""),
            bucket_name=bucket_name,
            endpoint_url=s3_api_endpoint,
        )

    def validate(self) -> None:
        """Validate configuration."""
        if not self.account_id:
            raise ValueError("R2_ACCOUNT_ID is required")
        if not self.access_key_id:
            raise ValueError("R2_ACCESS_ID is required")
        if not self.secret_access_key:
            raise ValueError("R2_SECRET_ACCESS_KEY is required")

        # Parse endpoint URL to ensure it's valid
        try:
            parsed = urlparse(self.endpoint_url)
            if not parsed.scheme or not parsed.netloc:
                raise ValueError(f"Invalid endpoint URL: {self.endpoint_url}")
        except Exception as e:
            raise ValueError(f"Invalid endpoint URL: {self.endpoint_url}") from e
