import asyncio
import json
from io import BytesIO
from pathlib import Path

import httpx
import numpy as np
import pytest
from app import folder_dialog
from app import jobs as jobs_module
from app import main as main_module
from app.config import Settings
from app.jobs import JobManager, JobState, _json_safe
from app.pipeline import caption_rules as caption_rules_module
from app.pipeline import engine as engine_module
from app.pipeline.caption_rules import (
    CaptionRuleData,
    build_caption_result,
)
from app.pipeline.clustering import complete_linkage_clusters
from app.pipeline.curation import (
    DEFAULT_CAPTION_DENYLIST,
    build_caption,
    derive_selection_features,
    select_dataset,
)
from app.pipeline.embedding import (
    PixAIEmbeddingProvider,
    _save_preprocessed_image,
)
from app.pipeline.engine import PipelineEngine
from app.pipeline.graph import build_mutual_topk_graph, connected_components, iterative_k_core
from app.pipeline.locate import (
    LocateAnythingHttpProvider,
    _extract_boxes,
    inspect_image,
)
from app.pipeline.pixai_parent_rules import load_pixai_parent_rules
from app.pipeline.prompts import COMIC_PROMPT, WATERMARK_PROMPT
from app.pipeline.scan import scan_images
from app.pipeline.types import Cluster, ImageRecord, Inspection, PipelineResult
from app.schemas import CurationFinalize, CurationStart, JobCreate, PixAIJobCreate
from PIL import Image
from pydantic import ValidationError


class FakeEmbeddingProvider:
    dimension = 1024

    def embed(self, path: Path, prepared_path: Path | None = None) -> np.ndarray:
        with Image.open(path) as image:
            pixels = np.asarray(
                image.convert("L").resize((32, 32), Image.Resampling.LANCZOS),
                dtype=np.float32,
            ).reshape(-1)
            if prepared_path is not None:
                image.convert("RGB").resize((448, 448), Image.Resampling.BILINEAR).save(
                    prepared_path,
                    format="PNG",
                )
        pixels -= pixels.mean()
        norm = np.linalg.norm(pixels)
        if norm <= 1e-12:
            pixels = np.ones(self.dimension, dtype=np.float32)
            norm = np.linalg.norm(pixels)
        return (pixels / norm).astype(np.float32)

    def close(self) -> None:
        return None


class FakeLocateAnythingProvider:
    def locate(self, path: Path, prompt: str) -> list[list[float]]:
        name = path.stem.casefold()
        if prompt == WATERMARK_PROMPT and any(
            token in name for token in ("watermark", "logo", "sample")
        ):
            return [[0.1, 0.1, 0.4, 0.2]]
        if prompt == COMIC_PROMPT and any(
            token in name for token in ("comic", "collage", "manga", "panel")
        ):
            return [[0.0, 0.0, 0.45, 1.0], [0.55, 0.0, 1.0, 1.0]]
        return []

    def close(self) -> None:
        return None


class FakePixAITagger:
    def tag(self, image_path: Path) -> dict[str, float]:
        return {
            "1girl": 0.96,
            "solo": 0.93,
            "looking_at_viewer": 0.82,
            "upper_body": 0.78,
            "indoors": 0.74,
            "long_hair": 0.72,
            "smile": 0.61,
        }

    def close(self) -> None:
        return None


def make_caption_rule_item(
    tags: dict[str, float],
    people_value: int | str = 1,
    people_source: str = "1girl",
) -> dict:
    return {
        "general_tags": tags,
        "selection_features": {
            "people_count": {
                "value": people_value,
                "source_tag": people_source,
                "confidence": 0.95,
            },
            "framing": {
                "value": "half_body",
                "source_tag": "upper_body",
                "confidence": 0.88,
            },
            "outdoors": {
                "value": False,
                "source_tag": "indoors",
                "confidence": 0.84,
            },
        },
    }


def test_pixai_selection_features_keep_selection_fields_separate():
    features = derive_selection_features(
        {
            "1girl": 0.94,
            "solo": 0.91,
            "cowboy_shot": 0.73,
            "upper_body": 0.62,
            "outdoors": 0.92,
            "long_hair": 0.88,
        }
    )

    assert features["people_count"]["value"] == 1
    assert features["framing"]["value"] == "half_body"
    assert features["framing"]["source_tag"] == "cowboy_shot"
    assert features["outdoors"]["value"] is True


def test_pixai_outdoors_stays_unknown_without_indoor_or_outdoor_evidence():
    features = derive_selection_features({"1girl": 0.9, "simple_background": 0.95})

    assert features["outdoors"]["value"] is None
    assert features["outdoors"]["status"] == "unknown"


def test_margin_selection_fills_people_distribution():
    def item(image_id, people, framing, outdoors):
        return {
            "image_id": image_id,
            "selection_features": {
                "people_count": {"value": people, "confidence": 0.9},
                "framing": {"value": framing, "confidence": 0.9},
                "outdoors": {"value": outdoors, "confidence": 0.9},
            },
            "general_tags": {},
            "selection": {"selected": False},
        }

    selected, report = select_dataset(
        [
            item("a", 1, "half_body", True),
            item("b", 1, "headshot", False),
            item("c", 2, "full_body", False),
        ],
        target_size=2,
        people_target={"1": 0.5, "2": 0.5, "3_plus": 0.0},
        framing_target={"full_body": 0.5, "half_body": 0.5, "headshot": 0.0},
        outdoors_target={"true": 0.5, "false": 0.5},
    )

    chosen_people = {
        entry["selection_features"]["people_count"]["value"]
        for entry in selected
        if entry["selection"]["selected"]
    }
    assert chosen_people == {1, 2}
    assert report["selected_size"] == 2


def test_caption_uses_prefix_denylist_and_selection_overrides():
    item = {
        "general_tags": {
            "watermark": 0.99,
            "2girls": 0.93,
            "1girl": 0.91,
            "full_body": 0.88,
            "upper_body": 0.81,
            "outdoors": 0.79,
            "indoors": 0.72,
            "long_hair": 0.70,
        },
        "selection_features": {
            "people_count": {
                "value": 1,
                "source_tag": "1girl",
                "confidence": 0.91,
            },
            "framing": {
                "value": "half_body",
                "source_tag": "upper_body",
                "confidence": 0.81,
            },
            "outdoors": {
                "value": False,
                "source_tag": "indoors",
                "confidence": 0.72,
            },
        },
    }

    caption = build_caption(item, "artist_style", 0.35)

    assert caption.startswith("artist_style, ")
    assert "watermark" not in caption
    assert "2girls" not in caption
    assert "full_body" not in caption
    assert "outdoors" not in caption
    assert "1girl" in caption
    assert "solo" in caption
    assert "upper_body" in caption
    assert "indoors" in caption


