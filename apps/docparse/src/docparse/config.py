"""Configuration management for DocParse."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Provider configuration
    docparse_provider: str = "docling"

    # API configuration
    api_title: str = "DocParse API"
    api_description: str = "Document parsing service that converts documents to markdown"
    api_version: str = "0.1.0"
    api_host: str = "0.0.0.0"
    api_port: int = 8001

    # Logging
    log_level: str = "INFO"


settings = Settings()
