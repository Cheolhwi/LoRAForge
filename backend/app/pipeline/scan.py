from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from pathlib import Path
from time import sleep
from typing import Any

from PIL import Image, UnidentifiedImageError

from .types import ImageRecord

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
DEFAULT_READ_ATTEMPTS = 3
DEFAULT_RETRY_DELAY_SECONDS = 0.25

logger = logging.getLogger(__name__)

ScanStats = dict[str, Any]
ScanProgressCallback = Callable[[int, int, ScanStats], None]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def scan_images(
    source_dir: Path,
    minimum_pixels: int,
    *,
    deduplicate: bool = True,
    resolution_filter: bool = True,
    on_progress: ScanProgressCallback | None = None,
    read_attempts: int = DEFAULT_READ_ATTEMPTS,
    retry_delay_seconds: float = DEFAULT_RETRY_DELAY_SECONDS,
) -> tuple[list[ImageRecord], ScanStats]:
    if not source_dir.exists() or not source_dir.is_dir():
        raise ValueError(f"source_dir is not a directory: {source_dir}")
    if read_attempts < 1:
        raise ValueError("read_attempts must be at least 1")
    if retry_delay_seconds < 0:
        raise ValueError("retry_delay_seconds cannot be negative")

    image_paths = [
        path
        for path in sorted(source_dir.rglob("*"))
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    ]
    records: list[ImageRecord] = []
    seen_hashes: dict[str, Path] = {}
    stats = {
        "files_found": len(image_paths),
        "files_processed": 0,
        "duplicates": 0,
        "invalid_images": 0,
        "read_retries": 0,
        "read_failures": 0,
        "read_failure_details": [],
        "resolution_rejected": 0,
        "unique_images": 0,
        "embedding_candidates": 0,
        "minimum_pixels": minimum_pixels,
        "deduplicate_enabled": deduplicate,
        "resolution_filter_enabled": resolution_filter,
    }

    def report_progress() -> None:
        if on_progress is None:
            return
        snapshot = dict(stats)
        snapshot["read_failure_details"] = list(stats["read_failure_details"])
        on_progress(stats["files_processed"], len(image_paths), snapshot)

    report_progress()
    for path in image_paths:
        file_hash: str | None = None
        width = 0
        height = 0
        last_error: OSError | None = None
        attempts_used = 0
        for attempt in range(1, read_attempts + 1):
            attempts_used = attempt
            try:
                file_hash = sha256_file(path)
                with Image.open(path) as image:
                    width, height = image.size
                last_error = None
                break
            except UnidentifiedImageError as exc:
                last_error = exc
                break
            except OSError as exc:
                last_error = exc
                if attempt == read_attempts:
                    break
                stats["read_retries"] += 1
                logger.warning(
                    "Image read failed for %s (attempt %d/%d); retrying: %s",
                    path,
                    attempt,
                    read_attempts,
                    exc,
                )
                if retry_delay_seconds:
                    sleep(retry_delay_seconds * (2 ** (attempt - 1)))

        if last_error is not None or file_hash is None:
            stats["invalid_images"] += 1
            is_read_failure = not isinstance(last_error, UnidentifiedImageError)
            if is_read_failure:
                stats["read_failures"] += 1
            detail = {
                "path": str(path),
                "error": str(last_error or "unknown read error"),
                "errno": getattr(last_error, "errno", None),
                "attempts": attempts_used,
                "kind": "read_error" if is_read_failure else "invalid_image",
            }
            stats["read_failure_details"].append(detail)
            logger.error(
                "Skipping unreadable image %s after %d attempt(s): %s",
                path,
                attempts_used,
                detail["error"],
            )
            stats["files_processed"] += 1
            stats["unique_images"] = len(records) + stats["resolution_rejected"]
            stats["embedding_candidates"] = len(records)
            report_progress()
            continue

        if deduplicate and file_hash in seen_hashes:
            stats["duplicates"] += 1
            stats["files_processed"] += 1
            stats["unique_images"] = len(records) + stats["resolution_rejected"]
            stats["embedding_candidates"] = len(records)
            report_progress()
            continue
        seen_hashes[file_hash] = path
        pixels = width * height
        resolution_ok = not resolution_filter or pixels >= minimum_pixels
        record = ImageRecord(
            path,
            file_hash,
            width,
            height,
            pixels,
            resolution_ok=resolution_ok,
        )
        if not record.resolution_ok:
            stats["resolution_rejected"] += 1
        else:
            records.append(record)
        stats["files_processed"] += 1
        stats["unique_images"] = len(records) + stats["resolution_rejected"]
        stats["embedding_candidates"] = len(records)
        report_progress()
    return records, stats
