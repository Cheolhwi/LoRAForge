from __future__ import annotations

import base64
import json
import random
import shutil
import threading
from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import numpy as np
from PIL import Image

from ..config import Settings
from ..schemas import PipelineOptions
from .clustering import complete_linkage_clusters
from .embedding import make_embedding_provider, make_pixai_embedding_provider
from .graph import build_mutual_topk_graph, connected_components, iterative_k_core
from .locate import inspect_image, make_locate_provider
from .scan import scan_images
from .types import Cluster, PipelineResult

EventCallback = Callable[[str, str, str, float, dict[str, Any]], None]


class PipelineEngine:
    def __init__(
        self,
        settings: Settings,
        event: EventCallback,
        similarity_model: str = "dinov3",
        minimum_pixels: int | None = None,
        complete_linkage_similarity: float | None = None,
        graph_similarity: float | None = None,
        pipeline_options: PipelineOptions | None = None,
    ):
        if similarity_model not in {"dinov3", "pixai"}:
            raise ValueError(f"unsupported similarity model: {similarity_model}")
        self.settings = settings
        self.event = event
        self.similarity_model = similarity_model
        self.minimum_pixels = (
            minimum_pixels if minimum_pixels is not None else self.settings.min_megapixels
        )
        self.complete_linkage_similarity = float(
            complete_linkage_similarity
            if complete_linkage_similarity is not None
            else self.settings.complete_linkage_similarity
        )
        self.graph_similarity = float(
            graph_similarity if graph_similarity is not None else self.settings.graph_similarity
        )
        for name, value in (
            ("complete_linkage_similarity", self.complete_linkage_similarity),
            ("graph_similarity", self.graph_similarity),
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")
        self.pipeline_options = pipeline_options or PipelineOptions()
        self._stop = threading.Event()

    def run(
        self,
        job_id: str,
        source_dir: Path,
        output_dir: Path | None,
        seed: int | None,
    ) -> PipelineResult:
        temporary_root = Path.cwd() / ".auto-cat-tmp"
        temporary_root.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix=f"{job_id}-", dir=temporary_root) as temporary_dir:
            temporary_path = Path(temporary_dir)
            result = self._run_pipeline(
                job_id,
                source_dir,
                output_dir,
                seed,
                temporary_path,
            )
        result.stats["temporary_images_cleaned"] = not temporary_path.exists()
        return result

    def _run_pipeline(
        self,
        job_id: str,
        source_dir: Path,
        output_dir: Path | None,
        seed: int | None,
        temporary_dir: Path,
    ) -> PipelineResult:
        rng = random.Random(seed if seed is not None else hash(job_id))
        minimum_label = (
            "720p"
            if self.minimum_pixels == 1280 * 720
            else f"{self.minimum_pixels / 1_000_000:g}MP"
        )
        scan_actions = ["扫描图片"]
        if self.pipeline_options.deduplicate:
            scan_actions.append("SHA-256 去重")
        if self.pipeline_options.resolution_filter:
            scan_actions.append(f"分辨率检查（≥ {minimum_label}）")
        self.emit(
            "scan",
            "running",
            "、".join(scan_actions),
            0.02,
            {
                "minimum_pixels": self.minimum_pixels,
                "minimum_resolution_label": minimum_label,
                "pipeline_options": self.pipeline_options.model_dump(),
            },
        )

        def emit_scan_progress(
            processed: int,
            total: int,
            scan_stats: dict[str, Any],
        ) -> None:
            self._ensure_not_stopped()
            fraction = processed / total if total else 1.0
            progress = 0.02 + (0.13 * fraction)
            message = f"扫描图片 {processed}/{total}"
            if scan_stats.get("read_retries"):
                message += f"，读取重试 {scan_stats['read_retries']} 次"
            if scan_stats.get("read_failures"):
                message += f"，跳过 {scan_stats['read_failures']} 个读取失败文件"
            self.emit("scan", "running", message, progress, scan_stats)

        records, scan_stats = scan_images(
            source_dir,
            self.minimum_pixels,
            deduplicate=self.pipeline_options.deduplicate,
            resolution_filter=self.pipeline_options.resolution_filter,
            on_progress=emit_scan_progress,
        )
        scan_message = "扫描阶段完成"
        if scan_stats.get("read_failures"):
            scan_message += f"，已跳过 {scan_stats['read_failures']} 个读取失败文件"
        self.emit("scan", "completed", scan_message, 0.15, scan_stats)
        self._ensure_not_stopped()

        prepared_images = 0
        embedding_dimension = 0
        if self.pipeline_options.embedding:
            if self.similarity_model == "pixai":
                embedding_label = "PixAI Tagger visual embedding"
                embedding_provider = make_pixai_embedding_provider(
                    self.settings.pixai_model_name,
                )
            else:
                embedding_label = "DINOv3 embedding"
                embedding_provider = make_embedding_provider(self.settings.dino_model_id)
            embedding_dimension = embedding_provider.dimension
            self.emit(
                "embedding",
                "running",
                f"生成 {embedding_label}（{embedding_provider.dimension} 维）",
                0.16,
                {"similarity_model": self.similarity_model},
            )
            try:
                for index, record in enumerate(records):
                    prepared_path = temporary_dir / f"{index:08d}.png"
                    record.embedding = embedding_provider.embed(record.path, prepared_path)
                    if prepared_path.exists():
                        record.prepared_path = prepared_path
                        prepared_images += 1
                    if index == len(records) - 1 or index % max(1, len(records) // 10) == 0:
                        progress = 0.16 + 0.20 * ((index + 1) / max(len(records), 1))
                        self.emit(
                            "embedding",
                            "running",
                            f"embedding {index + 1}/{len(records)}",
                            progress,
                            {},
                        )
            finally:
                embedding_provider.close()
            self.emit(
                "embedding",
                "completed",
                f"{embedding_label} 阶段完成",
                0.36,
                {
                    "embedding_dimension": embedding_dimension,
                    "embedding_model": self.similarity_model,
                    "prepared_images": prepared_images,
                },
            )
        else:
            self.emit(
                "embedding",
                "completed",
                "Visual Embedding 已旁路",
                0.36,
                {
                    "embedding_dimension": 0,
                    "embedding_model": "disabled",
                    "prepared_images": 0,
                    "skipped": True,
                },
            )
        self._ensure_not_stopped()

        clustering_similarity = self.complete_linkage_similarity
        clustering_label = f"{clustering_similarity:.2f}"
        if self.pipeline_options.clustering:
            self.emit(
                "clustering",
                "running",
                f"Complete-linkage {clustering_label} 聚簇并计算 medoid",
                0.38,
                {"similarity": clustering_similarity},
            )
            clusters = complete_linkage_clusters(records, clustering_similarity)
            clustering_message = f"得到 {len(clusters)} 个 {clustering_label} 簇"
        else:
            clusters = [
                Cluster(cluster_id=index, members=[record], medoid=record)
                for index, record in enumerate(records)
            ]
            clustering_message = f"聚簇已旁路，建立 {len(clusters)} 个单图簇"
        self.emit(
            "clustering",
            "completed",
            clustering_message,
            0.48,
            {
                "clusters": len(clusters),
                "cluster_sizes": [len(cluster.members) for cluster in clusters],
                "cluster_audit": self._cluster_audit_payload(clusters),
                "skipped": not self.pipeline_options.clustering,
            },
        )
        self._ensure_not_stopped()

        if self.pipeline_options.graph_filter:
            self.emit(
                "graph",
                "running",
                "建立 Mutual Top-20 图并迭代 3-core",
                0.50,
                {"similarity": self.graph_similarity},
            )
            involved_clusters, graph_audit = self._select_graph_component(clusters)
            graph_message = f"最大连通分量涉及 {len(involved_clusters)} 个簇"
        else:
            involved_clusters = {cluster.cluster_id for cluster in clusters}
            graph_audit = {
                "graph_nodes": len(clusters),
                "graph_edges": 0,
                "nodes_with_edges": 0,
                "core_nodes": len(clusters),
                "component_count": 1 if clusters else 0,
            }
            graph_message = f"图筛选已旁路，保留全部 {len(clusters)} 个簇"
        kept_images = sum(
            len(cluster.members) for cluster in clusters if cluster.cluster_id in involved_clusters
        )
        excluded_images = sum(
            len(cluster.members)
            for cluster in clusters
            if cluster.cluster_id not in involved_clusters
        )
        self.emit(
            "graph",
            "completed",
            graph_message,
            0.60,
            {
                "involved_clusters": sorted(involved_clusters),
                "core_degree": self.settings.core_degree,
                "skipped": not self.pipeline_options.graph_filter,
                "cluster_audit": {
                    "event": "graph_filtered",
                    "similarity": self.graph_similarity,
                    "top_k": self.settings.graph_top_k,
                    "core_degree": self.settings.core_degree,
                    "kept_cluster_ids": sorted(involved_clusters),
                    "kept_clusters": len(involved_clusters),
                    "excluded_clusters": len(clusters) - len(involved_clusters),
                    "kept_images": kept_images,
                    "excluded_images": excluded_images,
                    **graph_audit,
                },
            },
        )
        self._ensure_not_stopped()

        clusters_to_check = [
            cluster for cluster in clusters if cluster.cluster_id in involved_clusters
        ]
        if self.pipeline_options.locate:
            self.emit(
                "locate",
                "running",
                "只检查图筛选保留簇的候选",
                0.62,
                {},
            )
            locate_provider = make_locate_provider(
                self.settings.locate_anything_endpoint,
                self.settings.locate_anything_model_id,
                self.settings.locate_anything_timeout_seconds,
                self.settings.locate_anything_max_tokens,
            )
            try:
                manifest, locate_stats = self._run_locate_stage(
                    locate_provider,
                    clusters_to_check,
                    rng,
                    allow_retry=self.pipeline_options.retry,
                )
            finally:
                locate_provider.close()
        else:
            manifest, locate_stats = self._bypass_locate_stage(clusters_to_check)
        self._ensure_not_stopped()

        self.emit("output", "running", "复制通过图片并写入 manifest.json", 0.92, {})
        output_stats = self._write_output(job_id, source_dir, output_dir, manifest)
        stats = {
            **scan_stats,
            "embedding_dimension": embedding_dimension,
            "embedding_model": (
                self.similarity_model if self.pipeline_options.embedding else "disabled"
            ),
            "prepared_images": prepared_images,
            "clusters": len(clusters),
            "complete_linkage_similarity": self.complete_linkage_similarity,
            "graph_similarity": self.graph_similarity,
            "pipeline_options": self.pipeline_options.model_dump(),
            **locate_stats,
            **output_stats,
        }
        self.emit("output", "completed", "输出阶段完成", 1.0, stats)
        return PipelineResult(stats=stats, manifest=manifest)

    def _run_locate_stage(
        self,
        locate_provider,
        clusters_to_check,
        rng,
        *,
        allow_retry: bool = True,
    ):
        manifest: list[dict[str, Any]] = []
        locate_stats = {
            "checked_clusters": 0,
            "primary_pass": 0,
            "retried": 0,
            "retry_pass": 0,
            "dropped_clusters": 0,
        }
        self.emit(
            "locate",
            "running",
            f"准备检查 {len(clusters_to_check)} 个簇",
            0.62,
            {
                "locate_flow": {
                    "event": "pipeline_started",
                    "cluster_total": len(clusters_to_check),
                }
            },
        )
        for index, cluster in enumerate(clusters_to_check):
            locate_stats["checked_clusters"] += 1
            primary = cluster.medoid
            if primary is None:
                continue
            progress = 0.62 + 0.28 * (index / max(len(clusters_to_check), 1))
            primary_inspection = self._inspect_candidate(
                locate_provider,
                primary,
                cluster,
                "medoid",
                1,
                index + 1,
                len(clusters_to_check),
                progress,
            )
            if primary_inspection.meets:
                locate_stats["primary_pass"] += 1
                manifest.append(self._manifest_item(primary, cluster, "medoid", primary_inspection))
                cluster_result = {
                    "event": "cluster_result",
                    "cluster_id": cluster.cluster_id,
                    "status": "passed",
                    "candidate_role": "medoid",
                    "attempt": 1,
                }
            else:
                backup = self._choose_backup(cluster, rng) if allow_retry else None
                if backup is None:
                    locate_stats["dropped_clusters"] += 1
                    manifest.append(self._dropped_item(primary, cluster, primary_inspection))
                    cluster_result = {
                        "event": "cluster_result",
                        "cluster_id": cluster.cluster_id,
                        "status": "dropped",
                        "candidate_role": "medoid",
                        "attempt": 1,
                        "reason": primary_inspection.reason,
                        "retry_available": False,
                        "retry_disabled": not allow_retry,
                    }
                else:
                    locate_stats["retried"] += 1
                    self.emit(
                        "locate",
                        "running",
                        f"簇 {index + 1}/{len(clusters_to_check)} 切换备用候选",
                        progress,
                        {
                            "locate_flow": {
                                "event": "retry_scheduled",
                                "cluster_id": cluster.cluster_id,
                                "filename": backup.path.name,
                            }
                        },
                    )
                    retry = self._inspect_candidate(
                        locate_provider,
                        backup,
                        cluster,
                        "backup_retry",
                        2,
                        index + 1,
                        len(clusters_to_check),
                        progress,
                    )
                    if retry.meets:
                        locate_stats["retry_pass"] += 1
                        manifest.append(self._manifest_item(backup, cluster, "backup_retry", retry))
                        cluster_result = {
                            "event": "cluster_result",
                            "cluster_id": cluster.cluster_id,
                            "status": "passed",
                            "candidate_role": "backup_retry",
                            "attempt": 2,
                        }
                    else:
                        locate_stats["dropped_clusters"] += 1
                        manifest.append(self._dropped_item(backup, cluster, retry))
                        cluster_result = {
                            "event": "cluster_result",
                            "cluster_id": cluster.cluster_id,
                            "status": "dropped",
                            "candidate_role": "backup_retry",
                            "attempt": 2,
                            "reason": retry.reason,
                        }
            progress = 0.62 + 0.28 * ((index + 1) / max(len(clusters_to_check), 1))
            self.emit(
                "locate",
                "running",
                f"检查簇 {index + 1}/{len(clusters_to_check)}",
                progress,
                {**locate_stats, "locate_flow": cluster_result},
            )
        self.emit(
            "locate",
            "completed",
            "Locate Anything 检查完成",
            0.90,
            {
                **locate_stats,
                "locate_flow": {
                    "event": "pipeline_completed",
                    "checked_clusters": locate_stats["checked_clusters"],
                },
            },
        )
        return manifest, locate_stats

    def _bypass_locate_stage(
        self,
        clusters_to_check: list[Cluster],
    ) -> tuple[list[dict[str, Any]], dict[str, int | bool]]:
        manifest = []
        for cluster in clusters_to_check:
            if cluster.medoid is None:
                continue
            manifest.append(
                {
                    "source": str(cluster.medoid.path),
                    "output": None,
                    "cluster_id": cluster.cluster_id,
                    "candidate_role": "locate_bypassed",
                    "locate_attempt": 0,
                    "status": "passed",
                    "reason": None,
                }
            )
        locate_stats: dict[str, int | bool] = {
            "checked_clusters": 0,
            "primary_pass": 0,
            "retried": 0,
            "retry_pass": 0,
            "dropped_clusters": 0,
            "locate_bypassed": True,
        }
        self.emit(
            "locate",
            "completed",
            f"Locate Anything 已旁路，直接保留 {len(manifest)} 个候选",
            0.90,
            {
                **locate_stats,
                "locate_flow": {
                    "event": "pipeline_completed",
                    "checked_clusters": 0,
                    "skipped": True,
                },
            },
        )
        return manifest, locate_stats

    def _select_graph_component(self, clusters: list[Cluster]) -> tuple[set[int], dict[str, int]]:
        if not clusters:
            return set(), {
                "graph_nodes": 0,
                "graph_edges": 0,
                "nodes_with_edges": 0,
                "core_nodes": 0,
                "component_count": 0,
            }
        embeddings = np.stack([cluster.medoid.embedding for cluster in clusters])
        graph = build_mutual_topk_graph(
            embeddings,
            self.settings.graph_top_k,
            self.graph_similarity,
        )
        core = iterative_k_core(graph, self.settings.core_degree)
        components = connected_components(core)
        largest = components[0] if components else set()
        return largest, {
            "graph_nodes": len(graph),
            "graph_edges": sum(len(neighbors) for neighbors in graph.values()) // 2,
            "nodes_with_edges": sum(bool(neighbors) for neighbors in graph.values()),
            "core_nodes": len(core),
            "component_count": len(components),
        }

    def _cluster_audit_payload(self, clusters: list[Cluster]) -> dict[str, Any]:
        audit_clusters = []
        for cluster in clusters:
            medoid_index = next(
                index for index, member in enumerate(cluster.members) if member is cluster.medoid
            )
            if any(member.embedding is None for member in cluster.members):
                similarities = np.eye(len(cluster.members), dtype=np.float32)
                minimum_similarity = 1.0 if len(cluster.members) == 1 else 0.0
            else:
                embeddings = np.stack([member.embedding for member in cluster.members])
                similarities = np.clip(embeddings @ embeddings.T, -1.0, 1.0)
                if len(cluster.members) == 1:
                    minimum_similarity = 1.0
                else:
                    minimum_similarity = float(
                        similarities[np.triu_indices(len(cluster.members), k=1)].min()
                    )

            audit_clusters.append(
                {
                    "cluster_id": cluster.cluster_id,
                    "size": len(cluster.members),
                    "minimum_similarity": minimum_similarity,
                    "members": [
                        {
                            "image_id": member.sha256,
                            "filename": member.path.name,
                            "source": str(member.path),
                            "role": "medoid" if member is cluster.medoid else "member",
                            "similarity_to_medoid": float(similarities[index, medoid_index]),
                        }
                        for index, member in enumerate(cluster.members)
                    ],
                }
            )

        return {
            "event": "clusters_ready",
            "similarity": self.complete_linkage_similarity,
            "total_images": sum(len(cluster.members) for cluster in clusters),
            "clusters": audit_clusters,
        }

    @staticmethod
    def _choose_backup(cluster: Cluster, rng: random.Random):
        if not cluster.backup_candidates:
            return None
        return rng.choice(cluster.backup_candidates)

    def _inspect_candidate(
        self,
        provider,
        image,
        cluster,
        role: str,
        attempt: int,
        cluster_index: int,
        cluster_total: int,
        progress: float,
    ):
        inspection_path = image.prepared_path or image.path
        preview, width, height = self._preview_data_url(inspection_path)
        common = {
            "cluster_id": cluster.cluster_id,
            "cluster_index": cluster_index,
            "cluster_total": cluster_total,
            "attempt": attempt,
            "candidate_role": role,
            "filename": image.path.name,
            "source": str(image.path),
        }
        self.emit(
            "locate",
            "running",
            f"簇 {cluster_index}/{cluster_total} · 载入 {image.path.name}",
            progress,
            {
                "locate_flow": {
                    **common,
                    "event": "candidate_loaded",
                    "preview": preview,
                    "preview_width": width,
                    "preview_height": height,
                }
            },
        )

        def on_step(check: str, status: str, boxes: list[list[float]]):
            normalized_boxes = self._normalize_boxes(boxes, width, height) if boxes else []
            check_name = "水印" if check == "watermark" else "漫画/拼图"
            if status == "running":
                message = f"簇 {cluster_index}/{cluster_total} · {check_name}检查中"
            elif status == "skipped":
                message = f"簇 {cluster_index}/{cluster_total} · 已检测到水印，跳过漫画/拼图检查"
            else:
                message = f"簇 {cluster_index}/{cluster_total} · {check_name}返回 {len(boxes)} 个框"
            self.emit(
                "locate",
                "running",
                message,
                progress,
                {
                    "locate_flow": {
                        **common,
                        "event": f"check_{status}",
                        "check": check,
                        "boxes": normalized_boxes,
                        "box_count": len(boxes),
                    }
                },
            )

        inspection = inspect_image(provider, inspection_path, attempt, on_step=on_step)
        self.emit(
            "locate",
            "running",
            (
                f"簇 {cluster_index}/{cluster_total} · 当前候选通过"
                if inspection.meets
                else f"簇 {cluster_index}/{cluster_total} · 当前候选不通过"
            ),
            progress,
            {
                "locate_flow": {
                    **common,
                    "event": "candidate_result",
                    "status": "passed" if inspection.meets else "not_meet",
                    "reason": inspection.reason,
                }
            },
        )
        return inspection

    @staticmethod
    def _preview_data_url(path: Path) -> tuple[str, int, int]:
        with Image.open(path) as image:
            width, height = image.size
            preview = image.convert("RGB")
        preview.thumbnail((512, 512), Image.Resampling.LANCZOS)
        buffer = BytesIO()
        preview.save(buffer, format="JPEG", quality=74, optimize=True)
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return f"data:image/jpeg;base64,{encoded}", width, height

    @staticmethod
    def _normalize_boxes(boxes: list[list[float]], width: int, height: int) -> list[list[float]]:
        normalized = []
        for box in boxes:
            if len(box) < 4:
                continue
            x1, y1, x2, y2 = (float(value) for value in box[:4])
            if all(0 <= value <= 1 for value in (x1, y1, x2, y2)):
                values = [x1, y1, x2, y2]
            elif max(x1, x2) > width or max(y1, y2) > height:
                values = [x1 / 1000, y1 / 1000, x2 / 1000, y2 / 1000]
            else:
                values = [x1 / width, y1 / height, x2 / width, y2 / height]
            normalized.append([max(0.0, min(1.0, value)) for value in values])
        return normalized

    @staticmethod
    def _manifest_item(image, cluster, role, inspection):
        return {
            "source": str(image.path),
            "output": None,
            "cluster_id": cluster.cluster_id,
            "candidate_role": role,
            "locate_attempt": inspection.attempt,
            "status": "passed",
            "reason": None,
        }

    @staticmethod
    def _dropped_item(image, cluster, inspection):
        return {
            "source": str(image.path),
            "output": None,
            "cluster_id": cluster.cluster_id,
            "candidate_role": "dropped",
            "locate_attempt": inspection.attempt,
            "status": "not_meet",
            "reason": inspection.reason,
        }

    def _write_output(self, job_id: str, source_dir: Path, output_dir: Path | None, manifest):
        if output_dir is None:
            output_dir = source_dir / f"filtered_dataset_{job_id}"
        output_dir.mkdir(parents=True, exist_ok=True)
        passed = 0
        for index, item in enumerate(manifest, start=1):
            if item["status"] != "passed":
                continue
            source = Path(item["source"])
            destination = output_dir / f"{index:05d}_{source.name}"
            shutil.copy2(source, destination)
            item["output"] = str(destination)
            passed += 1
        manifest_path = output_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps({"job_id": job_id, "items": manifest}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return {
            "output_images": passed,
            "output_dir": str(output_dir),
            "manifest_path": str(manifest_path),
        }

    def emit(self, stage, status, message, progress, data):
        self.event(stage, status, message, progress, data)

    def _ensure_not_stopped(self):
        if self._stop.is_set():
            raise RuntimeError("pipeline stopped")
