from __future__ import annotations

import asyncio
import json
import shutil
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import Any

import numpy as np

from .config import Settings
from .pipeline.caption_rules import (
    CAPTION_CATEGORY_ORDER,
    DEFAULT_CAPTION_DENYLIST,
    OPTIONAL_TEXT_DENYLIST,
    build_caption_result,
    load_caption_rule_data,
)
from .pipeline.curation import (
    derive_selection_features,
    make_pixai_tagger,
    select_dataset,
    summarize_distribution,
)
from .pipeline.engine import PipelineEngine
from .pipeline.scan import IMAGE_EXTENSIONS
from .schemas import CurationFinalize, JobManifest, JobSummary, PipelineEvent


def utc_now():
    return datetime.now(UTC)


def _json_safe(value: Any) -> Any:
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return _json_safe(value.tolist())
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(_json_safe(key)): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]
    return value


class JobState:
    def __init__(
        self,
        job_id: str,
        source_dir: str,
        output_dir: str | None,
        workflow: str = "filtering",
        similarity_model: str = "dinov3",
        minimum_pixels: int | None = None,
    ):
        self.job_id = job_id
        self.source_dir = source_dir
        self.output_dir = output_dir
        self.workflow = workflow
        self.similarity_model = similarity_model
        self.minimum_pixels = minimum_pixels
        self.status = "queued"
        self.current_stage: str | None = None
        self.progress = 0.0
        self.started_at = utc_now()
        self.finished_at = None
        self.stats: dict[str, Any] = {}
        self.error: str | None = None
        self.events: list[PipelineEvent] = []
        self.manifest: list[dict[str, Any]] = []
        self.audit_images: dict[str, str] = {}
        self.curation: dict[str, Any] = {"status": "not_started"}
        self.curation_items: list[dict[str, Any]] = []
        self.lock = threading.Lock()

    def summary(self) -> JobSummary:
        with self.lock:
            return JobSummary(
                job_id=self.job_id,
                status=self.status,
                workflow=self.workflow,
                similarity_model=self.similarity_model,
                minimum_pixels=self.minimum_pixels,
                source_dir=self.source_dir,
                output_dir=self.output_dir,
                current_stage=self.current_stage,
                progress=self.progress,
                started_at=self.started_at,
                finished_at=self.finished_at,
                stats=dict(self.stats),
                error=self.error,
            )


