from __future__ import annotations

import subprocess
from functools import lru_cache
from io import BytesIO
from typing import Annotated, Literal

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from PIL import Image, ImageOps

from .config import get_settings
from .folder_dialog import select_folder
from .jobs import JobManager
from .schemas import (
    CurationFinalize,
    CurationStart,
    JobCreate,
    JobManifest,
    JobSummary,
    PixAIJobCreate,
)

settings = get_settings()
manager = JobManager(settings)
app = FastAPI(title="LoRAForge Pipeline API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

@lru_cache(maxsize=128)
def _review_thumbnail_bytes(path: str, modified_ns: int, file_size: int) -> bytes:
    del modified_ns, file_size
    with Image.open(path) as image:
        thumbnail = ImageOps.exif_transpose(image).convert("RGB")
        width, height = thumbnail.size
        if width > height:
            preview_size = (1280, 720)
        elif height > width:
            preview_size = (720, 1280)
        else:
            preview_size = (960, 960)
        thumbnail.thumbnail(preview_size, Image.Resampling.LANCZOS)
        buffer = BytesIO()
        thumbnail.save(
            buffer,
            format="JPEG",
            quality=82,
            subsampling="4:2:0",
            # The frontend loads several review images in a small scroll window.
            # Baseline JPEG avoids repeated progressive-scan paints while keeping
            # the same 720p review resolution and visual quality.
            progressive=False,
        )
    return buffer.getvalue()


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "runtime": "local_models",
        "acceleration": {
            "locate_anything": "mlx",
            "dinov3": "mps",
            "pixai": "CoreMLExecutionProvider",
        },
        "review_thumbnail": True,
        "minimum_pixels": settings.min_megapixels,
        "complete_linkage_similarity": settings.complete_linkage_similarity,
        "graph_similarity": settings.graph_similarity,
        "pixai_model_id": settings.pixai_model_id,
        "pixai_caption_threshold": settings.pixai_caption_threshold,
        "pixai_caption_max_tags": settings.pixai_caption_max_tags,
        "pixai_caption_hard_max_tags": settings.pixai_caption_hard_max_tags,
    }


@app.get("/api/folders/select")
def choose_folder(
    purpose: Literal["source", "output"] = Query(default="source"),
    locale: Literal["zh", "en"] = Query(default="zh"),
):
    try:
        selected = select_folder(purpose, locale=locale)
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(status_code=504, detail="folder selection timed out") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"path": str(selected) if selected else None, "cancelled": selected is None}


@app.post("/api/jobs", response_model=JobSummary, status_code=202)
def create_job(request: JobCreate):
    state = manager.create(
        source_dir=request.source_dir,
        output_dir=request.output_dir,
        seed=request.seed,
        similarity_model=request.similarity_model,
        minimum_pixels=request.minimum_pixels,
        complete_linkage_similarity=request.complete_linkage_similarity,
        graph_similarity=request.graph_similarity,
        pipeline_options=request.pipeline_options,
    )
    return state.summary()


@app.post("/api/pixai/jobs", status_code=202)
def create_pixai_job(request: PixAIJobCreate):
    try:
        _, result = manager.create_pixai_only(
            request.source_dir,
            request.output_dir,
            request.lora_prefix,
        )
        return result
    except (FileNotFoundError, NotADirectoryError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/jobs", response_model=list[JobSummary])
def list_jobs():
    return manager.list()


def get_state(job_id: str):
    state = manager.get(job_id)
    if state is None:
        raise HTTPException(status_code=404, detail="job not found")
    return state


@app.get("/api/jobs/{job_id}", response_model=JobSummary)
def get_job(job_id: str):
    return get_state(job_id).summary()


@app.get("/api/jobs/{job_id}/events")
async def job_events(
    job_id: str,
    last_event_id: int = Query(default=0, ge=0),
    last_event_id_header: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
):
    state = get_state(job_id)
    if last_event_id_header:
        try:
            last_event_id = max(last_event_id, int(last_event_id_header))
        except ValueError:
            pass
    return StreamingResponse(
        manager.event_stream(state, last_event_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@app.get("/api/jobs/{job_id}/manifest", response_model=JobManifest)
def get_manifest(job_id: str):
    return manager.manifest(get_state(job_id))


@app.get("/api/jobs/{job_id}/curation")
def get_curation(job_id: str):
    return manager.curation_summary(get_state(job_id))


@app.post("/api/jobs/{job_id}/curation", status_code=202)
def start_curation(job_id: str, request: CurationStart):
    try:
        return manager.start_curation(get_state(job_id), request.lora_prefix)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/jobs/{job_id}/curation/finalize", status_code=202)
def finalize_curation(job_id: str, request: CurationFinalize):
    try:
        return manager.finalize_curation(get_state(job_id), request)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/jobs/{job_id}/curation/image/{item_index}")
def curation_image(job_id: str, item_index: int):
    try:
        image_path = manager.curation_image_path(get_state(job_id), item_index)
    except (IndexError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return FileResponse(image_path, headers={"Cache-Control": "private, max-age=3600"})


@app.get("/api/jobs/{job_id}/audit/thumbnail/{image_id}")
def audit_thumbnail(job_id: str, image_id: str):
    state = get_state(job_id)
    try:
        image_path = manager.audit_image_path(state, image_id)
        with Image.open(image_path) as image:
            thumbnail = ImageOps.exif_transpose(image).convert("RGB")
            thumbnail.thumbnail((96, 96), Image.Resampling.LANCZOS)
        buffer = BytesIO()
        thumbnail.save(buffer, format="JPEG", quality=38, optimize=True)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=422, detail=f"could not create audit thumbnail: {exc}") from exc
    return Response(
        content=buffer.getvalue(),
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=3600"},
    )


@app.get("/api/jobs/{job_id}/review/{item_index}")
def review_image(job_id: str, item_index: int):
    try:
        image_path = manager.review_image_path(get_state(job_id), item_index)
    except (IndexError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return FileResponse(image_path, headers={"Cache-Control": "private, max-age=3600"})


@app.get("/api/jobs/{job_id}/review/{item_index}/thumbnail")
def review_thumbnail(job_id: str, item_index: int):
    try:
        image_path = manager.review_image_path(get_state(job_id), item_index)
        stat = image_path.stat()
        content = _review_thumbnail_bytes(str(image_path), stat.st_mtime_ns, stat.st_size)
    except (IndexError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=422, detail=f"could not create review thumbnail: {exc}") from exc
    return Response(
        content=content,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=86400"},
    )


@app.delete("/api/jobs/{job_id}/review/{item_index}")
def remove_review_image(job_id: str, item_index: int):
    try:
        return manager.remove_review_image(get_state(job_id), item_index)
    except (IndexError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/jobs/{job_id}/review/{item_index}/restore")
def restore_review_image(job_id: str, item_index: int):
    try:
        return manager.restore_review_image(get_state(job_id), item_index)
    except (IndexError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (ValueError, FileExistsError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