def test_caption_limits_total_tags_but_keeps_structural_tags():
    general_tags = {
        **{f"detail_tag_{index:02d}": 0.99 - index * 0.01 for index in range(30)},
        "1girl": 0.91,
        "solo": 0.89,
        "upper_body": 0.81,
        "indoors": 0.72,
    }
    item = {
        "general_tags": general_tags,
        "selection_features": {
            "people_count": {
                "value": 1,
                "source_tag": "1girl",
                "confidence": 0.91,
            },
            "framing": {
                "value": "half_body",
                "source_tag": "upper_body",
                "confidence": 0.81,
            },
            "outdoors": {
                "value": False,
                "source_tag": "indoors",
                "confidence": 0.72,
            },
        },
    }

    caption = build_caption(item, "artist_style", 0.35, max_tags=8)
    tags = caption.split(", ")

    assert len(tags) == 8
    assert tags[0] == "artist_style"
    assert {"1girl", "solo", "upper_body", "indoors"} <= set(tags)
    assert {"detail_tag_00", "detail_tag_01", "detail_tag_02"} <= set(tags)


def test_caption_prioritizes_semantic_groups_over_high_score_noise():
    item = {
        "general_tags": {
            **{f"noise_tag_{index:02d}": 0.99 - index * 0.001 for index in range(20)},
            "walking": 0.72,
            "hugging": 0.71,
            "long_hair": 0.70,
            "red_ribbon": 0.69,
            "sitting": 0.68,
            "smile": 0.67,
            "forest": 0.66,
            "1girl": 0.91,
            "solo": 0.89,
            "upper_body": 0.81,
            "indoors": 0.72,
        },
        "selection_features": {
            "people_count": {
                "value": 1,
                "source_tag": "1girl",
                "confidence": 0.91,
            },
            "framing": {
                "value": "half_body",
                "source_tag": "upper_body",
                "confidence": 0.81,
            },
            "outdoors": {
                "value": False,
                "source_tag": "indoors",
                "confidence": 0.72,
            },
        },
    }

    tags = build_caption(item, "artist_style", 0.35, max_tags=12).split(", ")

    assert len(tags) == 12
    assert {
        "walking",
        "hugging",
        "long_hair",
        "red_ribbon",
        "sitting",
        "smile",
        "forest",
    } <= set(tags)
    assert not any(tag.startswith("noise_tag_") for tag in tags)


def test_default_caption_denylist_removes_censoring_tags():
    censoring_tags = {
        "censored",
        "uncensored",
        "mosaic_censoring",
        "bar_censor",
        "censor_bar",
        "blur_censor",
        "light_censor",
        "convenient_censoring",
    }

    assert censoring_tags <= DEFAULT_CAPTION_DENYLIST


def test_caption_rules_normalize_aliases_and_keep_highest_score():
    rule_data = CaptionRuleData(
        aliases={"gray_hair": "grey_hair"},
        removable_parents={},
    )
    result = build_caption_result(
        make_caption_rule_item(
            {
                "Gray  Hair,": 0.81,
                "grey_hair": 0.72,
                "1girl": 0.95,
                "upper_body": 0.88,
                "indoors": 0.84,
            }
        ),
        "artist_style",
        0.50,
        rule_data=rule_data,
    )

    assert result.tags.count("grey_hair") == 1
    assert "gray_hair" not in result.tags
    assert any(entry["reason"] == "alias_duplicate" for entry in result.audit_log)


def test_caption_threshold_runs_before_alias_score_merge():
    rule_data = CaptionRuleData(
        aliases={"legacy_pose": "canonical_pose"},
        removable_parents={},
    )
    result = build_caption_result(
        make_caption_rule_item(
            {
                "legacy_pose": 0.49,
                "canonical_pose": 0.72,
                "1girl": 0.95,
                "upper_body": 0.88,
                "indoors": 0.84,
            }
        ),
        "artist_style",
        0.50,
        rule_data=rule_data,
    )

    assert "canonical_pose" in result.tags
    assert any(
        entry["tag"] == "legacy_pose" and entry["reason"] == "below_threshold"
        for entry in result.audit_log
    )
    assert not any(
        entry["reason"] == "alias_duplicate" and entry.get("canonical_tag") == "canonical_pose"
        for entry in result.audit_log
    )


def test_caption_threshold_uses_canonical_risk_group_without_early_aliasing():
    rule_data = CaptionRuleData(
        aliases={"legacy_mind_control": "mind_control"},
        removable_parents={},
    )
    result = build_caption_result(
        make_caption_rule_item(
            {
                "legacy_mind_control": 0.60,
                "1girl": 0.95,
                "upper_body": 0.88,
                "indoors": 0.84,
            }
        ),
        "artist_style",
        0.50,
        abstract_threshold=0.65,
        rule_data=rule_data,
    )

    assert "mind_control" not in result.tags
    assert any(
        entry["tag"] == "legacy_mind_control"
        and entry["reason"] == "below_threshold"
        and entry["required_threshold"] == 0.65
        and entry["canonical_tag"] == "mind_control"
        for entry in result.audit_log
    )


def test_caption_aliases_selection_injections_and_updates_protected_tags():
    rule_data = CaptionRuleData(
        aliases={
            "portrait": "upper_body",
            "torso_view": "upper_body",
        },
        removable_parents={},
    )
    item = make_caption_rule_item(
        {
            "torso_view": 0.72,
            **{f"detail_{index}": 0.99 - index * 0.01 for index in range(12)},
        }
    )
    item["selection_features"]["framing"]["source_tag"] = "portrait"

    result = build_caption_result(
        item,
        "artist_style",
        0.50,
        soft_max_tags=8,
        hard_max_tags=8,
        rule_data=rule_data,
    )

    assert result.tags[:4] == ["1girl", "solo", "upper_body", "indoors"]
    assert "portrait" not in result.tags
    assert "torso_view" not in result.tags
    assert any(
        entry["reason"] == "selection_override"
        and entry["tag"] == "torso_view"
        for entry in result.audit_log
    )


def test_selection_override_removes_stale_structural_aliases_before_aliasing():
    rule_data = CaptionRuleData(
        aliases={
            "legacy_full_body": "full_body",
            "legacy_1girl": "1girl",
        },
        removable_parents={},
    )
    item = make_caption_rule_item(
        {
            "legacy_full_body": 0.99,
            "legacy_1girl": 0.98,
            "2girls": 0.94,
            "indoors": 0.84,
        },
        people_value=2,
        people_source="2girls",
    )

    result = build_caption_result(
        item,
        "artist_style",
        0.50,
        rule_data=rule_data,
    )

    assert "2girls" in result.tags
    assert "upper_body" in result.tags
    assert not {"legacy_1girl", "1girl", "legacy_full_body", "full_body"} & set(
        result.tags
    )