class JobManager:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.jobs: dict[str, JobState] = {}
        self.lock = threading.Lock()
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="auto-cat")

    def create(
        self,
        source_dir: str,
        output_dir: str | None,
        seed: int | None,
        similarity_model: str = "dinov3",
        minimum_pixels: int | None = None,
    ) -> JobState:
        job_id = uuid.uuid4().hex[:12]
        resolved_minimum_pixels = (
            minimum_pixels
            if minimum_pixels is not None
            else self.settings.min_megapixels
        )
        state = JobState(
            job_id,
            source_dir,
            output_dir,
            similarity_model=similarity_model,
            minimum_pixels=resolved_minimum_pixels,
        )
        with self.lock:
            self.jobs[job_id] = state
        self.executor.submit(self._run, state, seed)
        return state

    def create_pixai_only(
        self,
        source_dir: str,
        output_dir: str | None,
        lora_prefix: str,
    ) -> tuple[JobState, dict[str, Any]]:
        source_root = Path(source_dir).expanduser().resolve()
        if not source_root.is_dir():
            raise FileNotFoundError("source image directory does not exist")

        job_id = uuid.uuid4().hex[:12]
        output_root = (
            Path(output_dir).expanduser().resolve()
            if output_dir
            else (source_root / f"pixai_dataset_{job_id}").resolve()
        )
        if output_root.exists() and not output_root.is_dir():
            raise NotADirectoryError("PixAI output path is not a directory")

        image_paths: list[Path] = []
        for candidate in source_root.rglob("*"):
            if not candidate.is_file() or candidate.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            image_path = candidate.resolve()
            if not image_path.is_relative_to(source_root):
                continue
            if output_root != source_root and image_path.is_relative_to(output_root):
                continue
            image_paths.append(image_path)
        image_paths.sort(key=lambda path: path.relative_to(source_root).as_posix().casefold())
        if not image_paths:
            raise ValueError("the selected folder does not contain supported image files")

        output_root.mkdir(parents=True, exist_ok=True)
        state = JobState(
            job_id,
            str(source_root),
            str(output_root),
            workflow="pixai_only",
            similarity_model="none",
        )
        state.status = "completed"
        state.progress = 1.0
        state.finished_at = utc_now()
        state.manifest = [
            {
                "source": str(image_path),
                "output": None,
                "cluster_id": -1,
                "candidate_role": "standalone",
                "locate_attempt": 0,
                "status": "passed",
                "reason": None,
            }
            for image_path in image_paths
        ]
        state.stats = {
            "workflow": "pixai_only",
            "files_found": len(image_paths),
            "output_images": len(image_paths),
            "output_dir": str(output_root),
        }
        with self.lock:
            self.jobs[job_id] = state

        start_result = self.start_curation(state, lora_prefix)
        start_result.update(
            {
                "workflow": state.workflow,
                "source_images": len(image_paths),
                "source_dir": state.source_dir,
                "output_dir": state.output_dir,
            }
        )
        return state, start_result

    def get(self, job_id: str) -> JobState | None:
        with self.lock:
            return self.jobs.get(job_id)

    def list(self) -> list[JobSummary]:
        with self.lock:
            states = list(self.jobs.values())
        return [state.summary() for state in reversed(states)]

    def _run(self, state: JobState, seed: int | None):
        with state.lock:
            state.status = "running"
        try:
            engine = PipelineEngine(
                self.settings,
                lambda *args: self._event(state, *args),
                similarity_model=state.similarity_model,
                minimum_pixels=state.minimum_pixels,
            )
            result = engine.run(
                state.job_id,
                Path(state.source_dir),
                Path(state.output_dir) if state.output_dir else None,
                seed,
            )
            with state.lock:
                state.status = "completed"
                state.progress = 1.0
                state.stats = _json_safe(result.stats)
                state.output_dir = result.stats.get("output_dir", state.output_dir)
                state.manifest = _json_safe(result.manifest)
                state.finished_at = utc_now()
        except Exception as exc:  # noqa: BLE001 - a worker must publish every failure to the job UI
            with state.lock:
                state.error = str(exc)
                state.finished_at = utc_now()
            self._event(
                state,
                "system",
                "failed",
                "流水线运行失败",
                state.progress,
                {"error": str(exc)},
            )
            with state.lock:
                state.status = "failed"

    def _event(self, state: JobState, stage: str, status: str, message: str, progress: float, data: dict[str, Any]):
        safe_data = _json_safe(data)
        audit_sources: dict[str, str] = {}
        cluster_audit = safe_data.get("cluster_audit")
        if isinstance(cluster_audit, dict) and cluster_audit.get("event") == "clusters_ready":
            for cluster in cluster_audit.get("clusters", []):
                for member in cluster.get("members", []):
                    source = member.pop("source", None)
                    image_id = member.get("image_id")
                    if source and image_id:
                        audit_sources[str(image_id)] = str(source)
        with state.lock:
            state.audit_images.update(audit_sources)
            event = PipelineEvent(
                id=len(state.events) + 1,
                job_id=state.job_id,
                stage=stage,
                status=status,
                message=message,
                progress=progress,
                timestamp=utc_now(),
                data=safe_data,
            )
            state.events.append(event)
            state.current_stage = stage
            state.progress = progress
            transient_keys = {"locate_flow", "cluster_audit", "curation_flow"}
            persistent_data = {key: value for key, value in safe_data.items() if key not in transient_keys}
            if persistent_data:
                state.stats.update(persistent_data)

    async def event_stream(self, state: JobState, last_event_id: int = 0):
        cursor = last_event_id
        last_write = monotonic()
        while True:
            with state.lock:
                new_events = [event for event in state.events if event.id > cursor]
                terminal = state.status in {"completed", "failed", "awaiting_selection"}
            for event in new_events:
                cursor = event.id
                yield f"id: {event.id}\ndata: {event.model_dump_json()}\n\n"
                last_write = monotonic()
            if terminal and not new_events:
                break
            if monotonic() - last_write >= 10:
                yield ": keep-alive\n\n"
                last_write = monotonic()
            await asyncio.sleep(0.25)

    def manifest(self, state: JobState) -> JobManifest:
        return JobManifest(job_id=state.job_id, items=state.manifest)

    def start_curation(self, state: JobState, lora_prefix: str) -> dict[str, Any]:
        with state.lock:
            if state.status != "completed":
                raise ValueError("the filtering task must be completed before PixAI submission")
            if state.curation.get("status") not in {"not_started", "failed"}:
                raise ValueError("this dataset has already been submitted to PixAI")
            source_key = "source" if state.workflow == "pixai_only" else "output"
            passed_items = [
                item
                for item in state.manifest
                if item.get("status") == "passed" and item.get(source_key)
            ]
            if not passed_items:
                raise ValueError("the reviewed dataset is empty")
            event_cursor = len(state.events)
            state.curation = {
                "status": "tagging",
                "lora_prefix": lora_prefix,
                "model_id": self.settings.pixai_model_id,
                "runtime_model_id": self.settings.pixai_runtime_model_id,
                "total_images": len(passed_items),
                "tagged_images": 0,
                "submitted_at": utc_now().isoformat(),
            }
            state.curation_items = []
            state.status = "running"
            state.current_stage = "pixai"
            state.progress = 0.0
            state.finished_at = None
            state.error = None
        self.executor.submit(self._run_curation, state)
        return {
            "job_id": state.job_id,
            "status": "tagging",
            "event_cursor": event_cursor,
            "lora_prefix": lora_prefix,
        }

    def _run_curation(self, state: JobState) -> None:
        provider = None
        try:
            with state.lock:
                source_key = "source" if state.workflow == "pixai_only" else "output"
                source_items = [
                    (index, dict(item))
                    for index, item in enumerate(state.manifest)
                    if item.get("status") == "passed" and item.get(source_key)
                ]
                output_root = self._output_root(state)
                input_root = self._curation_input_root(state)
                lora_prefix = str(state.curation["lora_prefix"])
            provider = make_pixai_tagger(
                self.settings.pixai_model_name,
                self.settings.pixai_model_id,
                self.settings.pixai_storage_threshold,
            )
            tagged_items = []
            total = len(source_items)
            self._event(
                state,
                "pixai",
                "running",
                (
                    f"PixAI Tagger 准备标注文件夹中的 {total} 张图片"
                    if state.workflow == "pixai_only"
                    else f"PixAI Tagger 准备标注 {total} 张 Review 通过图片"
                ),
                0.01,
                {
                    "curation_flow": {
                        "event": "started",
                        "total_images": total,
                        "model_id": self.settings.pixai_model_id,
                        "runtime_model_id": self.settings.pixai_runtime_model_id,
                    }
                },
            )
            for position, (manifest_index, manifest_item) in enumerate(source_items, start=1):
                image_path = Path(str(manifest_item[source_key])).resolve()
                if not image_path.is_relative_to(input_root):
                    raise PermissionError("curation image is outside the task input directory")
                if not image_path.is_file():
                    raise FileNotFoundError(f"curation image is missing: {image_path.name}")
                general_tags = provider.tag(image_path)
                features = derive_selection_features(
                    general_tags,
                    self.settings.pixai_feature_threshold,
                )
                tagged_item = {
                    "image_id": f"{manifest_index:06d}",
                    "path": image_path.relative_to(input_root).as_posix(),
                    "manifest_index": manifest_index,
                    "selection_features": features,
                    "general_tags": general_tags,
                    "selection": {"selected": False},
                }
                tagged_items.append(tagged_item)
                progress = 0.03 + 0.94 * position / max(total, 1)
                with state.lock:
                    state.curation["tagged_images"] = position
                self._event(
                    state,
                    "pixai",
                    "running",
                    f"PixAI 标注 {position}/{total} · {image_path.name}",
                    progress,
                    {
                        "tagged_images": position,
                        "curation_flow": {
                            "event": "image_tagged",
                            "index": position,
                            "total": total,
                            "manifest_index": manifest_index,
                            "filename": image_path.name,
                            "selection_features": features,
                            "top_tags": [
                                {"tag": tag, "score": score}
                                for tag, score in list(general_tags.items())[:8]
                            ],
                        },
                    },
                )

            metadata_path = output_root / "pixai_tags.json"
            metadata_payload = {
                "job_id": state.job_id,
                "model_id": self.settings.pixai_model_id,
                "runtime_model_id": self.settings.pixai_runtime_model_id,
                "resolved_trigger_prefix": lora_prefix,
                "storage_threshold": self.settings.pixai_storage_threshold,
                "items": tagged_items,
            }
            self._write_json_atomic(metadata_path, metadata_payload)
            distribution = summarize_distribution(tagged_items)
            with state.lock:
                state.curation_items = tagged_items
                state.curation.update(
                    {
                        "status": "awaiting_selection",
                        "tagged_images": total,
                        "metadata_path": str(metadata_path),
                        "distribution": distribution,
                        "finished_tagging_at": utc_now().isoformat(),
                    }
                )
            self._event(
                state,
                "pixai",
                "completed",
                "PixAI 标注完成，等待设置边际分布",
                1.0,
                {
                    "tagged_images": total,
                    "curation_flow": {
                        "event": "tagging_completed",
                        "total_images": total,
                        "distribution": distribution,
                    },
                },
            )
            with state.lock:
                state.status = "awaiting_selection"
                state.finished_at = utc_now()
        except Exception as exc:  # noqa: BLE001 - publish model failures to the UI
            self._event(
                state,
                "pixai",
                "failed",
                "PixAI 标注失败",
                state.progress,
                {"error": str(exc), "curation_flow": {"event": "failed", "error": str(exc)}},
            )
            with state.lock:
                state.curation.update({"status": "failed", "error": str(exc)})
                state.status = "completed"
                state.finished_at = utc_now()
        finally:
            if provider is not None:
                provider.close()

    def finalize_curation(
        self,
        state: JobState,
        request: CurationFinalize,
    ) -> dict[str, Any]:
        with state.lock:
            if state.status != "awaiting_selection":
                raise ValueError("PixAI tagging must finish before dataset selection")
            if not state.curation_items:
                raise ValueError("PixAI tagging results are unavailable")
            event_cursor = len(state.events)
            state.curation.update(
                {
                    "status": "finalizing",
                    "selection_config": request.model_dump(),
                    "error": None,
                }
            )
            state.status = "running"
            state.current_stage = "caption"
            state.progress = 0.0
            state.finished_at = None
        self.executor.submit(self._run_finalize_curation, state, request)
        return {
            "job_id": state.job_id,
            "status": "finalizing",
            "event_cursor": event_cursor,
        }

    def _run_finalize_curation(
        self,
        state: JobState,
        request: CurationFinalize,
    ) -> None:
        temporary_root: Path | None = None
        training_root_created = False
        try:
            with state.lock:
                tagged_items = deepcopy(state.curation_items)
                output_root = self._output_root(state)
                lora_prefix = str(state.curation["lora_prefix"])
            caption_rule_data = load_caption_rule_data(
                self.settings.pixai_parent_rules_path,
                self.settings.pixai_parent_rules_strict,
            )
            selected_items, selection_report = select_dataset(
                tagged_items,
                request.target_size,
                request.people_count_target,
                request.framing_target,
                request.outdoors_target,
            )
            training_root = (output_root / f"training_dataset_{lora_prefix}").resolve()
            if not training_root.is_relative_to(output_root):
                raise PermissionError("training output is outside the task output directory")
            if training_root.exists():
                raise FileExistsError(f"training output already exists: {training_root.name}")
            temporary_root = (
                output_root / f".{training_root.name}.tmp-{state.job_id}-{uuid.uuid4().hex[:6]}"
            ).resolve()
            temporary_root.mkdir(parents=False)
            chosen = sorted(
                (item for item in selected_items if item["selection"]["selected"]),
                key=lambda item: item["selection"]["rank"],
            )
            total = len(chosen)
            self._event(
                state,
                "caption",
                "running",
                f"开始生成 {total} 组训练图片与 caption",
                0.01,
                {
                    "curation_flow": {
                        "event": "finalize_started",
                        "selected_images": total,
                    }
                },
            )
            for position, item in enumerate(chosen, start=1):
                source = self.curation_image_path(state, int(item["manifest_index"]))
                destination = temporary_root / source.name
                if destination.exists():
                    destination = temporary_root / (
                        f"{int(item['manifest_index']):06d}_{source.name}"
                    )
                shutil.copy2(source, destination)
                caption_result = build_caption_result(
                    item,
                    lora_prefix,
                    request.caption_threshold,
                    set(request.denylist),
                    soft_max_tags=self.settings.pixai_caption_max_tags,
                    hard_max_tags=self.settings.pixai_caption_hard_max_tags,
                    exclusive_margin=self.settings.pixai_caption_exclusive_margin,
                    pair_conflict_margin=self.settings.pixai_caption_pair_margin,
                    abstract_threshold=self.settings.pixai_caption_abstract_threshold,
                    remove_all_text_tags=self.settings.pixai_caption_remove_all_text_tags,
                    rule_data=caption_rule_data,
                )
                caption = caption_result.caption
                caption_path = destination.with_suffix(".txt")
                caption_path.write_text(caption, encoding="utf-8")
                item.update(
                    {
                        "caption": caption,
                        "caption_tags": caption_result.tags,
                        "caption_audit": caption_result.audit_log,
                        "training_image": destination.name,
                        "caption_file": caption_path.name,
                    }
                )
                progress = 0.05 + 0.90 * position / max(total, 1)
                self._event(
                    state,
                    "caption",
                    "running",
                    f"写入训练样本 {position}/{total} · {source.name}",
                    progress,
                    {
                        "captioned_images": position,
                        "curation_flow": {
                            "event": "caption_written",
                            "index": position,
                            "total": total,
                            "manifest_index": item["manifest_index"],
                            "filename": source.name,
                            "caption": caption,
                        },
                    },
                )

            selection_report.update(
                {
                    "job_id": state.job_id,
                    "resolved_trigger_prefix": lora_prefix,
                    "caption_threshold": request.caption_threshold,
                    "caption_max_tags": self.settings.pixai_caption_max_tags,
                    "caption_hard_max_tags": self.settings.pixai_caption_hard_max_tags,
                    "caption_policy": {
                        "order": ["basic_structure", *CAPTION_CATEGORY_ORDER],
                        "stages": [
                            "threshold",
                            "denylist",
                            "selection_features",
                            "alias",
                            "exclusive_conflicts",
                            "support_rules",
                            "removable_parents",
                            "semantic_sort",
                            "lora_prefix",
                            "txt_output",
                        ],
                        "exclusive_margin": self.settings.pixai_caption_exclusive_margin,
                        "pair_conflict_margin": self.settings.pixai_caption_pair_margin,
                        "abstract_threshold": self.settings.pixai_caption_abstract_threshold,
                        "remove_all_text_tags": (
                            self.settings.pixai_caption_remove_all_text_tags
                        ),
                        "parent_rules": {
                            "source": caption_rule_data.parent_rule_source,
                            "general_tag_count": caption_rule_data.general_tag_count,
                            "direct_relation_count": (
                                caption_rule_data.direct_parent_rule_count
                            ),
                            "blocked_relation_count": (
                                caption_rule_data.blocked_parent_rule_count
                            ),
                            "relation_count": caption_rule_data.parent_rule_count,
                            "strict_loading": self.settings.pixai_parent_rules_strict,
                        },
                    },
                    "denylist": request.denylist,
                    "default_denylist": sorted(DEFAULT_CAPTION_DENYLIST),
                    "effective_denylist": sorted(
                        DEFAULT_CAPTION_DENYLIST
                        | set(request.denylist)
                        | (
                            OPTIONAL_TEXT_DENYLIST
                            if self.settings.pixai_caption_remove_all_text_tags
                            else set()
                        )
                    ),
                }
            )
            self._write_json_atomic(temporary_root / "selection_report.json", selection_report)
            temporary_root.replace(training_root)
            training_root_created = True
            for item in selected_items:
                if item.get("training_image"):
                    item["training_image"] = str(training_root / item["training_image"])
                    item["caption_file"] = str(training_root / item["caption_file"])
            metadata_path = output_root / "pixai_tags.json"
            self._write_json_atomic(
                metadata_path,
                {
                    "job_id": state.job_id,
                    "model_id": self.settings.pixai_model_id,
                    "runtime_model_id": self.settings.pixai_runtime_model_id,
                    "resolved_trigger_prefix": lora_prefix,
                    "storage_threshold": self.settings.pixai_storage_threshold,
                    "selection_report": selection_report,
                    "items": selected_items,
                },
            )
            with state.lock:
                state.curation_items = selected_items
                state.curation.update(
                    {
                        "status": "completed",
                        "selected_images": total,
                        "training_output_dir": str(training_root),
                        "metadata_path": str(metadata_path),
                        "selection_report": selection_report,
                        "completed_at": utc_now().isoformat(),
                    }
                )
                state.stats["training_images"] = total
            self._event(
                state,
                "caption",
                "completed",
                "训练图片与 caption 已输出",
                1.0,
                {
                    "training_images": total,
                    "training_output_dir": str(training_root),
                    "curation_flow": {
                        "event": "pipeline_completed",
                        "selected_images": total,
                        "training_output_dir": str(training_root),
                    },
                },
            )
            with state.lock:
                state.status = "completed"
                state.finished_at = utc_now()
        except Exception as exc:  # noqa: BLE001 - publish output failures to the UI
            if temporary_root is not None and temporary_root.is_dir():
                shutil.rmtree(temporary_root, ignore_errors=True)
            if training_root_created and training_root.is_dir():
                shutil.rmtree(training_root, ignore_errors=True)
            self._event(
                state,
                "caption",
                "failed",
                "训练数据集生成失败",
                state.progress,
                {"error": str(exc), "curation_flow": {"event": "failed", "error": str(exc)}},
            )
            with state.lock:
                state.curation.update({"status": "awaiting_selection", "error": str(exc)})
                state.status = "awaiting_selection"
                state.finished_at = utc_now()

    def curation_summary(self, state: JobState) -> dict[str, Any]:
        with state.lock:
            curation = deepcopy(state.curation)
            items = deepcopy(state.curation_items)
        curation["job_id"] = state.job_id
        curation["workflow"] = state.workflow
        curation["items"] = [
            {
                "image_id": item["image_id"],
                "path": item["path"],
                "manifest_index": item["manifest_index"],
                "selection_features": item["selection_features"],
                "selection": item.get("selection", {"selected": False}),
                "top_general_tags": [
                    {"tag": tag, "score": score}
                    for tag, score in list(item.get("general_tags", {}).items())[:12]
                ],
                "caption": item.get("caption"),
                "caption_removed_count": len(item.get("caption_audit", [])),
                "training_image": item.get("training_image"),
                "caption_file": item.get("caption_file"),
            }
            for item in items
        ]
        return _json_safe(curation)

    def curation_image_path(self, state: JobState, item_index: int) -> Path:
        with state.lock:
            item = dict(self._review_item(state, item_index))
            source_key = "source" if state.workflow == "pixai_only" else "output"
            input_root = self._curation_input_root(state)
        source = item.get(source_key)
        if item.get("status") != "passed" or not source:
            raise FileNotFoundError("curation image not found")
        image_path = Path(str(source)).resolve()
        if not image_path.is_relative_to(input_root):
            raise PermissionError("curation image is outside the task input directory")
        if not image_path.is_file():
            raise FileNotFoundError("curation image file is missing")
        return image_path

    @staticmethod
    def audit_image_path(state: JobState, image_id: str) -> Path:
        with state.lock:
            source = state.audit_images.get(image_id)
            source_root = state.source_dir
        if not source:
            raise FileNotFoundError("audit image not found")
        source_path = Path(source).resolve()
        if not source_path.is_relative_to(Path(source_root).resolve()):
            raise PermissionError("audit image is outside the task source directory")
        if not source_path.is_file():
            raise FileNotFoundError("audit image file is missing")
        return source_path

    def remove_review_image(self, state: JobState, item_index: int) -> dict[str, Any]:
        with state.lock:
            if state.curation.get("status") not in {"not_started", "failed"}:
                raise ValueError("review is locked after PixAI submission")
            item = self._review_item(state, item_index)
            if item.get("status") != "passed" or not item.get("output"):
                raise ValueError("image is not part of the final dataset")

            output_root = self._output_root(state)
            source = Path(item["output"]).resolve()
            if not source.is_relative_to(output_root):
                raise PermissionError("review image is outside the task output directory")
            if not source.is_file():
                raise FileNotFoundError("review image file is missing")

            removed_root = self._removed_root(state, output_root)
            removed_root.mkdir(parents=True, exist_ok=True)
            destination = removed_root / source.name
            collision = 0
            while destination.exists():
                collision += 1
                destination = removed_root / f"{item_index:05d}_{collision:02d}_{source.name}"
            original_item = dict(item)
            shutil.move(str(source), str(destination))
            item.update(
                {
                    "output": None,
                    "status": "removed_by_review",
                    "reason": "removed_by_review",
                    "review_original_output": str(source),
                    "review_removed_path": str(destination),
                    "review_removed_at": utc_now().isoformat(),
                }
            )
            self._refresh_output_count(state)
            try:
                self._persist_manifest(state, output_root)
            except Exception:
                shutil.move(str(destination), str(source))
                item.clear()
                item.update(original_item)
                self._refresh_output_count(state)
                raise
            return {"item": _json_safe(item), "output_images": state.stats["output_images"]}

    def restore_review_image(self, state: JobState, item_index: int) -> dict[str, Any]:
        with state.lock:
            if state.curation.get("status") not in {"not_started", "failed"}:
                raise ValueError("review is locked after PixAI submission")
            item = self._review_item(state, item_index)
            if item.get("status") != "removed_by_review":
                raise ValueError("image was not removed by review")

            output_root = self._output_root(state)
            removed_root = self._removed_root(state, output_root)
            source = Path(item.get("review_removed_path", "")).resolve()
            destination = Path(item.get("review_original_output", "")).resolve()
            if not source.is_relative_to(removed_root) or not destination.is_relative_to(output_root):
                raise PermissionError("review recovery path is outside the task directories")
            if not source.is_file():
                raise FileNotFoundError("removed review image file is missing")
            if destination.exists():
                raise FileExistsError("original review image path is already occupied")

            original_item = dict(item)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))
            item.update({"output": str(destination), "status": "passed", "reason": None})
            item.pop("review_original_output", None)
            item.pop("review_removed_path", None)
            item.pop("review_removed_at", None)
            self._refresh_output_count(state)
            try:
                self._persist_manifest(state, output_root)
            except Exception:
                shutil.move(str(destination), str(source))
                item.clear()
                item.update(original_item)
                self._refresh_output_count(state)
                raise
            try:
                removed_root.rmdir()
            except OSError:
                pass
            return {"item": _json_safe(item), "output_images": state.stats["output_images"]}

    @staticmethod
    def _review_item(state: JobState, item_index: int) -> dict[str, Any]:
        if item_index < 0 or item_index >= len(state.manifest):
            raise IndexError("review image not found")
        return state.manifest[item_index]

    @staticmethod
    def _output_root(state: JobState) -> Path:
        if not state.output_dir:
            raise FileNotFoundError("task output directory is unavailable")
        return Path(state.output_dir).resolve()

    @staticmethod
    def _curation_input_root(state: JobState) -> Path:
        if state.workflow == "pixai_only":
            return Path(state.source_dir).resolve()
        return JobManager._output_root(state)

    @staticmethod
    def _removed_root(state: JobState, output_root: Path) -> Path:
        return (output_root.parent / f".{output_root.name}.review-removed-{state.job_id}").resolve()

    @staticmethod
    def _refresh_output_count(state: JobState) -> None:
        state.stats["output_images"] = sum(
            item.get("status") == "passed" and bool(item.get("output")) for item in state.manifest
        )

    @staticmethod
    def _persist_manifest(state: JobState, output_root: Path) -> None:
        manifest_path = Path(state.stats.get("manifest_path") or output_root / "manifest.json").resolve()
        if not manifest_path.is_relative_to(output_root):
            raise PermissionError("manifest is outside the task output directory")
        temporary_path = manifest_path.with_suffix(f"{manifest_path.suffix}.tmp")
        payload = {"job_id": state.job_id, "items": _json_safe(state.manifest)}
        temporary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary_path.replace(manifest_path)

    @staticmethod
    def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
        temporary_path = path.with_suffix(f"{path.suffix}.tmp")
        temporary_path.write_text(
            json.dumps(_json_safe(payload), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary_path.replace(path)
