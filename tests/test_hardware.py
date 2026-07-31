import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import numpy as np
import pytest
from app.hardware import clear_mps_cache, configure_coreml_provider, require_mps_device
from app.pipeline.embedding import DINOv3Provider, _normalize_embedding


class FakeMPSBackend:
    def __init__(self, *, built: bool = True, available: bool = True):
        self._built = built
        self._available = available

    def is_built(self) -> bool:
        return self._built

    def is_available(self) -> bool:
        return self._available


def fake_torch(*, built: bool = True, available: bool = True):
    return SimpleNamespace(
        backends=SimpleNamespace(mps=FakeMPSBackend(built=built, available=available)),
        device=lambda name: f"{name}-device",
    )


def test_require_mps_device_returns_metal_device():
    assert require_mps_device(fake_torch()) == "mps-device"


def test_require_mps_device_rejects_unavailable_backend():
    with pytest.raises(RuntimeError, match="Apple Metal"):
        require_mps_device(fake_torch(available=False))


def test_clear_mps_cache_calls_torch_mps_cache():
    calls = []
    torch_module = SimpleNamespace(mps=SimpleNamespace(empty_cache=lambda: calls.append("clear")))

    clear_mps_cache(torch_module)

    assert calls == ["clear"]


def test_configure_coreml_provider_accepts_available_provider():
    runtime = SimpleNamespace(
        get_available_providers=lambda: [
            "CoreMLExecutionProvider",
            "CPUExecutionProvider",
        ]
    )

    assert configure_coreml_provider(runtime) == "CoreMLExecutionProvider"


def test_configure_coreml_provider_rejects_cpu_only_runtime():
    runtime = SimpleNamespace(get_available_providers=lambda: ["CPUExecutionProvider"])

    with pytest.raises(RuntimeError, match="CoreMLExecutionProvider"):
        configure_coreml_provider(runtime)


def test_dinov3_provider_uses_float32_on_mps(monkeypatch):
    model = SimpleNamespace(
        eval=lambda: None,
        to=lambda **kwargs: setattr(model, "move", kwargs),
    )
    torch_module = ModuleType("torch")
    torch_module.float32 = "float32"
    torch_module.backends = SimpleNamespace(mps=FakeMPSBackend())
    torch_module.device = lambda name: f"{name}-device"
    transformers_module = ModuleType("transformers")
    transformers_module.AutoImageProcessor = SimpleNamespace(
        from_pretrained=lambda model_id: SimpleNamespace(model_id=model_id)
    )
    transformers_module.AutoModel = SimpleNamespace(from_pretrained=lambda model_id: model)
    monkeypatch.setitem(sys.modules, "torch", torch_module)
    monkeypatch.setitem(sys.modules, "transformers", transformers_module)

    provider = DINOv3Provider("dino-model")

    assert provider.dtype == "float32"
    assert model.move == {"device": "mps-device", "dtype": "float32"}


def test_embedding_normalization_rejects_non_finite_values():
    with pytest.raises(RuntimeError, match="DINOv3 returned an invalid embedding"):
        _normalize_embedding(
            np.asarray([np.nan, 1.0], dtype=np.float32),
            2,
            "DINOv3",
            Path("image.png"),
        )