def test_selection_override_removes_singular_people_tags_when_switching_to_group():
    result = build_caption_result(
        make_caption_rule_item(
            {
                "1girl": 0.97,
                "2girls": 0.94,
                "upper_body": 0.88,
                "indoors": 0.84,
            },
            people_value=2,
            people_source="2girls",
        ),
        "artist_style",
        0.50,
    )

    assert "2girls" in result.tags
    assert "1girl" not in result.tags
    assert "solo" not in result.tags


def test_caption_canonical_denylist_blocks_legacy_alias_before_aliasing():
    rule_data = CaptionRuleData(
        aliases={"legacy_watermark": "watermark"},
        removable_parents={},
    )
    result = build_caption_result(
        make_caption_rule_item(
            {
                "legacy_watermark": 0.99,
                "1girl": 0.95,
                "upper_body": 0.88,
                "indoors": 0.84,
            }
        ),
        "artist_style",
        0.50,
        rule_data=rule_data,
    )

    assert not {"legacy_watermark", "watermark"} & set(result.tags)
    assert any(
        entry["tag"] == "legacy_watermark"
        and entry["reason"] == "denylisted"
        and entry["canonical_tag"] == "watermark"
        for entry in result.audit_log
    )


def test_caption_rules_remove_ambiguous_single_person_eye_colors_but_keep_multi_person():
    tags = {
        "brown_eyes": 0.69,
        "black_eyes": 0.66,
        "1girl": 0.95,
        "upper_body": 0.88,
        "indoors": 0.84,
    }
    single_result = build_caption_result(
        make_caption_rule_item(tags),
        "artist_style",
        0.50,
    )
    multi_result = build_caption_result(
        make_caption_rule_item(
            {**tags, "2girls": 0.94},
            people_value=2,
            people_source="2girls",
        ),
        "artist_style",
        0.50,
    )

    assert not {"brown_eyes", "black_eyes"} & set(single_result.tags)
    assert {"brown_eyes", "black_eyes"} <= set(multi_result.tags)
    assert any(
        entry["reason"] == "exclusive_ambiguous"
        and entry["tag"] in {"brown_eyes", "black_eyes"}
        for entry in single_result.audit_log
    )


def test_caption_rules_keep_clear_exclusive_winner_and_remove_ambiguous_footwear():
    result = build_caption_result(
        make_caption_rule_item(
            {
                "brown_eyes": 0.84,
                "black_eyes": 0.57,
                "barefoot": 0.61,
                "socks": 0.64,
                "1girl": 0.95,
                "upper_body": 0.88,
                "indoors": 0.84,
            }
        ),
        "artist_style",
        0.50,
    )

    assert "brown_eyes" in result.tags
    assert "black_eyes" not in result.tags
    assert "barefoot" not in result.tags
    assert "socks" not in result.tags


def test_caption_parent_cleanup_runs_after_exclusive_resolution():
    rule_data = CaptionRuleData(
        aliases={},
        removable_parents={"red_eyes": {"eyes"}},
    )
    result = build_caption_result(
        make_caption_rule_item(
            {
                "blue_eyes": 0.90,
                "eyes": 0.80,
                "red_eyes": 0.60,
                "1girl": 0.95,
                "upper_body": 0.88,
                "indoors": 0.84,
            }
        ),
        "artist_style",
        0.50,
        rule_data=rule_data,
    )

    assert "blue_eyes" in result.tags
    assert "eyes" in result.tags
    assert "red_eyes" not in result.tags
    assert any(
        entry["tag"] == "red_eyes" and entry["reason"] == "exclusive_loser"
        for entry in result.audit_log
    )
    assert not any(
        entry["tag"] == "eyes" and entry["reason"] == "redundant_parent"
        for entry in result.audit_log
    )


def test_caption_support_rules_check_survivors_after_conflicts(monkeypatch):
    monkeypatch.setitem(
        caption_rules_module.ABSTRACT_SUPPORT_RULES,
        "mind_control",
        {"red_eyes"},
    )
    result = build_caption_result(
        make_caption_rule_item(
            {
                "blue_eyes": 0.90,
                "mind_control": 0.80,
                "red_eyes": 0.60,
                "1girl": 0.95,
                "upper_body": 0.88,
                "indoors": 0.84,
            }
        ),
        "artist_style",
        0.50,
    )

    assert "red_eyes" not in result.tags
    assert "mind_control" not in result.tags
    conflict_index = next(
        index
        for index, entry in enumerate(result.audit_log)
        if entry["tag"] == "red_eyes" and entry["reason"] == "exclusive_loser"
    )
    support_index = next(
        index
        for index, entry in enumerate(result.audit_log)
        if entry["tag"] == "mind_control" and entry["reason"] == "missing_support"
    )
    assert conflict_index < support_index


def test_caption_cleanup_is_set_idempotent():
    rule_data = CaptionRuleData(
        aliases={"legacy_red_eyes": "red_eyes"},
        removable_parents={"red_eyes": {"eyes"}},
    )
    item = make_caption_rule_item(
        {
            "legacy_red_eyes": 0.90,
            "eyes": 0.80,
            "black_eyes": 0.55,
            "watermark": 0.99,
            "1girl": 0.95,
            "upper_body": 0.88,
            "indoors": 0.84,
        }
    )

    first = build_caption_result(
        item,
        "artist_style",
        0.50,
        rule_data=rule_data,
    )
    second = build_caption_result(
        {
            **item,
            "general_tags": {tag: 1.0 for tag in first.tags},
        },
        "artist_style",
        0.50,
        rule_data=rule_data,
    )

    assert set(second.tags) == set(first.tags)


def test_caption_rules_apply_compact_implications_and_preserve_compatible_tags():
    result = build_caption_result(
        make_caption_rule_item(
            {
                "1girl": 0.96,
                "full_body": 0.90,
                "indoors": 0.88,
                "from_above": 0.82,
                "looking_at_viewer": 0.80,
                "looking_up": 0.78,
                "school_uniform": 0.77,
                "skirt": 0.75,
                "plaid_clothes": 0.73,
                "plaid_skirt": 0.81,
                "pleated_skirt": 0.79,
                "serafuku": 0.83,
                "short_hair": 0.76,
                "chair": 0.65,
            }
        ),
        "artist_style",
        0.50,
    )

    assert {"serafuku", "plaid_skirt", "pleated_skirt"} <= set(result.tags)
    assert not {"school_uniform", "skirt", "plaid_clothes"} & set(result.tags)
    assert {"from_above", "looking_at_viewer", "looking_up"} <= set(result.tags)


def test_caption_rules_only_remove_text_tags_when_enabled():
    item = make_caption_rule_item(
        {
            "1girl": 0.95,
            "upper_body": 0.88,
            "indoors": 0.84,
            "text": 0.79,
            "speech_bubble": 0.73,
        }
    )

    default_result = build_caption_result(item, "artist_style", 0.50)
    strict_result = build_caption_result(
        item,
        "artist_style",
        0.50,
        remove_all_text_tags=True,
    )

    assert {"text", "speech_bubble"} <= set(default_result.tags)
    assert not {"text", "speech_bubble"} & set(strict_result.tags)
    assert {
        entry["tag"]
        for entry in strict_result.audit_log
        if entry["reason"] == "denylisted"
    } >= {"text", "speech_bubble"}


