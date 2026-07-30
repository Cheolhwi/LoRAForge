from __future__ import annotations

import hashlib
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from .caption_rules import (
    DEFAULT_CAPTION_DENYLIST as RULE_ENGINE_DEFAULT_DENYLIST,
)
from .caption_rules import build_caption_result

DEFAULT_CAPTION_DENYLIST = {
    "artist_name",
    "artist_signature",
    "bar_censor",
    "blur_censor",
    "censor_bar",
    "censored",
    "commission",
    "convenient_censoring",
    "copyright_name",
    "fanbox_username",
    "light_censor",
    "mosaic_censoring",
    "patreon_logo",
    "patreon_username",
    "sample_watermark",
    "signature",
    "text_focus",
    "twitter_username",
    "uncensored",
    "watermark",
    "web_address",
}
DEFAULT_CAPTION_DENYLIST = RULE_ENGINE_DEFAULT_DENYLIST

PEOPLE_COUNT_TAGS = {
    "solo",
    "duo",
    "couple",
    "group",
    "multiple_boys",
    "multiple_girls",
    "multiple_others",
    *{f"{count}{kind}" for count in range(1, 10) for kind in ("boy", "boys", "girl", "girls")},
    *{f"{count}others" for count in range(1, 10)},
}
FRAMING_TAGS = {"full_body", "cowboy_shot", "upper_body", "close-up", "close_up"}
OUTDOOR_TAGS = {"outdoors"}
INDOOR_TAGS = {
    "indoors",
    "bedroom",
    "classroom",
    "office",
    "kitchen",
    "bathroom",
    "living_room",
}

CAPTION_CATEGORY_ORDER = (
    "action_composition",
    "interaction_concept",
    "key_appearance",
    "accessory_setting",
    "body_state",
    "expression_state",
    "background",
)
CAPTION_CATEGORY_LIMITS = {
    "action_composition": 6,
    "interaction_concept": 4,
    "key_appearance": 8,
    "accessory_setting": 5,
    "body_state": 4,
    "expression_state": 5,
    "background": 5,
    "other": 4,
}
ACTION_COMPOSITION_TAGS = {
    "back_to_viewer",
    "depth_of_field",
    "dynamic_angle",
    "dynamic_pose",
    "facing_viewer",
    "foreshortening",
    "from_above",
    "from_behind",
    "from_below",
    "from_side",
    "looking_at_viewer",
    "looking_away",
    "looking_back",
    "looking_down",
    "looking_up",
    "motion_blur",
    "over_shoulder",
    "pointing",
    "pov",
    "profile",
    "reaching",
}
INTERACTION_CONCEPT_TAGS = {
    "arm_around_waist",
    "arms_around_neck",
    "couple",
    "feeding",
    "group_hug",
    "handholding",
    "headpat",
    "holding_hands",
    "hug",
    "hugging",
    "kiss",
    "kissing",
    "lap_pillow",
    "princess_carry",
    "romantic",
    "solo_focus",
    "yuri",
}
BODY_STATE_TAGS = {
    "arched_back",
    "arms_up",
    "bent_over",
    "bottomless",
    "crouching",
    "crossed_legs",
    "hands_up",
    "kneeling",
    "legs_together",
    "lying",
    "lying_on_back",
    "lying_on_side",
    "naked",
    "nude",
    "on_back",
    "on_side",
    "pregnant",
    "sitting",
    "spread_legs",
    "squatting",
    "standing",
    "sweat",
    "sweaty",
    "topless",
    "wet",
}
EXPRESSION_STATE_TAGS = {
    "angry",
    "blush",
    "closed_eyes",
    "closed_mouth",
    "clenched_teeth",
    "crying",
    "embarrassed",
    "expressionless",
    "frown",
    "grin",
    "happy",
    "open_mouth",
    "parted_lips",
    "sad",
    "scared",
    "seductive_smile",
    "sleepy",
    "smile",
    "surprised",
    "tears",
    "tired",
    "tongue_out",
    "wink",
}
BACKGROUND_TAGS = {
    "bathroom",
    "beach",
    "bedroom",
    "blue_sky",
    "city",
    "classroom",
    "clouds",
    "day",
    "forest",
    "indoors",
    "kitchen",
    "landscape",
    "living_room",
    "night",
    "office",
    "outdoors",
    "room",
    "scenery",
    "simple_background",
    "sky",
    "street",
    "sunset",
}
APPEARANCE_TOKENS = {
    "ass",
    "bangs",
    "body",
    "boy",
    "breasts",
    "clothes",
    "dress",
    "ears",
    "eye",
    "eyes",
    "face",
    "girl",
    "hair",
    "horns",
    "jacket",
    "pants",
    "shirt",
    "shorts",
    "skin",
    "skirt",
    "sleeves",
    "stockings",
    "suit",
    "tail",
    "thighs",
    "uniform",
}
ACCESSORY_SETTING_TOKENS = {
    "accessory",
    "bag",
    "bow",
    "bracelet",
    "camera",
    "cap",
    "choker",
    "collar",
    "earrings",
    "glasses",
    "goggles",
    "halo",
    "hat",
    "hairpin",
    "jewelry",
    "necklace",
    "ornament",
    "phone",
    "piercing",
    "ribbon",
    "ring",
    "sword",
    "tattoo",
    "umbrella",
    "weapon",
    "wings",
}
ACCESSORY_SETTING_TAGS = {
    "armor",
    "bikini",
    "bride",
    "cosplay",
    "gothic_lolita",
    "idol",
    "kimono",
    "lingerie",
    "maid",
    "magical_girl",
    "military_uniform",
    "nurse",
    "office_lady",
    "princess",
    "schoolgirl",
    "swimsuit",
    "teacher",
    "underwear",
    "warrior",
    "witch",
    "yukata",
}
CONCEPT_TOKENS = {
    "concept",
    "cyberpunk",
    "fantasy",
    "horror",
    "romance",
    "romantic",
    "sci-fi",
    "theme",
}


