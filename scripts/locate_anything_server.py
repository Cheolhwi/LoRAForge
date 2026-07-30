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
import torch
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
        if not torch.cuda.is_available():
            raise RuntimeError("Locate Anything 4bit service requires a CUDA GPU")
        from transformers import AutoConfig, AutoModel, AutoProcessor, AutoTokenizer

        self.model_id = model_id
        self.device = "cuda"
        self.dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
        config = AutoConfig.from_pretrained(model_id, trust_remote_code=True)
        for child in (config, getattr(config, "text_config", None), getattr(config, "vision_config", None)):
            if child is not None:
                child._attn_implementation = "sdpa"
        quantization_config = getattr(config, "quantization_config", None)
        if isinstance(quantization_config, dict):
            quantization_config["run_compressed"] = False
        self.tokenizer = AutoTokenizer.from_pretrained(model_id, trust_remote_code=True)
        self.processor = AutoProcessor.from_pretrained(model_id, trust_remote_code=True)
        self.model = AutoModel.from_pretrained(
            model_id,
            config=config,
            torch_dtype=self.dtype,
            trust_remote_code=True,
        ).to(self.device).eval()
        self.lock = threading.Lock()

    @staticmethod
    def clear_cuda_cache(force_gc: bool = False) -> None:
        if force_gc:
            gc.collect()
        try:
            torch.cuda.empty_cache()
        except Exception as exc:  # noqa: BLE001 - cleanup must not hide the original inference error
            print(f"[locate-anything] CUDA cache cleanup failed: {exc}", file=sys.stderr, flush=True)

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
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": image},
                    {"type": "text", "text": prompt},
                ],
            }
        ]
        text = self.processor.py_apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        images, videos = self.processor.process_vision_info(messages)
        cpu_inputs = self.processor(text=[text], images=images, videos=videos, return_tensors="pt")
        inputs = None
        response = None
        answer = None
        with self.lock:
            try:
                inputs = cpu_inputs.to(self.device)
                if "pixel_values" in inputs:
                    inputs["pixel_values"] = inputs["pixel_values"].to(self.dtype)
                with torch.inference_mode():
                    response = self.model.generate(
                        pixel_values=inputs.get("pixel_values"),
                        input_ids=inputs["input_ids"],
                        attention_mask=inputs["attention_mask"],
                        image_grid_hws=inputs.get("image_grid_hws"),
                        tokenizer=self.tokenizer,
                        max_new_tokens=max_tokens,
                        use_cache=True,
                        generation_mode="hybrid",
                        temperature=0.0,
                        do_sample=False,
                        verbose=False,
                    )
                answer = response[0] if isinstance(response, tuple) else response
                if isinstance(answer, str):
                    result = answer
                elif isinstance(answer, torch.Tensor):
                    result = self.tokenizer.decode(answer.tolist(), skip_special_tokens=False)
                else:
                    result = str(answer)
                return result
            finally:
                del answer
                del response
                del inputs
                self.clear_cuda_cache()


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
    model_id = os.getenv("LOCATE_ANYTHING_MODEL_ID", "sahilchachra/LocateAnything-3B-AWQ-W4A16")
    print(f"[locate-anything] loading {model_id}", flush=True)
    worker = LocateWorker(model_id)
    print("[locate-anything] ready", flush=True)
    yield
    worker = None


app = FastAPI(title="Locate Anything CLI Service", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok" if worker else "loading", "model": worker.model_id if worker else None}


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
        is_cuda_oom = isinstance(exc, torch.cuda.OutOfMemoryError) or "out of memory" in str(exc).lower()
        worker.clear_cuda_cache(force_gc=True)
        print(
            f"[locate-anything] request {request_id} failed: {type(exc).__name__}: {exc}",
            file=sys.stderr,
            flush=True,
        )
        traceback.print_exc()
        if is_cuda_oom:
            detail = {
                "code": "cuda_out_of_memory",
                "message": (
                    "Locate Anything ran out of CUDA memory. The CUDA cache was cleared; "
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