def test_settings_reject_caption_soft_limit_above_hard_limit():
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            pixai_caption_max_tags=65,
            pixai_caption_hard_max_tags=64,
        )


def test_lora_prefix_rejects_spaces():
    with pytest.raises(ValidationError):
        CurationStart(lora_prefix="bad prefix")


def test_curation_pipeline_writes_metadata_images_and_captions(monkeypatch, tmp_path):
    output_dir = tmp_path / "filtered"
    output_dir.mkdir()
    output_image = output_dir / "00001-image.png"
    Image.new("RGB", (64, 64), "purple").save(output_image)
    state = JobState("curation-job", str(tmp_path), str(output_dir))
    state.status = "completed"
    state.manifest = [
        {
            "source": str(tmp_path / "source.png"),
            "output": str(output_image),
            "cluster_id": 0,
            "candidate_role": "medoid",
            "locate_attempt": 1,
            "status": "passed",
            "reason": None,
        }
    ]

    class InlineExecutor:
        @staticmethod
        def submit(callback, *args):
            callback(*args)

    monkeypatch.setattr(
        jobs_module,
        "make_pixai_tagger",
        lambda *args: FakePixAITagger(),
    )
    manager = JobManager(Settings(pixai_caption_remove_all_text_tags=True))
    manager.executor = InlineExecutor()

    manager.start_curation(state, "artist_style")

    assert state.status == "awaiting_selection"
    assert state.curation["status"] == "awaiting_selection"
    assert (output_dir / "pixai_tags.json").is_file()
    summary = manager.curation_summary(state)
    assert "general_tags" not in summary["items"][0]
    assert summary["items"][0]["top_general_tags"]

    manager.finalize_curation(state, CurationFinalize(target_size=1))

    training_dir = output_dir / "training_dataset_artist_style"
    assert state.status == "completed"
    assert state.curation["status"] == "completed"
    assert (training_dir / output_image.name).is_file()
    caption_path = training_dir / output_image.with_suffix(".txt").name
    assert caption_path.read_text(encoding="utf-8").startswith("artist_style, ")
    assert (training_dir / "selection_report.json").is_file()
    metadata = json.loads((output_dir / "pixai_tags.json").read_text(encoding="utf-8"))
    selected_metadata = next(
        item for item in metadata["items"] if item["selection"]["selected"]
    )
    assert isinstance(selected_metadata["caption_tags"], list)
    assert isinstance(selected_metadata["caption_audit"], list)
    parent_policy = metadata["selection_report"]["caption_policy"]["parent_rules"]
    assert metadata["selection_report"]["caption_policy"]["stages"] == [
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
    ]
    parent_rules_path = (
        Path(__file__).resolve().parents[1]
        / "backend"
        / "app"
        / "pipeline"
        / "resources"
        / "pixai_parent_rules.json"
    )
    loaded_parent_rules = load_pixai_parent_rules(str(parent_rules_path), strict=True)
    expected_relation_count = loaded_parent_rules.parent_relation_count
    assert parent_policy["general_tag_count"] == 9741
    assert parent_policy["direct_relation_count"] == (
        loaded_parent_rules.direct_relation_count
    )
    assert parent_policy["blocked_relation_count"] == (
        loaded_parent_rules.blocked_relation_count
    )
    assert 4000 < parent_policy["direct_relation_count"] < expected_relation_count
    assert expected_relation_count > 5000
    assert parent_policy["relation_count"] == expected_relation_count
    assert "censored" in metadata["selection_report"]["effective_denylist"]
    assert "speech_bubble" in metadata["selection_report"]["effective_denylist"]


def test_pixai_only_uses_all_folder_images_without_visual_filtering(monkeypatch, tmp_path):
    source_dir = tmp_path / "source"
    first_dir = source_dir / "first"
    second_dir = source_dir / "second"
    output_dir = source_dir / "pixai-output"
    first_dir.mkdir(parents=True)
    second_dir.mkdir()
    output_dir.mkdir()
    first_image = first_dir / "same.png"
    second_image = second_dir / "same.png"
    excluded_output_image = output_dir / "old-output.png"
    Image.new("RGB", (16, 16), "purple").save(first_image)
    first_image_bytes = first_image.read_bytes()
    second_image.write_bytes(first_image_bytes)
    Image.new("RGB", (16, 16), "orange").save(excluded_output_image)
    (source_dir / "notes.txt").write_text("not an image", encoding="utf-8")

    class InlineExecutor:
        @staticmethod
        def submit(callback, *args):
            callback(*args)

    monkeypatch.setattr(
        jobs_module,
        "make_pixai_tagger",
        lambda *args: FakePixAITagger(),
    )
    manager = JobManager(Settings())
    manager.executor = InlineExecutor()

    state, result = manager.create_pixai_only(
        str(source_dir),
        str(output_dir),
        "direct_style",
    )

    assert state.workflow == "pixai_only"
    assert result["source_images"] == 2
    assert {Path(item["source"]) for item in state.manifest} == {
        first_image.resolve(),
        second_image.resolve(),
    }
    assert all(item["output"] is None for item in state.manifest)
    assert state.curation["status"] == "awaiting_selection"
    assert manager.curation_image_path(state, 0).is_relative_to(source_dir)
    metadata = json.loads((output_dir / "pixai_tags.json").read_text(encoding="utf-8"))
    assert {item["path"] for item in metadata["items"]} == {
        "first/same.png",
        "second/same.png",
    }
    assert str(source_dir.resolve()) not in json.dumps(metadata)

    manager.finalize_curation(state, CurationFinalize(target_size=2))

    training_dir = output_dir / "training_dataset_direct_style"
    assert state.curation["status"] == "completed"
    assert len(list(training_dir.glob("*.png"))) == 2
    assert len(list(training_dir.glob("*.txt"))) == 2


def test_pixai_only_request_reuses_prefix_validation():
    with pytest.raises(ValidationError):
        PixAIJobCreate(source_dir="images", lora_prefix="bad prefix")


def test_pixai_only_preview_rejects_source_outside_selected_folder(tmp_path):
    source_dir = tmp_path / "source"
    output_dir = tmp_path / "output"
    source_dir.mkdir()
    output_dir.mkdir()
    outside_image = tmp_path / "outside.png"
    Image.new("RGB", (16, 16), "red").save(outside_image)
    state = JobState(
        "pixai-preview",
        str(source_dir),
        str(output_dir),
        workflow="pixai_only",
    )
    state.manifest = [
        {
            "source": str(outside_image),
            "output": None,
            "cluster_id": -1,
            "candidate_role": "standalone",
            "locate_attempt": 0,
            "status": "passed",
            "reason": None,
        }
    ]
    manager = JobManager(Settings())
    try:
        with pytest.raises(PermissionError, match="outside the task input"):
            manager.curation_image_path(state, 0)
    finally:
        manager.executor.shutdown(wait=False, cancel_futures=True)


