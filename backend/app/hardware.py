from __future__ import annotations

import gc
from typing import Any


def require_mps_device(torch_module: Any):
    """Return the MPS device or fail with a macOS-specific setup error."""
    backends = getattr(torch_module, "backends", None)
    mps_backend = getattr(backends, "mps", None)
    if mps_backend is None or not mps_backend.is_built():
        raise RuntimeError(
            "PyTorch was installed without MPS support. Use the native arm64 Python "
            "environment created by start_services.sh."
        )
    if not mps_backend.is_available():
        raise RuntimeError(
            "Apple Metal (MPS) is unavailable. LoRAForge mac-version requires an "
            "Apple Silicon Mac running macOS 14 or newer."
        )
    return torch_module.device("mps")


def clear_mps_cache(torch_module: Any, *, force_gc: bool = False) -> None:
    """Release unused PyTorch Metal allocations without hiding inference errors."""
    if force_gc:
        gc.collect()
    mps_module = getattr(torch_module, "mps", None)
    empty_cache = getattr(mps_module, "empty_cache", None)
    if callable(empty_cache):
        empty_cache()


def configure_coreml_provider(onnxruntime_module: Any) -> str:
    """Select CoreML for ONNX inference and verify the wheel exposes it."""
    provider = "CoreMLExecutionProvider"
    available = set(onnxruntime_module.get_available_providers())
    if provider not in available:
        choices = ", ".join(sorted(available)) or "none"
        raise RuntimeError(
            "The installed ONNX Runtime does not expose CoreMLExecutionProvider "
            f"(available: {choices}). Re-run ./start_services.sh with native arm64 Python."
        )
    return provider
