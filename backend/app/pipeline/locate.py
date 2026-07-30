from __future__ import annotations

import base64
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
from PIL import Image

from .prompts import COMIC_PROMPT, WATERMARK_PROMPT
from .types import Inspection

DetectionStepCallback = Callable[[str, str, list[list[float]]], None]


class LocateAnythingProvider:
    def locate(self, path: Path, prompt: str) -> list[list[float]]:
        raise NotImplementedError

    def close(self) -> None:
        pass


class LocateAnythingHttpProvider(LocateAnythingProvider):
    def __init__(self, endpoint: str, model_id: str, timeout_seconds: int = 180, max_tokens: int = 1024):
        if not endpoint:
            raise RuntimeError("LOCATE_ANYTHING_ENDPOINT is required")
        self.endpoint = endpoint
        self.model_id = model_id
        self.timeout = timeout_seconds
        self.max_tokens = max_tokens
        self.client = httpx.Client(timeout=self.timeout)

    def locate(self, path: Path, prompt: str) -> list[list[float]]:  # pragma: no cover - external service
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        suffix = path.suffix.lower().lstrip(".") or "jpeg"
        mime = "jpg" if suffix == "jpg" else suffix
        payload = {
            "model": self.model_id,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/{mime};base64,{encoded}"}},
                    ],
                }
            ],
            "max_tokens": self.max_tokens,
            "temperature": 0,
        }
        try:
            response = self.client.post(self.endpoint, json=payload)
        except httpx.TimeoutException as exc:
            raise RuntimeError(
                f"Locate Anything timed out after {self.timeout}s while checking {path.name}"
            ) from exc
        except httpx.RequestError as exc:
            raise RuntimeError(f"Locate Anything request failed for {path.name}: {exc}") from exc
        if response.is_error:
            detail = response.text.strip()[:4000] or "<empty response body>"
            raise RuntimeError(
                f"Locate Anything HTTP {response.status_code} while checking {path.name}: {detail}"
            )
        with Image.open(path) as image:
            width, height = image.size
        return _extract_boxes(response.json(), width, height)

    def close(self) -> None:
        self.client.close()


def _extract_boxes(payload: Any, width: int | None = None, height: int | None = None) -> list[list[float]]:
    if isinstance(payload, dict):
        if isinstance(payload.get("boxes"), list):
            return payload["boxes"]
        choices = payload.get("choices")
        if isinstance(choices, list) and choices:
            message = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
            content = message.get("content") if isinstance(message, dict) else None
            if isinstance(content, str):
                return _parse_box_tokens(content, width, height)
        for key in ("results", "detections", "instances"):
            entries = payload.get(key)
            if isinstance(entries, list):
                boxes = []
                for entry in entries:
                    if isinstance(entry, dict):
                        box = entry.get("box", entry.get("bbox"))
                        if isinstance(box, list):
                            boxes.append(box)
                return boxes
    if isinstance(payload, list):
        return [entry for entry in payload if isinstance(entry, list)]
    raise ValueError(f"Locate Anything response does not contain boxes: {json.dumps(payload)[:400]}")


def _parse_box_tokens(content: str, width: int | None, height: int | None) -> list[list[float]]:
    """Parse LocateAnything's normalized [0, 1000] box tokens."""
    boxes = []
    for match in re.finditer(r"<box><(\d+)><(\d+)><(\d+)><(\d+)></box>", content):
        x1, y1, x2, y2 = (int(value) for value in match.groups())
        if width and height:
            boxes.append([x1 / 1000 * width, y1 / 1000 * height, x2 / 1000 * width, y2 / 1000 * height])
        else:
            boxes.append([x1, y1, x2, y2])
    return boxes


def make_locate_provider(
    endpoint: str,
    model_id: str,
    timeout_seconds: int,
    max_tokens: int,
) -> LocateAnythingProvider:
    return LocateAnythingHttpProvider(endpoint, model_id, timeout_seconds, max_tokens)


def inspect_image(
    provider: LocateAnythingProvider,
    path: Path,
    attempt: int,
    on_step: DetectionStepCallback | None = None,
) -> Inspection:
    if on_step:
        on_step("watermark", "running", [])
    watermark_boxes = provider.locate(path, WATERMARK_PROMPT)
    if on_step:
        on_step("watermark", "completed", watermark_boxes)
    if watermark_boxes:
        if on_step:
            on_step("comic", "skipped", [])
        return Inspection(watermark_boxes, [], False, "watermark_detected", attempt)
    if on_step:
        on_step("comic", "running", [])
    comic_boxes = provider.locate(path, COMIC_PROMPT)
    if on_step:
        on_step("comic", "completed", comic_boxes)
    if len(comic_boxes) > 1:
        return Inspection(watermark_boxes, comic_boxes, False, "comic_or_collage_detected", attempt)
    return Inspection(watermark_boxes, comic_boxes, True, None, attempt)