def test_review_image_serves_only_passed_task_output(monkeypatch, tmp_path):
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    output_image = output_dir / "00001-image.png"
    Image.new("RGB", (32, 32), "green").save(output_image)
    state = JobState("review-job", str(tmp_path), str(output_dir))
    state.manifest = [
        {
            "source": str(tmp_path / "image.png"),
            "output": str(output_image),
            "cluster_id": 1,
            "candidate_role": "medoid",
            "locate_attempt": 1,
            "status": "passed",
            "reason": None,
        }
    ]
    monkeypatch.setattr(main_module, "get_state", lambda job_id: state)

    response = main_module.review_image("review-job", 0)

    assert Path(response.path) == output_image.resolve()


def test_review_image_rejects_path_outside_task_output(monkeypatch, tmp_path):
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    outside_image = tmp_path / "outside.png"
    Image.new("RGB", (32, 32), "red").save(outside_image)
    state = JobState("review-job", str(tmp_path), str(output_dir))
    state.manifest = [
        {
            "source": str(outside_image),
            "output": str(outside_image),
            "cluster_id": 1,
            "candidate_role": "medoid",
            "locate_attempt": 1,
            "status": "passed",
            "reason": None,
        }
    ]
    monkeypatch.setattr(main_module, "get_state", lambda job_id: state)

    with pytest.raises(main_module.HTTPException) as error:
        main_module.review_image("review-job", 0)

    assert error.value.status_code == 403


def test_review_remove_and_restore_updates_file_manifest_and_count(tmp_path):
    output_dir = tmp_path / "filtered"
    output_dir.mkdir()
    output_image = output_dir / "00001-image.png"
    Image.new("RGB", (32, 32), "blue").save(output_image)
    manifest_path = output_dir / "manifest.json"
    state = JobState("review-mutation", str(tmp_path), str(output_dir))
    state.manifest = [
        {
            "source": str(tmp_path / "image.png"),
            "output": str(output_image),
            "cluster_id": 1,
            "candidate_role": "medoid",
            "locate_attempt": 1,
            "status": "passed",
            "reason": None,
        }
    ]
    state.stats = {
        "output_images": 1,
        "manifest_path": str(manifest_path),
    }
    manifest_path.write_text(
        json.dumps({"job_id": state.job_id, "items": state.manifest}),
        encoding="utf-8",
    )
    manager = JobManager(Settings())
    try:
        removed = manager.remove_review_image(state, 0)
        removed_path = Path(state.manifest[0]["review_removed_path"])

        assert removed["output_images"] == 0
        assert not output_image.exists()
        assert removed_path.is_file()
        assert not removed_path.is_relative_to(output_dir)
        assert state.manifest[0]["status"] == "removed_by_review"
        assert json.loads(manifest_path.read_text(encoding="utf-8"))["items"][0]["status"] == "removed_by_review"

        restored = manager.restore_review_image(state, 0)

        assert restored["output_images"] == 1
        assert output_image.is_file()
        assert not removed_path.exists()
        assert state.manifest[0]["status"] == "passed"
        assert state.manifest[0]["output"] == str(output_image.resolve())
        assert json.loads(manifest_path.read_text(encoding="utf-8"))["items"][0]["status"] == "passed"
    finally:
        manager.executor.shutdown(wait=False, cancel_futures=True)


def test_review_remove_rejects_non_passed_item(tmp_path):
    output_dir = tmp_path / "filtered"
    output_dir.mkdir()
    state = JobState("review-rejected", str(tmp_path), str(output_dir))
    state.manifest = [
        {
            "source": str(tmp_path / "image.png"),
            "output": None,
            "cluster_id": 1,
            "candidate_role": "dropped",
            "locate_attempt": 1,
            "status": "not_meet",
            "reason": "watermark_detected",
        }
    ]
    manager = JobManager(Settings())
    try:
        with pytest.raises(ValueError, match="not part of the final dataset"):
            manager.remove_review_image(state, 0)
    finally:
        manager.executor.shutdown(wait=False, cancel_futures=True)


def test_native_folder_picker_returns_selected_directory(monkeypatch, tmp_path):
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return folder_dialog.subprocess.CompletedProcess(command, 0, f"\ufeff{tmp_path}\n", "")

    monkeypatch.setattr(folder_dialog.sys, "platform", "win32")
    monkeypatch.setattr(folder_dialog.subprocess, "run", fake_run)

    selected = folder_dialog.select_folder("source")

    assert selected == tmp_path
    assert "-STA" in captured["command"]
    assert captured["kwargs"]["env"]["AUTO_CAT_FOLDER_DIALOG_TITLE"] == "选择需要筛选的图片文件夹"
    assert captured["kwargs"]["encoding"] == "utf-8"


def test_native_folder_picker_cancel_returns_none(monkeypatch):
    def fake_run(command, **kwargs):
        return folder_dialog.subprocess.CompletedProcess(command, 2, "", "")

    monkeypatch.setattr(folder_dialog.sys, "platform", "win32")
    monkeypatch.setattr(folder_dialog.subprocess, "run", fake_run)

    assert folder_dialog.select_folder("output") is None


def test_native_folder_picker_uses_english_title(monkeypatch, tmp_path):
    captured = {}

    def fake_run(command, **kwargs):
        captured["environment"] = kwargs["env"]
        return folder_dialog.subprocess.CompletedProcess(command, 0, f"{tmp_path}\n", "")

    monkeypatch.setattr(folder_dialog.sys, "platform", "win32")
    monkeypatch.setattr(folder_dialog.subprocess, "run", fake_run)

    assert folder_dialog.select_folder("source", locale="en") == tmp_path
    assert captured["environment"]["AUTO_CAT_FOLDER_DIALOG_TITLE"] == (
        "Select the image folder to process"
    )


def test_native_folder_picker_reports_process_error(monkeypatch):
    def fake_run(command, **kwargs):
        return folder_dialog.subprocess.CompletedProcess(command, 1, "", "dialog unavailable")

    monkeypatch.setattr(folder_dialog.sys, "platform", "win32")
    monkeypatch.setattr(folder_dialog.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="dialog unavailable"):
        folder_dialog.select_folder("source")


def make_record(path: Path, vector: list[float]) -> ImageRecord:
    embedding = np.asarray(vector, dtype=np.float32)
    embedding /= np.linalg.norm(embedding)
    return ImageRecord(path, str(path), 1200, 1200, 1_440_000, embedding=embedding)