def _caption_category(tag: str) -> str:
    normalized = tag.casefold().replace(" ", "_")
    tokens = set(re.split(r"[_-]+", normalized))
    if (
        normalized in INTERACTION_CONCEPT_TAGS
        or normalized.startswith(("hand_on_", "breast_grab", "face_to_face"))
        or tokens & CONCEPT_TOKENS
    ):
        return "interaction_concept"
    if normalized in ACTION_COMPOSITION_TAGS or tokens & {
        "dancing",
        "fighting",
        "flying",
        "grabbing",
        "holding",
        "jumping",
        "pulling",
        "pushing",
        "running",
        "walking",
    }:
        return "action_composition"
    if normalized in EXPRESSION_STATE_TAGS or tokens & {
        "blush",
        "crying",
        "expression",
        "laughing",
        "smile",
        "tears",
    }:
        return "expression_state"
    if normalized in BODY_STATE_TAGS:
        return "body_state"
    if normalized in ACCESSORY_SETTING_TAGS or tokens & ACCESSORY_SETTING_TOKENS:
        return "accessory_setting"
    if tokens & APPEARANCE_TOKENS:
        return "key_appearance"
    if normalized in BACKGROUND_TAGS or tokens & {
        "background",
        "building",
        "garden",
        "mountain",
        "nature",
        "ocean",
        "park",
        "river",
        "school",
        "scenery",
        "water",
    }:
        return "background"
    return "other"


