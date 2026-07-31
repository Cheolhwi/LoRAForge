from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from .types import ImageRecord

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}


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
) -> tuple[list[ImageRecord], dict[str, int | bool]]:
    if not source_dir.exists() or not source_dir.is_dir():
        raise ValueError(f"source_dir is not a directory: {source_dir}")
    records: list[ImageRecord] = []
    seen_hashes: dict[str, Path] = {}
    stats = {
        "files_found": 0,
        "duplicates": 0,
        "invalid_images": 0,
        "resolution_rejected": 0,
        "minimum_pixels": minimum_pixels,
        "deduplicate_enabled": deduplicate,
        "resolution_filter_enabled": resolution_filter,
    }
    for path in sorted(source_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        stats["files_found"] += 1
        file_hash = sha256_file(path)
        if deduplicate and file_hash in seen_hashes:
            stats["duplicates"] += 1
            continue
        try:
            with Image.open(path) as image:
                width, height = image.size
        except (UnidentifiedImageError, OSError):
            stats["invalid_images"] += 1
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
            continue
        records.append(record)
    stats["unique_images"] = len(records) + stats["resolution_rejected"]
    stats["embedding_candidates"] = len(records)
    return records, stats
