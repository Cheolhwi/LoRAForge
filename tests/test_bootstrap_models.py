import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace


def load_bootstrap_models_module():
    script_path = Path(__file__).parents[1] / "scripts" / "bootstrap_models.py"
    spec = importlib.util.spec_from_file_location("loraforge_bootstrap_models", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_verify_dino_processor_initializes_from_local_snapshot(monkeypatch, tmp_path):
    bootstrap_models = load_bootstrap_models_module()
    calls = []

    class FakeProcessor:
        pass

    fake_transformers = SimpleNamespace(
        AutoImageProcessor=SimpleNamespace(
            from_pretrained=lambda path: calls.append(path) or FakeProcessor()
        )
    )
    monkeypatch.setitem(sys.modules, "transformers", fake_transformers)

    processor_name = bootstrap_models.verify_dino_processor(tmp_path)

    assert processor_name == "FakeProcessor"
    assert calls == [tmp_path]