def test_scan_dedupes_and_rejects_small_images(tmp_path):
    large = tmp_path / "large.png"
    duplicate = tmp_path / "duplicate.png"
    small = tmp_path / "small.png"
    Image.new("RGB", (1200, 1200), "white").save(large)
    duplicate.write_bytes(large.read_bytes())
    Image.new("RGB", (100, 100), "black").save(small)
    records, stats = scan_images(tmp_path, 1_000_000)
    assert len(records) == 1
    assert stats["duplicates"] == 1
    assert stats["resolution_rejected"] == 1


def test_scan_accepts_720p_when_task_uses_720p_threshold(tmp_path):
    image_path = tmp_path / "720p.png"
    Image.new("RGB", (1280, 720), "navy").save(image_path)

    compatible_records, compatible_stats = scan_images(tmp_path, 1280 * 720)
    strict_records, strict_stats = scan_images(tmp_path, 1_000_000)

    assert len(compatible_records) == 1
    assert compatible_stats["minimum_pixels"] == 921_600
    assert compatible_stats["resolution_rejected"] == 0
    assert strict_records == []
    assert strict_stats["minimum_pixels"] == 1_000_000
    assert strict_stats["resolution_rejected"] == 1


def test_complete_linkage_and_medoid():
    records = [
        make_record(Path("a.jpg"), [1, 0, 0, 0]),
        make_record(Path("b.jpg"), [0.99, 0.1, 0, 0]),
        make_record(Path("c.jpg"), [0, 1, 0, 0]),
    ]
    clusters = complete_linkage_clusters(records, 0.90)
    assert sorted(len(cluster.members) for cluster in clusters) == [1, 2]
    assert all(cluster.medoid is not None for cluster in clusters)


def test_single_image_cluster_has_medoid_but_no_retry_candidate():
    record = make_record(Path("only.jpg"), [1, 0, 0, 0])

    clusters = complete_linkage_clusters([record], 0.90)

    assert len(clusters) == 1
    assert clusters[0].medoid is record
    assert clusters[0].backup_candidates == []


def test_cluster_audit_reports_medoid_and_minimum_pairwise_similarity():
    medoid = make_record(Path("a.jpg"), [1, 0, 0, 0])
    member = make_record(Path("b.jpg"), [0.8, 0.6, 0, 0])
    cluster = Cluster(cluster_id=7, members=[medoid, member], medoid=medoid)
    engine = PipelineEngine(Settings(), lambda *args: None)

    payload = engine._cluster_audit_payload([cluster])

    audit_cluster = payload["clusters"][0]
    assert audit_cluster["minimum_similarity"] == pytest.approx(0.8)
    assert audit_cluster["members"][0]["similarity_to_medoid"] == pytest.approx(1.0)
    assert audit_cluster["members"][1]["similarity_to_medoid"] == pytest.approx(0.8)


def test_save_preprocessed_image_creates_lossless_448_png(tmp_path):
    destination = tmp_path / "prepared.png"
    normalized = np.zeros((3, 448, 448), dtype=np.float32)

    _save_preprocessed_image(
        normalized,
        destination,
        image_mean=[0.5, 0.5, 0.5],
        image_std=[1.0, 1.0, 1.0],
    )

    with Image.open(destination) as prepared:
        assert prepared.size == (448, 448)
        assert prepared.mode == "RGB"
        assert prepared.getpixel((0, 0)) == (128, 128, 128)


def test_real_pixai_embedding_uses_saved_448_input(tmp_path):
    source = tmp_path / "source.png"
    prepared = tmp_path / "prepared.png"
    Image.new("RGB", (1200, 900), "purple").save(source)
    received_path = None

    def fake_get_pixai_tags(path, model_name, fmt):
        nonlocal received_path
        received_path = Path(path)
        assert model_name == "v0.9"
        assert fmt == "embedding"
        with Image.open(path) as image:
            assert image.size == (448, 448)
            assert image.mode == "RGB"
        return np.ones(1024, dtype=np.float32)

    provider = PixAIEmbeddingProvider.__new__(PixAIEmbeddingProvider)
    provider.model_name = "v0.9"
    provider._get_pixai_tags = fake_get_pixai_tags

    vector = provider.embed(source, prepared)

    assert received_path == prepared
    assert prepared.is_file()
    assert vector.shape == (1024,)
    assert np.linalg.norm(vector) == pytest.approx(1.0)


def test_pipeline_can_use_pixai_visual_embedding_experiment(monkeypatch, tmp_path):
    source_dir = tmp_path / "source"
    output_dir = tmp_path / "output"
    source_dir.mkdir()
    Image.new("RGB", (1200, 1200), "purple").save(source_dir / "image.png")
    events = []
    monkeypatch.setattr(
        engine_module,
        "make_pixai_embedding_provider",
        lambda model_name: FakeEmbeddingProvider(),
    )
    engine = PipelineEngine(
        Settings(),
        lambda *args: events.append(args),
        similarity_model="pixai",
    )

    result = engine.run("pixai-embedding", source_dir, output_dir, None)

    assert result.stats["embedding_model"] == "pixai"
    assert result.stats["embedding_dimension"] == 1024
    assert result.stats["prepared_images"] == 1
    assert any(
        event[0] == "embedding"
        and event[1] == "running"
        and event[4].get("similarity_model") == "pixai"
        for event in events
    )


def test_job_create_rejects_unknown_similarity_model():
    with pytest.raises(ValidationError):
        JobCreate(source_dir="images", similarity_model="unknown")


def test_runtime_mode_is_not_exposed_by_api_models_or_health():
    assert "mode" not in JobCreate.model_fields
    assert "mode" not in PixAIJobCreate.model_fields
    health = main_module.health()
    assert "mode" not in health
    assert health["runtime"] == "local_models"


def test_job_create_accepts_task_resolution_threshold_and_rejects_too_small_values():
    request = JobCreate(source_dir="images", minimum_pixels=1280 * 720)

    assert request.minimum_pixels == 921_600
    with pytest.raises(ValidationError):
        JobCreate(source_dir="images", minimum_pixels=10_000)


def test_pipeline_uses_task_resolution_threshold(monkeypatch, tmp_path):
    source_dir = tmp_path / "source"
    output_dir = tmp_path / "output"
    source_dir.mkdir()
    Image.new("RGB", (720, 1280), "teal").save(source_dir / "portrait-720p.png")
    events = []
    monkeypatch.setattr(
        engine_module,
        "make_embedding_provider",
        lambda model_id: FakeEmbeddingProvider(),
    )
    engine = PipelineEngine(
        Settings(),
        lambda *args: events.append(args),
        minimum_pixels=1280 * 720,
    )

    result = engine.run("720p-threshold", source_dir, output_dir, None)

    assert result.stats["minimum_pixels"] == 921_600
    assert result.stats["embedding_candidates"] == 1
    assert any(
        event[0] == "scan"
        and event[1] == "running"
        and event[4]["minimum_resolution_label"] == "720p"
        for event in events
    )


