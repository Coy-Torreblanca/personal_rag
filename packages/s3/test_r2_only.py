#!/usr/bin/env python3
"""Test the R2-only refactored package."""


def test_r2_imports():
    """Test that R2 modules can be imported."""
    print("Testing R2 imports...")

    try:
        from s3 import (
            R2Client,
            R2Config,
            create_r2_client,
            FileMetadata,
            UploadResponse,
            DownloadResponse,
            ListResponse,
            DeleteResponse,
            PresignedUrlResponse,
            FileType,
            S3Error,
            ConfigurationError,
            guess_content_type,
            generate_key,
            parse_key,
        )

        print("✓ All R2 imports successful!")
        return True
    except ImportError as e:
        print(f"✗ Import failed: {e}")
        return False
    except Exception as e:
        print(f"✗ Unexpected error: {e}")
        return False


if __name__ == "__main__":
    test_r2_imports()

