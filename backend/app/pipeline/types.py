from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np


@dataclass
class ImageRecord:
    path: Path
    sha256: str
    width: int
    height: int
    pixels: int
    embedding: np.ndarray | None = None
    prepared_path: Path | None = None
    duplicate_of: str | None = None
    resolution_ok: bool = True


@dataclass
class Cluster:
    cluster_id: int
    members: list[ImageRecord]
    medoid: ImageRecord | None = None
    backup_candidates: list[ImageRecord] = field(default_factory=list)


@dataclass
class Inspection:
    watermark_boxes: list[list[float]]
    comic_boxes: list[list[float]]
    meets: bool
    reason: str | None = None
    attempt: int = 1


@dataclass
class PipelineResult:
    stats: dict[str, Any]
    manifest: list[dict[str, Any]]
