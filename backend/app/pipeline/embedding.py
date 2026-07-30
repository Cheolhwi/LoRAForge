from __future__ import annotations

import gc
from pathlib import Path
from typing import Protocol

import numpy as np
from PIL import Image, ImageOps


class EmbeddingProvider(Protocol):
    dimension: int

    def embed(self, path: Path, prepared_path: Path | None = None) -> np.ndarray:
        ...

    def close(self) -> None:
        ...


class DINOv3Provider:
    """DINOv3 ViT-L/16 provider; heavy imports are delayed until it is used."""

    dimension = 1024

    def __init__(self, model_id: str):
        try:
            import torch
            from transformers import AutoImageProcessor, AutoModel
        except ImportError as exc:  # pragma: no cover - depends on optional extra
            raise RuntimeError("DINOv3 requires `uv sync --extra models`") from exc

        self.torch = torch
        self.processor = AutoImageProcessor.from_pretrained(model_id)
        self.model = AutoModel.from_pretrained(model_id)
        self.model.eval()
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model.to(self.device)

    def embed(
        self,
        path: Path,
        prepared_path: Path | None = None,
    ) -> np.ndarray:  # pragma: no cover - requires model download
        with Image.open(path) as image:
            image = image.convert("RGB")
            cpu_inputs = self.processor(
                images=image,
                return_tensors="pt",
                size={"height": 448, "width": 448},
            )
        if prepared_path is not None:
            prepared_pixels = cpu_inputs["pixel_values"][0].detach().float().cpu().numpy()
            if prepared_pixels.shape[-2:] != (448, 448):
                raise RuntimeError(
                    f"DINOv3 preprocessed image is {prepared_pixels.shape[-2:]}, expected (448, 448)"
                )
            image_mean = self.processor.image_mean if getattr(self.processor, "do_normalize", False) else None
            image_std = self.processor.image_std if getattr(self.processor, "do_normalize", False) else None
            _save_preprocessed_image(
                prepared_pixels,
                prepared_path,
                image_mean,
                image_std,
            )
        inputs = cpu_inputs.to(self.device)
        with self.torch.inference_mode():
            outputs = self.model(**inputs)
        vector = getattr(outputs, "pooler_output", None)
        if vector is None:
            vector = outputs.last_hidden_state[:, 0]
        vector = vector[0].detach().float().cpu().numpy()
        if vector.shape[0] != self.dimension:
            raise RuntimeError(f"DINOv3 embedding dimension is {vector.shape[0]}, expected 1024")
        norm = np.linalg.norm(vector)
        return (vector / max(norm, 1e-12)).astype(np.float32)

    def close(self) -> None:
        if hasattr(self, "model"):
            del self.model
        if self.device == "cuda":
            gc.collect()
            self.torch.cuda.empty_cache()


class PixAIEmbeddingProvider:
    """PixAI Tagger v0.9's native 1024-dim visual embedding output."""

    dimension = 1024

    def __init__(self, model_name: str):
        try:
            import onnxruntime
            import torch
            from imgutils.tagging import get_pixai_tags
        except ImportError as exc:  # pragma: no cover - depends on optional extra
            raise RuntimeError(
                "PixAI similarity requires model dependencies. Run start_services.bat."
            ) from exc
        if torch.cuda.is_available() and hasattr(onnxruntime, "preload_dlls"):
            onnxruntime.preload_dlls()
        self._get_pixai_tags = get_pixai_tags
        self.model_name = model_name

    def embed(
        self,
        path: Path,
        prepared_path: Path | None = None,
    ) -> np.ndarray:  # pragma: no cover - requires model download
        inference_path = path
        if prepared_path is not None:
            _save_pixai_preprocessed_image(path, prepared_path)
            inference_path = prepared_path
        vector = np.asarray(
            self._get_pixai_tags(
                inference_path,
                model_name=self.model_name,
                fmt="embedding",
            ),
            dtype=np.float32,
        ).reshape(-1)
        if vector.shape != (self.dimension,):
            raise RuntimeError(
                f"PixAI embedding dimension is {vector.shape}, expected ({self.dimension},)"
            )
        norm = np.linalg.norm(vector)
        if not np.isfinite(norm) or norm <= 1e-12:
            raise RuntimeError(f"PixAI returned an invalid embedding for {path.name}")
        return (vector / norm).astype(np.float32)

    def close(self) -> None:
        return None


def _save_pixai_preprocessed_image(source: Path, destination: Path) -> None:
    with Image.open(source) as source_image:
        image = ImageOps.exif_transpose(source_image)
        if image.mode in {"RGBA", "LA"} or (
            image.mode == "P" and "transparency" in image.info
        ):
            foreground = image.convert("RGBA")
            background = Image.new("RGBA", foreground.size, "white")
            image = Image.alpha_composite(background, foreground).convert("RGB")
        else:
            image = image.convert("RGB")
        image = image.resize((448, 448), Image.Resampling.BILINEAR)
        destination.parent.mkdir(parents=True, exist_ok=True)
        image.save(destination, format="PNG")


def _save_preprocessed_image(
    pixel_values: np.ndarray,
    destination: Path,
    image_mean: list[float] | tuple[float, ...] | None,
    image_std: list[float] | tuple[float, ...] | None,
) -> None:
    pixels = np.asarray(pixel_values, dtype=np.float32)
    if pixels.ndim != 3 or pixels.shape[0] not in {1, 3, 4}:
        raise ValueError(f"expected CHW image tensor, got shape {pixels.shape}")
    if image_mean is not None and image_std is not None:
        mean = np.asarray(image_mean, dtype=np.float32).reshape(-1, 1, 1)
        std = np.asarray(image_std, dtype=np.float32).reshape(-1, 1, 1)
        pixels = pixels * std + mean
    if float(pixels.max(initial=0.0)) <= 1.5:
        pixels = pixels * 255.0
    pixels = np.clip(np.rint(pixels), 0, 255).astype(np.uint8)
    pixels = np.transpose(pixels, (1, 2, 0))
    if pixels.shape[2] == 1:
        pixels = pixels[:, :, 0]
    destination.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(pixels).save(destination, format="PNG")


def make_embedding_provider(model_id: str) -> EmbeddingProvider:
    return DINOv3Provider(model_id)


def make_pixai_embedding_provider(model_name: str) -> EmbeddingProvider:
    return PixAIEmbeddingProvider(model_name)