def test_pipeline_temporary_images_are_removed_after_success(monkeypatch):
    engine = PipelineEngine(Settings(), lambda *args: None)
    captured_path = None

    def fake_run_pipeline(job_id, source_dir, output_dir, seed, temporary_dir):
        nonlocal captured_path
        captured_path = temporary_dir
        (temporary_dir / "prepared.png").write_bytes(b"temporary")
        return PipelineResult(stats={}, manifest=[])

    monkeypatch.setattr(engine, "_run_pipeline", fake_run_pipeline)
    engine.run("cleanup-success", Path("."), None, None)

    assert captured_path is not None
    assert not captured_path.exists()


def test_pipeline_temporary_images_are_removed_after_failure(monkeypatch):
    engine = PipelineEngine(Settings(), lambda *args: None)
    captured_path = None

    def fake_run_pipeline(job_id, source_dir, output_dir, seed, temporary_dir):
        nonlocal captured_path
        captured_path = temporary_dir
        (temporary_dir / "prepared.png").write_bytes(b"temporary")
        raise RuntimeError("expected failure")

    monkeypatch.setattr(engine, "_run_pipeline", fake_run_pipeline)
    with pytest.raises(RuntimeError, match="expected failure"):
        engine.run("cleanup-failure", Path("."), None, None)

    assert captured_path is not None
    assert not captured_path.exists()


@pytest.mark.parametrize(
    ("similarity_model", "factory_name"),
    [
        ("dinov3", "make_embedding_provider"),
        ("pixai", "make_pixai_embedding_provider"),
    ],
)
def test_pipeline_reuses_prepared_image_for_locate(
    monkeypatch,
    tmp_path,
    similarity_model,
    factory_name,
):
    source_dir = tmp_path / "source"
    output_dir = tmp_path / "output"
    source_dir.mkdir()
    original = source_dir / "original.png"
    Image.new("RGB", (1200, 1200), "navy").save(original)
    record = ImageRecord(original, "sha", 1200, 1200, 1_440_000)
    provider_closed = False
    locate_provider_closed = False
    locate_path = None
    events = []

    class FakeEmbeddingProvider:
        dimension = 1024

        def embed(self, path, prepared_path=None):
            assert prepared_path is not None
            with Image.open(path) as image:
                image.resize((448, 448), Image.Resampling.LANCZOS).save(prepared_path, format="PNG")
            vector = np.ones(1024, dtype=np.float32)
            return vector / np.linalg.norm(vector)

        def close(self):
            nonlocal provider_closed
            provider_closed = True

    def fake_clusters(records, similarity):
        cluster = Cluster(0, records)
        cluster.medoid = records[0]
        return [cluster]

    class FakeLocateProvider:
        def close(self):
            nonlocal locate_provider_closed
            locate_provider_closed = True

    def fake_inspect(provider, path, attempt, on_step=None):
        nonlocal locate_path
        locate_path = path
        assert path != original
        with Image.open(path) as prepared:
            assert prepared.size == (448, 448)
        if on_step:
            on_step("watermark", "running", [])
            on_step("watermark", "completed", [])
            on_step("comic", "running", [])
            on_step("comic", "completed", [])
        return Inspection([], [], True, None, attempt)

    monkeypatch.setattr(engine_module, "scan_images", lambda source, minimum: ([record], {"files_found": 1}))
    monkeypatch.setattr(
        engine_module,
        factory_name,
        lambda model_id: FakeEmbeddingProvider(),
    )
    monkeypatch.setattr(engine_module, "complete_linkage_clusters", fake_clusters)
    monkeypatch.setattr(engine_module, "make_locate_provider", lambda *args: FakeLocateProvider())
    monkeypatch.setattr(engine_module, "inspect_image", fake_inspect)

    engine = PipelineEngine(
        Settings(),
        lambda *args: events.append(args),
        similarity_model=similarity_model,
    )
    monkeypatch.setattr(
        engine,
        "_select_graph_component",
        lambda clusters: (
            {0},
            {
                "graph_nodes": 1,
                "graph_edges": 0,
                "nodes_with_edges": 0,
                "core_nodes": 1,
                "component_count": 1,
            },
        ),
    )
    result = engine.run("prepared-reuse", source_dir, output_dir, None)

    assert provider_closed
    assert locate_provider_closed
    assert locate_path is not None
    assert not locate_path.exists()
    assert result.stats["output_images"] == 1
    assert result.stats["prepared_images"] == 1
    assert result.stats["temporary_images_cleaned"] is True
    assert Path(result.manifest[0]["source"]) == original
    locate_flow = [event[4]["locate_flow"] for event in events if "locate_flow" in event[4]]
    assert [item["event"] for item in locate_flow] == [
        "pipeline_started",
        "candidate_loaded",
        "check_running",
        "check_completed",
        "check_running",
        "check_completed",
        "candidate_result",
        "cluster_result",
        "pipeline_completed",
    ]
    assert locate_flow[1]["preview"].startswith("data:image/jpeg;base64,")


def test_locate_detection_steps_are_reported():
    steps = []

    inspection = inspect_image(
        FakeLocateAnythingProvider(),
        Path("comic.png"),
        1,
        on_step=lambda *args: steps.append(args),
    )

    assert [step[:2] for step in steps] == [
        ("watermark", "running"),
        ("watermark", "completed"),
        ("comic", "running"),
        ("comic", "completed"),
    ]
    assert len(steps[-1][2]) == 2
    assert not inspection.meets


def test_watermark_detection_skips_comic_request():
    steps = []

    class WatermarkProvider:
        def __init__(self):
            self.calls = 0

        def locate(self, path, prompt):
            self.calls += 1
            return [[0.1, 0.1, 0.4, 0.2]]

    provider = WatermarkProvider()
    inspection = inspect_image(
        provider,
        Path("watermarked.png"),
        1,
        on_step=lambda *args: steps.append(args),
    )

    assert provider.calls == 1
    assert [step[:2] for step in steps] == [
        ("watermark", "running"),
        ("watermark", "completed"),
        ("comic", "skipped"),
    ]
    assert not inspection.meets
    assert inspection.reason == "watermark_detected"
    assert inspection.comic_boxes == []


def test_locate_preview_boxes_are_normalized():
    assert np.allclose(
        PipelineEngine._normalize_boxes([[44.8, 89.6, 224, 448]], 448, 448),
        [[0.1, 0.2, 0.5, 1.0]],
    )
    assert np.allclose(
        PipelineEngine._normalize_boxes([[100, 200, 900, 1000]], 448, 448),
        [[0.1, 0.2, 0.9, 1.0]],
    )


def test_graph_3_core_keeps_dense_component():
    vectors = np.eye(4, dtype=np.float32)
    graph = build_mutual_topk_graph(vectors, top_k=3, min_similarity=-1)
    assert all(type(node) is int for node in graph)
    assert all(type(neighbor) is int for neighbors in graph.values() for neighbor in neighbors)
    core = iterative_k_core(graph, degree=3)
    assert set(core) == {0, 1, 2, 3}
    assert connected_components(core) == [{0, 1, 2, 3}]