class MockPixAITagger:
    model_id = "pixai-labs/pixai-tagger-v0.9 (mock)"

    def tag(self, image_path: Path) -> dict[str, float]:
        seed = int(hashlib.sha256(str(image_path).encode("utf-8")).hexdigest()[:8], 16)
        people_variants = [
            {"1girl": 0.96, "solo": 0.93},
            {"1boy": 0.92, "solo": 0.89},
            {"2girls": 0.88, "duo": 0.78},
            {"3girls": 0.84, "group": 0.74},
        ]
        framing_variants = [
            {"full_body": 0.86},
            {"cowboy_shot": 0.81},
            {"upper_body": 0.83},
            {"close-up": 0.78},
        ]
        setting_variants = [
            {"outdoors": 0.88, "day": 0.76, "blue_sky": 0.65},
            {"indoors": 0.82, "room": 0.71},
            {"simple_background": 0.75},
        ]
        tags = {
            "looking_at_viewer": 0.82,
            "long_hair": 0.76,
            "standing": 0.68,
            "smile": 0.61,
            "white_shirt": 0.57,
        }
        tags.update(people_variants[seed % len(people_variants)])
        tags.update(framing_variants[(seed // 3) % len(framing_variants)])
        tags.update(setting_variants[(seed // 7) % len(setting_variants)])
        return dict(sorted(tags.items(), key=lambda item: (-item[1], item[0])))

    def close(self) -> None:
        return None


class RealPixAITagger:
    def __init__(self, model_name: str, model_id: str, storage_threshold: float):
        try:
            import onnxruntime
            import torch
            from imgutils.tagging import get_pixai_tags
        except ImportError as exc:
            raise RuntimeError(
                "PixAI dependencies are missing. Run start_services.bat to install model support."
            ) from exc
        if torch.cuda.is_available() and hasattr(onnxruntime, "preload_dlls"):
            onnxruntime.preload_dlls()
        self._get_pixai_tags = get_pixai_tags
        self.model_name = model_name
        self.model_id = model_id
        self.storage_threshold = storage_threshold

    def tag(self, image_path: Path) -> dict[str, float]:
        result = self._get_pixai_tags(
            image_path,
            model_name=self.model_name,
            thresholds={"general": self.storage_threshold, "character": 1.1},
            fmt="general",
        )
        if not isinstance(result, dict):
            raise TypeError(f"PixAI returned an unexpected general-tag payload: {type(result)!r}")
        return dict(
            sorted(
                ((str(tag), float(score)) for tag, score in result.items()),
                key=lambda item: (-item[1], item[0]),
            )
        )

    def close(self) -> None:
        return None


def make_pixai_tagger(
    mode: str,
    model_name: str,
    model_id: str,
    storage_threshold: float,
):
    if mode == "mock":
        return MockPixAITagger()
    return RealPixAITagger(model_name, model_id, storage_threshold)


def _best_tag(tags: dict[str, float], names: set[str]) -> tuple[str | None, float]:
    candidates = ((name, float(tags.get(name, 0.0))) for name in names)
    return max(candidates, key=lambda item: (item[1], item[0]), default=(None, 0.0))


def _status(confidence: float, known: bool = True) -> str:
    if not known:
        return "unknown"
    if confidence >= 0.65:
        return "high"
    if confidence >= 0.40:
        return "medium"
    return "low"


def derive_selection_features(
    general_tags: dict[str, float],
    decision_threshold: float = 0.35,
) -> dict[str, dict[str, Any]]:
    tags = {str(tag): float(score) for tag, score in general_tags.items()}

    one_source, one_score = _best_tag(tags, {"1girl", "1boy", "1other", "solo"})
    two_source, two_score = _best_tag(tags, {"2girls", "2boys", "2others", "duo", "couple"})
    mixed_score = min(tags.get("1girl", 0.0), tags.get("1boy", 0.0))
    if mixed_score > two_score:
        two_source, two_score = "1girl+1boy", mixed_score
    three_source, three_score = _best_tag(
        tags,
        {
            "group",
            "multiple_girls",
            "multiple_boys",
            "multiple_others",
            *{
                tag
                for tag in tags
                if re.fullmatch(r"(?:[3-9]|\d{2,})(?:girls|boys|others)", tag)
            },
        },
    )
    people_candidates = [
        ("3_plus", three_source, three_score),
        (2, two_source, two_score),
        (1, one_source, one_score),
    ]
    people_value, people_source, people_confidence = max(
        people_candidates,
        key=lambda item: item[2],
    )
    if people_confidence < decision_threshold:
        people_value, people_source = "unknown", None

    framing_candidates = [
        ("full_body", "full_body", tags.get("full_body", 0.0)),
        (
            "half_body",
            "cowboy_shot"
            if tags.get("cowboy_shot", 0.0) >= tags.get("upper_body", 0.0)
            else "upper_body",
            max(tags.get("cowboy_shot", 0.0), tags.get("upper_body", 0.0)),
        ),
        (
            "headshot",
            "close-up"
            if tags.get("close-up", 0.0) >= tags.get("close_up", 0.0)
            else "close_up",
            max(tags.get("close-up", 0.0), tags.get("close_up", 0.0)),
        ),
    ]
    framing_value, framing_source, framing_confidence = max(
        framing_candidates,
        key=lambda item: item[2],
    )
    if framing_confidence < decision_threshold:
        framing_value, framing_source = "unknown", None

    outdoor_source, outdoor_score = _best_tag(tags, OUTDOOR_TAGS)
    indoor_source, indoor_score = _best_tag(tags, INDOOR_TAGS)
    outdoors_value: bool | None
    outdoors_source: str | None
    outdoors_confidence = max(outdoor_score, indoor_score)
    if outdoor_score >= decision_threshold and outdoor_score >= indoor_score + 0.05:
        outdoors_value, outdoors_source = True, outdoor_source
        outdoors_confidence = outdoor_score
    elif indoor_score >= decision_threshold and indoor_score >= outdoor_score + 0.05:
        outdoors_value, outdoors_source = False, indoor_source
        outdoors_confidence = indoor_score
    else:
        outdoors_value, outdoors_source = None, None

    return {
        "people_count": {
            "value": people_value,
            "source_tag": people_source,
            "confidence": people_confidence,
            "status": _status(people_confidence, people_value != "unknown"),
        },
        "framing": {
            "value": framing_value,
            "source_tag": framing_source,
            "confidence": framing_confidence,
            "status": _status(framing_confidence, framing_value != "unknown"),
        },
        "outdoors": {
            "value": outdoors_value,
            "source_tag": outdoors_source,
            "confidence": outdoors_confidence,
            "status": _status(outdoors_confidence, outdoors_value is not None),
        },
    }


def summarize_distribution(items: list[dict[str, Any]], selected_only: bool = False) -> dict[str, Any]:
    selected_items = [
        item for item in items if not selected_only or item.get("selection", {}).get("selected")
    ]
    distribution = {
        "people_count": {"1": 0, "2": 0, "3_plus": 0, "unknown": 0},
        "framing": {"full_body": 0, "half_body": 0, "headshot": 0, "unknown": 0},
        "outdoors": {"true": 0, "false": 0, "unknown": 0},
    }
    for item in selected_items:
        features = item["selection_features"]
        people = str(features["people_count"]["value"])
        framing = str(features["framing"]["value"])
        outdoors = features["outdoors"]["value"]
        outdoors_key = "unknown" if outdoors is None else str(bool(outdoors)).lower()
        distribution["people_count"][people] += 1
        distribution["framing"][framing] += 1
        distribution["outdoors"][outdoors_key] += 1
    return {"total": len(selected_items), **distribution}


def _normalized_targets(values: dict[str, float]) -> dict[str, float]:
    cleaned = {str(key): max(0.0, float(value)) for key, value in values.items()}
    total = sum(cleaned.values())
    if total <= 0:
        raise ValueError("target distribution must contain at least one positive value")
    return {key: value / total for key, value in cleaned.items()}


def select_dataset(
    items: list[dict[str, Any]],
    target_size: int,
    people_target: dict[str, float],
    framing_target: dict[str, float],
    outdoors_target: dict[str, float],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    selected_items = deepcopy(items)
    limit = min(max(int(target_size), 0), len(selected_items))
    targets = {
        "people_count": _normalized_targets(people_target),
        "framing": _normalized_targets(framing_target),
        "outdoors": _normalized_targets(outdoors_target),
    }
    weights = {"people_count": 1.0, "framing": 1.0, "outdoors": 0.5}
    counts = {
        dimension: {key: 0 for key in dimension_targets}
        for dimension, dimension_targets in targets.items()
    }
    remaining = list(range(len(selected_items)))
    chosen: list[int] = []

    def feature_key(item: dict[str, Any], dimension: str) -> str | None:
        value = item["selection_features"][dimension]["value"]
        if value is None or value == "unknown":
            return None
        if dimension == "outdoors":
            return str(bool(value)).lower()
        return str(value)

    for rank in range(1, limit + 1):
        scored: list[tuple[float, float, str, int]] = []
        for index in remaining:
            item = selected_items[index]
            score = 0.0
            confidences = []
            for dimension, dimension_targets in targets.items():
                key = feature_key(item, dimension)
                if key in dimension_targets:
                    desired = dimension_targets[key] * limit
                    deficit = max(desired - counts[dimension][key], 0.0) / max(desired, 1.0)
                    score += weights[dimension] * deficit
                    confidences.append(
                        float(item["selection_features"][dimension].get("confidence", 0.0))
                    )
            confidence = sum(confidences) / len(confidences) if confidences else 0.0
            score += 0.1 * confidence
            scored.append((score, confidence, str(item["image_id"]), index))
        _, _, _, chosen_index = max(scored, key=lambda row: (row[0], row[1], row[2]))
        remaining.remove(chosen_index)
        chosen.append(chosen_index)
        chosen_item = selected_items[chosen_index]
        chosen_item["selection"] = {"selected": True, "rank": rank}
        for dimension, dimension_targets in targets.items():
            key = feature_key(chosen_item, dimension)
            if key in dimension_targets:
                counts[dimension][key] += 1

    chosen_set = set(chosen)
    for index, item in enumerate(selected_items):
        if index not in chosen_set:
            item["selection"] = {"selected": False}

    report = {
        "target_size": target_size,
        "selected_size": limit,
        "targets": targets,
        "distribution": summarize_distribution(selected_items, selected_only=True),
    }
    return selected_items, report


def build_caption(
    item: dict[str, Any],
    trigger_prefix: str,
    threshold: float,
    denylist: set[str] | None = None,
    max_tags: int = 48,
) -> str:
    return build_caption_result(
        item,
        trigger_prefix,
        threshold,
        denylist,
        soft_max_tags=max_tags,
        hard_max_tags=max(64, max_tags),
    ).caption
