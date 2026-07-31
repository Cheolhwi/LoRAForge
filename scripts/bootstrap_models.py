from __future__ import annotations

import os
from pathlib import Path


def load_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def verify_dino_processor(model_path: str | Path) -> str:
    from transformers import AutoImageProcessor

    processor = AutoImageProcessor.from_pretrained(model_path)
    return type(processor).__name__


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    dotenv = load_dotenv(root / ".env")
    for key, value in dotenv.items():
        os.environ.setdefault(key, value)

    dino_model_id = os.getenv("DINO_MODEL_ID", "facebook/dinov3-vitl16-pretrain-lvd1689m")
    locate_model_id = os.getenv("LOCATE_ANYTHING_MODEL_ID", "mlx-community/LocateAnything-3B-4bit")
    pixai_model_id = os.getenv("PIXAI_RUNTIME_MODEL_ID", "deepghs/pixai-tagger-v0.9-onnx")
    locate_endpoint = os.getenv("LOCATE_ANYTHING_ENDPOINT", "").strip()

    try:
        from huggingface_hub import snapshot_download

        print(f"[models] Checking DINOv3 model: {dino_model_id}")
        dino_path = snapshot_download(repo_id=dino_model_id)
        print(f"[models] DINOv3 assets ready at: {dino_path}")
        print(f"[models] Checking Locate Anything MLX model: {locate_model_id}")
        locate_path = snapshot_download(repo_id=locate_model_id)
        print(f"[models] Locate Anything MLX ready at: {locate_path}")
        print(f"[models] Checking PixAI Tagger v0.9 ONNX model: {pixai_model_id}")
        pixai_path = snapshot_download(repo_id=pixai_model_id)
        print(f"[models] PixAI Tagger ready at: {pixai_path}")
    except Exception as exc:  # noqa: BLE001 - show a setup-specific error before startup
        print("[ERROR] Could not download or access one of the configured models.")
        print("        Accept the model terms and set HF_TOKEN when the repository requires it.")
        print(f"        Details: {exc}")
        return 1

    try:
        processor_name = verify_dino_processor(dino_path)
    except Exception as exc:  # noqa: BLE001 - fail startup with the real processor error
        print("[ERROR] DINOv3 image processor could not be initialized.")
        print("        Run `uv sync --extra models` and check the torchvision installation.")
        print(f"        Details: {exc}")
        return 1
    print(f"[models] DINOv3 processor ready: {processor_name}")

    if not locate_endpoint:
        print("[ERROR] LOCATE_ANYTHING_ENDPOINT is empty.")
        print(
            "        Start a Locate Anything service and set its /v1/chat/completions URL in .env."
        )
        return 1

    print(f"[models] Locate Anything endpoint will be served locally at: {locate_endpoint}")
    print("[models] DINOv3 and PixAI Tagger assets are ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
