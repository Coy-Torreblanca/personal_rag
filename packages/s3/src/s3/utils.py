"""Utility functions for S3/R2 operations."""

import os
import mimetypes
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime

from .models import FileType


def guess_content_type(filename: str, default: str = "application/octet-stream") -> str:
    """Guess content type from filename."""
    content_type, _ = mimetypes.guess_type(filename)
    return content_type or default


def get_file_type_from_extension(filename: str) -> FileType:
    """Get file type from file extension."""
    ext = Path(filename).suffix.lower()

    if ext == ".pdf":
        return FileType.PDF
    elif ext in [".doc", ".docx"]:
        return FileType.DOCX
    elif ext == ".txt":
        return FileType.TXT
    elif ext == ".csv":
        return FileType.CSV
    elif ext == ".json":
        return FileType.JSON
    elif ext in [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"]:
        return FileType.IMAGE
    elif ext in [".mp3", ".wav", ".ogg", ".flac"]:
        return FileType.AUDIO
    elif ext in [".mp4", ".avi", ".mov", ".wmv", ".flv"]:
        return FileType.VIDEO
    else:
        return FileType.OTHER


def generate_key(
    filename: str,
    prefix: Optional[str] = None,
    organization_id: Optional[str] = None,
    user_id: Optional[str] = None,
    timestamp: Optional[datetime] = None,
) -> str:
    """Generate a structured key for file storage.

    Format: {prefix}/{organization_id}/{user_id}/{timestamp}/{filename}
    """
    parts = []

    if prefix:
        parts.append(prefix.strip("/"))

    if organization_id:
        parts.append(organization_id)

    if user_id:
        parts.append(user_id)

    if timestamp:
        # Format: YYYY/MM/DD/HHMMSS
        parts.append(timestamp.strftime("%Y/%m/%d/%H%M%S"))

    # Add filename
    parts.append(os.path.basename(filename))

    return "/".join(parts)


def parse_key(key: str) -> Dict[str, str]:
    """Parse a structured key into its components."""
    parts = key.split("/")
    result = {}

    if len(parts) >= 1:
        result["filename"] = parts[-1]

    if len(parts) >= 2:
        # Try to parse timestamp from second-to-last part
        timestamp_part = parts[-2]
        try:
            # Check if it's in HHMMSS format
            if len(timestamp_part) == 6 and timestamp_part.isdigit():
                result["timestamp"] = timestamp_part
        except:
            pass

    if len(parts) >= 3:
        result["user_id"] = parts[-3]

    if len(parts) >= 4:
        result["organization_id"] = parts[-4]

    if len(parts) >= 5:
        result["prefix"] = "/".join(parts[:-4])

    return result


def validate_file_size(file_path: str, max_size_mb: int = 100) -> bool:
    """Validate file size."""
    size_bytes = os.path.getsize(file_path)
    size_mb = size_bytes / (1024 * 1024)
    return size_mb <= max_size_mb


def get_file_size(file_path: str) -> int:
    """Get file size in bytes."""
    return os.path.getsize(file_path)


def sanitize_filename(filename: str) -> str:
    """Sanitize filename for safe storage."""
    # Remove path traversal attempts
    filename = os.path.basename(filename)

    # Replace problematic characters
    problematic_chars = ["\\", "/", ":", "*", "?", '"', "<", ">", "|"]
    for char in problematic_chars:
        filename = filename.replace(char, "_")

    # Limit length
    if len(filename) > 255:
        name, ext = os.path.splitext(filename)
        filename = name[: 255 - len(ext)] + ext

    return filename


def format_file_size(size_bytes: int) -> str:
    """Format file size in human-readable format."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0  # pyright: ignore[reportAssignmentType]
    return f"{size_bytes:.2f} PB"