def test_graph_selection_reports_intermediate_counts():
    clusters = []
    for cluster_id in range(4):
        record = make_record(Path(f"{cluster_id}.jpg"), [1, 0, 0, 0])
        cluster = Cluster(cluster_id, [record], medoid=record)
        clusters.append(cluster)
    engine = PipelineEngine(Settings(), lambda *args: None)

    selected, audit = engine._select_graph_component(clusters)

    assert selected == {0, 1, 2, 3}
    assert audit == {
        "graph_nodes": 4,
        "graph_edges": 6,
        "nodes_with_edges": 4,
        "core_nodes": 4,
        "component_count": 1,
    }


def test_json_safe_converts_numpy_values_recursively():
    payload = {
        "involved_clusters": [np.int64(1), np.int32(2)],
        "scores": np.asarray([0.5, 0.75], dtype=np.float32),
        "nested": {"count": np.int64(2)},
    }

    converted = _json_safe(payload)

    assert converted["involved_clusters"] == [1, 2]
    assert all(type(value) is int for value in converted["involved_clusters"])
    assert converted["scores"] == [0.5, 0.75]
    assert type(converted["nested"]["count"]) is int


def test_job_event_stream_serializes_numpy_values():
    manager = JobManager(Settings())
    state = JobState("test-job", "source", None)
    try:
        manager._event(
            state,
            "graph",
            "completed",
            "graph complete",
            0.6,
            {
                "involved_clusters": [np.int64(1), np.int64(2)],
                "locate_flow": {"event": "candidate_loaded", "preview": "data:image/jpeg;base64,test"},
            },
        )
        state.status = "completed"

        async def collect_events():
            return [chunk async for chunk in manager.event_stream(state)]

        chunks = asyncio.run(collect_events())
    finally:
        manager.executor.shutdown(wait=False, cancel_futures=True)

    serialized = json.loads(chunks[0].split("data: ", 1)[1])
    assert serialized["data"]["involved_clusters"] == [1, 2]
    assert serialized["data"]["locate_flow"]["event"] == "candidate_loaded"
    assert "locate_flow" not in state.stats


def test_job_event_stream_resumes_after_last_event_id():
    manager = JobManager(Settings())
    state = JobState("resume-job", "source", None)
    try:
        manager._event(state, "scan", "running", "first", 0.1, {})
        manager._event(state, "scan", "completed", "second", 0.2, {})
        state.status = "completed"

        async def collect_events():
            return [chunk async for chunk in manager.event_stream(state, last_event_id=1)]

        chunks = asyncio.run(collect_events())
    finally:
        manager.executor.shutdown(wait=False, cancel_futures=True)

    assert len(chunks) == 1
    assert chunks[0].startswith("id: 2\n")


def test_cluster_audit_registers_sources_but_hides_paths_from_event(tmp_path):
    image_path = tmp_path / "image.png"
    Image.new("RGB", (120, 80), "purple").save(image_path)
    manager = JobManager(Settings())
    state = JobState("audit-job", str(tmp_path), None)
    try:
        manager._event(
            state,
            "clustering",
            "completed",
            "clusters ready",
            0.48,
            {
                "cluster_audit": {
                    "event": "clusters_ready",
                    "clusters": [
                        {
                            "cluster_id": 0,
                            "size": 1,
                            "members": [
                                {
                                    "image_id": "image-id",
                                    "filename": image_path.name,
                                    "source": str(image_path),
                                    "role": "medoid",
                                }
                            ],
                        }
                    ],
                }
            },
        )
    finally:
        manager.executor.shutdown(wait=False, cancel_futures=True)

    member = state.events[0].data["cluster_audit"]["clusters"][0]["members"][0]
    assert "source" not in member
    assert state.audit_images["image-id"] == str(image_path)
    assert manager.audit_image_path(state, "image-id") == image_path.resolve()
    assert "cluster_audit" not in state.stats


def test_audit_thumbnail_is_tiny_jpeg(monkeypatch, tmp_path):
    image_path = tmp_path / "wide.png"
    Image.new("RGB", (1200, 600), "orange").save(image_path)
    state = JobState("audit-thumbnail", str(tmp_path), None)
    state.audit_images["image-id"] = str(image_path)
    monkeypatch.setattr(main_module, "get_state", lambda job_id: state)

    response = main_module.audit_thumbnail("audit-thumbnail", "image-id")

    assert response.media_type == "image/jpeg"
    with Image.open(BytesIO(response.body)) as thumbnail:
        assert thumbnail.width <= 96
        assert thumbnail.height <= 96


def test_locate_rules():
    provider = FakeLocateAnythingProvider()
    assert inspect_image(provider, Path("clean.jpg"), 1).meets
    watermark = inspect_image(provider, Path("watermark.jpg"), 1)
    assert not watermark.meets and watermark.reason == "watermark_detected"
    collage = inspect_image(provider, Path("collage.jpg"), 1)
    assert not collage.meets and collage.reason == "comic_or_collage_detected"


def test_locate_official_box_token_parser():
    payload = {"choices": [{"message": {"content": "<box><10><20><300><400></box>"}}]}
    assert _extract_boxes(payload, 1000, 500) == [[10.0, 10.0, 300.0, 200.0]]


def test_locate_http_provider_uses_bounded_max_tokens(monkeypatch, tmp_path):
    image_path = tmp_path / "image.png"
    Image.new("RGB", (100, 100), "white").save(image_path)
    captured = {}

    def fake_post(url, json):
        captured.update({"url": url, "json": json})
        request = httpx.Request("POST", url)
        payload = {"choices": [{"message": {"content": "<box>None</box>"}}]}
        return httpx.Response(200, json=payload, request=request)

    provider = LocateAnythingHttpProvider("http://127.0.0.1:9000/v1/chat/completions", "model", 180, 1024)
    monkeypatch.setattr(provider.client, "post", fake_post)

    try:
        assert provider.locate(image_path, "prompt") == []
        assert captured["json"]["max_tokens"] == 1024
    finally:
        provider.close()


def test_locate_http_provider_preserves_error_detail(monkeypatch, tmp_path):
    image_path = tmp_path / "image.png"
    Image.new("RGB", (100, 100), "white").save(image_path)

    def fake_post(url, json):
        request = httpx.Request("POST", url)
        detail = {"detail": {"code": "cuda_out_of_memory", "message": "CUDA cache cleared"}}
        return httpx.Response(503, json=detail, request=request)

    provider = LocateAnythingHttpProvider("http://127.0.0.1:9000/v1/chat/completions", "model")
    monkeypatch.setattr(provider.client, "post", fake_post)

    try:
        with pytest.raises(RuntimeError, match="cuda_out_of_memory"):
            provider.locate(image_path, "prompt")
    finally:
        provider.close()
