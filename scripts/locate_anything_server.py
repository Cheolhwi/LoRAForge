from __future__ import annotations

import argparse
import base64
import gc
import io
import os
import sys
import threading
import traceback
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException
from PIL import Image
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    model: str | None = None
    messages: list[dict[str, Any]]
    max_tokens: int = Field(default=1024, ge=1, le=1024)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)


class LocateWorker:
    def __init__(self, model_id: str):
        if sys.platform != "darwin":
            raise RuntimeError("The MLX Locate Anything service requires macOS on Apple Silicon")
        try:
            import mlx.core as mx
            from mlx_vlm import load
            from mlx_vlm.prompt_utils import apply_chat_template
            from mlx_vlm.utils import prepare_inputs
        except ImportError as exc:
            raise RuntimeError(
                "Locate Anything MLX dependencies are missing. Run ./start_services.sh."
            ) from exc

        self.model_id = model_id
        self.runtime = "mlx"
        self.mx = mx
        self.apply_chat_template = apply_chat_template
        self.prepare_inputs = prepare_inputs
        self.model, self.processor = load(model_id)
        if not hasattr(self.model, "pbd_generate"):
            raise RuntimeError(
                f"{model_id} is not a Locate Anything model supported by mlx-vlm"
            )
        self.lock = threading.Lock()

    def clear_accelerator_cache(self, force_gc: bool = False) -> None:
        if force_gc:
            gc.collect()
        try:
            metal = getattr(self.mx, "metal", None)
            clear_cache = getattr(metal, "clear_cache", None)
            if not callable(clear_cache):
                clear_cache = getattr(self.mx, "clear_cache", None)
            if callable(clear_cache):
                clear_cache()
        except Exception as exc:  # noqa: BLE001 - cleanup must not hide the original inference error
            print(f"[locate-anything] MLX cache cleanup failed: {exc}", file=sys.stderr, flush=True)

    @staticmethod
    def parse_message(messages: list[dict[str, Any]]) -> tuple[Image.Image, str]:
        image_url: str | None = None
        prompt = ""
        for message in reversed(messages):
            content = message.get("content", [])
            if isinstance(content, str):
                prompt = prompt or content
                continue
            if not isinstance(content, list):
                continue
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "text":
                    prompt = prompt or str(part.get("text", ""))
                if part.get("type") == "image_url":
                    image_value = part.get("image_url", {})
                    image_url = image_value.get("url") if isinstance(image_value, dict) else image_value
            if image_url:
                break
        if not image_url or not prompt:
            raise ValueError("request must contain one image_url and one text prompt")
        if image_url.startswith("data:"):
            _, encoded = image_url.split(",", 1)
            raw = base64.b64decode(encoded)
        else:
            response = httpx.get(image_url, timeout=30)
            response.raise_for_status()
            raw = response.content
        return Image.open(io.BytesIO(raw)).convert("RGB"), prompt

    def locate(self, image: Image.Image, prompt: str, max_tokens: int) -> str:
        formatted_prompt = self.apply_chat_template(
            self.processor,
            self.model.config,
            prompt,
            num_images=1,
        )
        inputs = None
        tokens = None
        with self.lock:
            try:
                inputs = self.prepare_inputs(
                    self.processor,
                    images=[image],
                    prompts=formatted_prompt,
                )
                input_ids = inputs.pop("input_ids")
                inputs.pop("attention_mask", None)
                tokens = self.model.pbd_generate(
                    input_ids,
                    generation_mode="hybrid",
                    max_tokens=max_tokens,
                    **inputs,
                )
                return self.processor.decode(tokens, skip_special_tokens=False)
            finally:
                del tokens
                del inputs
                self.clear_accelerator_cache()


worker: LocateWorker | None = None


def load_project_env() -> None:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@asynccontextmanager
async def lifespan(_: FastAPI):
    global worker
    model_id = os.getenv(
        "LOCATE_ANYTHING_MODEL_ID", "mlx-community/LocateAnything-3B-4bit"
    )
    print(f"[locate-anything] loading MLX model {model_id}", flush=True)
    worker = LocateWorker(model_id)
    print("[locate-anything] ready on Apple Metal via MLX", flush=True)
    yield
    worker = None


app = FastAPI(title="Locate Anything CLI Service", lifespan=lifespan)


@app.get("/health")
def health():
    return {
        "status": "ok" if worker else "loading",
        "model": worker.model_id if worker else None,
        "runtime": worker.runtime if worker else "mlx",
    }


@app.get("/v1/models")
def models():
    if worker is None:
        raise HTTPException(status_code=503, detail="model is still loading")
    return {"object": "list", "data": [{"id": worker.model_id, "object": "model", "owned_by": "local"}]}


@app.post("/v1/chat/completions")
def chat_completions(request: ChatRequest):
    if worker is None:
        raise HTTPException(status_code=503, detail="model is still loading")
    request_id = f"locate-{uuid.uuid4().hex[:12]}"
    image: Image.Image | None = None
    try:
        image, prompt = worker.parse_message(request.messages)
        answer = worker.locate(image, prompt, request.max_tokens)
    except Exception as exc:
        is_memory_error = isinstance(exc, MemoryError) or "out of memory" in str(exc).lower()
        worker.clear_accelerator_cache(force_gc=True)
        print(
            f"[locate-anything] request {request_id} failed: {type(exc).__name__}: {exc}",
            file=sys.stderr,
            flush=True,
        )
        traceback.print_exc()
        if is_memory_error:
            detail = {
                "code": "mlx_out_of_memory",
                "message": (
                    "Locate Anything ran out of Apple unified memory. The MLX cache was cleared; "
                    "retry with max_tokens <= 1024 or a smaller image."
                ),
                "cause": str(exc),
            }
            raise HTTPException(status_code=503, detail=detail) from exc
        detail = {"code": "inference_error", "type": type(exc).__name__, "message": str(exc)}
        raise HTTPException(status_code=500, detail=detail) from exc
    finally:
        if image is not None:
            image.close()
    return {
        "id": request_id,
        "object": "chat.completion",
        "model": worker.model_id,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": answer}, "finish_reason": "stop"}],
    }


def main():
    load_project_env()
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9000)
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
