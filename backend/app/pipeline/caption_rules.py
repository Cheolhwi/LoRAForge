from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from .pixai_parent_rules import (
    canonicalize_parent_tag,
    load_pixai_parent_rules,
    normalize_parent_tag,
    redundant_parent_removals,
)

SOURCE_METADATA_DENYLIST = {
    "artist_name",
    "artist_signature",
    "commission",
    "copyright_name",
    "fanbox_username",
    "logo",
    "patreon_logo",
    "patreon_username",
    "pixiv_id",
    "pixiv_username",
    "qr_code",
    "sample_watermark",
    "signature",
    "text_focus",
    "twitter_username",
    "username",
    "watermark",
    "web_address",
}
CENSOR_DENYLIST = {
    "bar_censor",
    "blur_censor",
    "censor_bar",
    "censored",
    "convenient_censoring",
    "light_censor",
    "mosaic_censoring",
    "uncensored",
}
BOORU_METADATA_DENYLIST = {
    "artist_request",
    "character_request",
    "commentary",
    "commentary_request",
    "copyright_request",
    "source_request",
    "tagme",
    "translated",
    "translation_request",
}
QUALITY_DENYLIST = {
    "bad_anatomy",
    "bad_hands",
    "blurry",
    "compression_artifacts",
    "error",
    "jpeg_artifacts",
    "lowres",
    "scan_artifacts",
}
OPTIONAL_TEXT_DENYLIST = {
    "chinese_text",
    "english_text",
    "japanese_text",
    "korean_text",
    "speech_bubble",
    "subtitle",
    "text",
}
DEFAULT_CAPTION_DENYLIST = (
    SOURCE_METADATA_DENYLIST
    | CENSOR_DENYLIST
    | BOORU_METADATA_DENYLIST
    | QUALITY_DENYLIST
)

PEOPLE_TAGS = {
    "couple",
    "duo",
    "group",
    "multiple_boys",
    "multiple_girls",
    "multiple_others",
    "solo",
}
FRAMING_TAGS = {
    "close-up",
    "close_up",
    "cowboy_shot",
    "full_body",
    "upper_body",
}
LOCATION_ROOT_TAGS = {"indoors", "outdoors"}

EYE_COLOR_TAGS = {
    "aqua_eyes",
    "black_eyes",
    "blue_eyes",
    "brown_eyes",
    "green_eyes",
    "grey_eyes",
    "orange_eyes",
    "pink_eyes",
    "purple_eyes",
    "red_eyes",
    "white_eyes",
    "yellow_eyes",
}
EYE_COLOR_EXCEPTIONS = {"heterochromia", "multicolored_eyes"}
HAIR_COLOR_TAGS = {
    "aqua_hair",
    "black_hair",
    "blonde_hair",
    "blue_hair",
    "brown_hair",
    "green_hair",
    "grey_hair",
    "orange_hair",
    "pink_hair",
    "purple_hair",
    "red_hair",
    "white_hair",
}
HAIR_COLOR_EXCEPTIONS = {
    "colored_inner_hair",
    "gradient_hair",
    "multicolored_hair",
    "split-color_hair",
    "streaked_hair",
    "two-tone_hair",
}
HAIR_LENGTH_TAGS = {
    "bald",
    "long_hair",
    "medium_hair",
    "short_hair",
    "very_long_hair",
    "very_short_hair",
}
EYE_STATE_TAGS = {"closed_eyes"}
MOUTH_STATE_TAGS = {"closed_mouth", "open_mouth"}
BREAST_SIZE_TAGS = {
    "flat_chest",
    "huge_breasts",
    "large_breasts",
    "medium_breasts",
    "small_breasts",
}
BREAST_SIZE_EXCEPTIONS = {"alternate_breast_size"}
AGE_APPEARANCE_TAGS = {"adult", "child", "mature_female", "teenage"}

WORN_FOOTWEAR_TAGS = {
    "ankle_socks",
    "boots",
    "high_heels",
    "kneehighs",
    "loafers",
    "mary_janes",
    "pantyhose",
    "sandals",
    "shoes",
    "slippers",
    "sneakers",
    "socks",
    "thighhighs",
}
FOOTWEAR_EXCEPTIONS = {
    "barefoot_sandals",
    "shoe_removal",
    "shoes_removed",
    "single_shoe",
    "single_sock",
    "sock_removal",
    "socks_removed",
    "toeless_socks",
}
BACKGROUND_COLOR_TAGS = {
    "black_background",
    "blue_background",
    "green_background",
    "grey_background",
    "orange_background",
    "pink_background",
    "purple_background",
    "red_background",
    "white_background",
    "yellow_background",
}
BACKGROUND_COLOR_EXCEPTIONS = {
    "gradient_background",
    "multicolored_background",
    "split_background",
    "two-tone_background",
}
TIME_TAGS = {"day", "night"}
TIME_EXCEPTIONS = {"sunrise", "sunset", "twilight"}
CAMERA_ANGLE_TAGS = {"from_above", "from_below"}
MULTI_VIEW_EXCEPTIONS = {
    "image_sample",
    "multiple_views",
    "reference_sheet",
    "split_screen",
}

SOLO_CONFLICT_PAIRS = {
    frozenset({"closed_mouth", "open_mouth"}),
    frozenset({"completely_nude", "fully_clothed"}),
    frozenset({"closed_eyes", "looking_at_viewer"}),
    frozenset({"expressionless", "grin"}),
    frozenset({"expressionless", "laughing"}),
    frozenset({"expressionless", "smile"}),
    frozenset({"facing_away", "facing_viewer"}),
    frozenset({"kneeling", "standing"}),
    frozenset({"looking_at_viewer", "looking_away"}),
    frozenset({"lying", "sitting"}),
    frozenset({"lying", "standing"}),
    frozenset({"sitting", "standing"}),
    frozenset({"smile", "frown"}),
    frozenset({"squatting", "standing"}),
}
GLOBAL_CONFLICT_PAIRS = {
    frozenset({"detailed_background", "simple_background"}),
    frozenset({"scenery", "white_background"}),
}

HIGH_RISK_TAGS = {
    "alternate_breast_size",
    "humiliation",
    "masochism",
    "mind_control",
    "sadism",
}
ABSTRACT_SUPPORT_RULES = {
    "humiliation": {
        "blush",
        "crying",
        "embarrassed",
        "public",
    },
    "masochism": {
        "bdsm",
        "bondage",
        "crying",
        "pain",
        "spanking",
        "whip",
    },
    "mind_control": {
        "empty_eyes",
        "hypnosis",
        "hypnotic_eyes",
        "spiral_eyes",
    },
    "pet_play": {
        "animal_collar",
        "cat_girl",
        "collar",
        "dog_girl",
        "leash",
        "paw_pose",
        "viewer_holding_leash",
    },
    "sadism": {
        "bdsm",
        "pain",
        "torture",
        "whip",
    },
}
SUPPORT_MINIMUMS = {"pet_play": 2}

CAPTION_CATEGORY_ORDER = (
    "action_composition",
    "interaction_concept",
    "key_appearance",
    "accessory_setting",
    "body_state",
    "expression_state",
    "background",
    "other",
)
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
    "closed_mouth",
    "clenched_teeth",
    "crying",
    "embarrassed",
    "expressionless",
    "frown",
    "grin",
    "happy",
    "laughing",
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


@dataclass(frozen=True)
class CaptionRuleData:
    aliases: dict[str, str]
    removable_parents: dict[str, set[str]]
    parent_rule_source: str = ""
    direct_parent_rule_count: int = 0
    blocked_parent_rule_count: int = 0
    parent_rule_count: int = 0
    general_tag_count: int = 0


@dataclass
class CaptionResult:
    caption: str
    tags: list[str]
    audit_log: list[dict[str, Any]]


def normalize_tag(tag: object) -> str:
    return normalize_parent_tag(tag)


@lru_cache(maxsize=8)
def load_caption_rule_data(
    parent_rules_path: str = "",
    strict: bool = False,
) -> CaptionRuleData:
    rules = load_pixai_parent_rules(parent_rules_path, strict)
    return CaptionRuleData(
        aliases=dict(rules.aliases),
        removable_parents={
            child: set(parents)
            for child, parents in rules.child_to_parents.items()
        },
        parent_rule_source=rules.source,
        direct_parent_rule_count=rules.direct_relation_count,
        blocked_parent_rule_count=rules.blocked_relation_count,
        parent_rule_count=rules.parent_relation_count,
        general_tag_count=rules.general_tag_count,
    )


def _canonical_tag(tag: str, aliases: dict[str, str]) -> str:
    return canonicalize_parent_tag(tag, aliases)


def _record_removal(
    audit: list[dict[str, Any]],
    tag: str,
    score: float,
    reason: str,
    **details: Any,
) -> None:
    entry = {"tag": tag, "score": float(score), "reason": reason}
    entry.update(details)
    audit.append(entry)


def _remove_tags(
    tags: dict[str, float],
    names: set[str] | list[str] | tuple[str, ...],
    audit: list[dict[str, Any]],
    reason: str,
    **details: Any,
) -> None:
    for name in sorted(names):
        if name in tags:
            score = tags.pop(name)
            _record_removal(audit, name, score, reason, **details)


def _normalize_tags(
    general_tags: dict[str, float],
    audit: list[dict[str, Any]],
) -> dict[str, float]:
    normalized: dict[str, float] = {}
    for raw_tag, raw_score in general_tags.items():
        tag = normalize_tag(raw_tag)
        if not tag:
            continue
        score = float(raw_score)
        if tag not in normalized:
            normalized[tag] = score
        elif score > normalized[tag]:
            _record_removal(
                audit,
                tag,
                normalized[tag],
                "normalized_duplicate",
                winner=tag,
                winner_score=score,
            )
            normalized[tag] = score
        else:
            _record_removal(
                audit,
                tag,
                score,
                "normalized_duplicate",
                winner=tag,
                winner_score=normalized[tag],
            )
    return normalized


def _filter_denylist(
    tags: dict[str, float],
    denied: set[str],
    aliases: dict[str, str],
    audit: list[dict[str, Any]],
) -> None:
    canonical_denied = {_canonical_tag(tag, aliases) for tag in denied}
    for tag, score in list(tags.items()):
        canonical = _canonical_tag(tag, aliases)
        if canonical not in canonical_denied:
            continue
        tags.pop(tag)
        details = {"canonical_tag": canonical} if canonical != tag else {}
        _record_removal(audit, tag, score, "denylisted", **details)


def _apply_aliases(
    tags: dict[str, float],
    aliases: dict[str, str],
    protected: list[str],
    audit: list[dict[str, Any]],
) -> tuple[dict[str, float], list[str]]:
    canonicalized: dict[str, float] = {}
    winner_sources: dict[str, str] = {}
    for tag, score in tags.items():
        canonical = _canonical_tag(tag, aliases)
        if canonical not in canonicalized:
            canonicalized[canonical] = score
            winner_sources[canonical] = tag
            continue

        winner_score = canonicalized[canonical]
        winner_source = winner_sources[canonical]
        if score > winner_score:
            _record_removal(
                audit,
                winner_source,
                winner_score,
                "alias_duplicate",
                canonical_tag=canonical,
                winner=canonical,
                winner_source=tag,
                winner_score=score,
            )
            canonicalized[canonical] = score
            winner_sources[canonical] = tag
        else:
            _record_removal(
                audit,
                tag,
                score,
                "alias_duplicate",
                canonical_tag=canonical,
                winner=canonical,
                winner_source=winner_source,
                winner_score=winner_score,
            )

    canonical_protected: list[str] = []
    for tag in protected:
        canonical = _canonical_tag(tag, aliases)
        if canonical in canonicalized and canonical not in canonical_protected:
            canonical_protected.append(canonical)
    return canonicalized, canonical_protected


def _is_people_tag(tag: str) -> bool:
    return tag in PEOPLE_TAGS or bool(
        re.fullmatch(r"\d+(?:girls?|boys?|others?)", tag)
    )


def _group_threshold(tag: str, general_threshold: float, abstract_threshold: float) -> float:
    if tag in EYE_COLOR_TAGS | HAIR_COLOR_TAGS | BACKGROUND_COLOR_TAGS:
        return max(general_threshold, 0.55)
    if tag in BREAST_SIZE_TAGS:
        return max(general_threshold, 0.60)
    if tag in HIGH_RISK_TAGS | AGE_APPEARANCE_TAGS:
        return max(general_threshold, abstract_threshold)
    return general_threshold


def _filter_thresholds(
    tags: dict[str, float],
    general_threshold: float,
    abstract_threshold: float,
    aliases: dict[str, str],
    audit: list[dict[str, Any]],
) -> None:
    for tag, score in list(tags.items()):
        canonical = _canonical_tag(tag, aliases)
        required = _group_threshold(canonical, general_threshold, abstract_threshold)
        if score < required:
            tags.pop(tag)
            details = {"canonical_tag": canonical} if canonical != tag else {}
            _record_removal(
                audit,
                tag,
                score,
                "below_threshold",
                required_threshold=required,
                **details,
            )


def _inject(
    tags: dict[str, float],
    protected: list[str],
    tag: str | None,
    score: float,
) -> None:
    if not tag:
        return
    normalized = normalize_tag(tag)
    if not normalized:
        return
    tags[normalized] = max(float(score), tags.get(normalized, 0.0))
    if normalized not in protected:
        protected.append(normalized)


def _apply_selection_overrides(
    tags: dict[str, float],
    features: dict[str, Any],
    aliases: dict[str, str],
    audit: list[dict[str, Any]],
) -> list[str]:
    original_scores = dict(tags)
    people_names = {
        tag for tag in tags if _is_people_tag(_canonical_tag(tag, aliases))
    }
    framing_names = {
        tag
        for tag in tags
        if _canonical_tag(tag, aliases) in FRAMING_TAGS
    }
    location_names = {
        tag
        for tag in tags
        if _canonical_tag(tag, aliases) in LOCATION_ROOT_TAGS
    }
    _remove_tags(tags, people_names, audit, "selection_override")
    _remove_tags(tags, framing_names, audit, "selection_override")
    _remove_tags(tags, location_names, audit, "selection_override")

    protected: list[str] = []
    people = features["people_count"]
    people_value = people.get("value")
    people_score = float(people.get("confidence", 0.0))
    people_source = normalize_tag(people.get("source_tag") or "")
    if people_value == 1:
        if people_source not in {"1girl", "1boy", "1other"}:
            people_source = max(
                ("1girl", "1boy", "1other"),
                key=lambda name: original_scores.get(name, 0.0),
            )
            if original_scores.get(people_source, 0.0) <= 0:
                people_source = ""
        _inject(tags, protected, people_source, original_scores.get(people_source, people_score))
        _inject(tags, protected, "solo", people_score)
    elif people_value == 2:
        if people_source == "1girl+1boy":
            _inject(tags, protected, "1girl", original_scores.get("1girl", people_score))
            _inject(tags, protected, "1boy", original_scores.get("1boy", people_score))
        elif people_source:
            _inject(tags, protected, people_source, people_score)
    elif people_value == "3_plus" and people_source:
        _inject(tags, protected, people_source, people_score)

    framing = features["framing"]
    if framing.get("value") != "unknown" and framing.get("source_tag"):
        _inject(
            tags,
            protected,
            framing["source_tag"],
            float(framing.get("confidence", 0.0)),
        )

    outdoors = features["outdoors"]
    if outdoors.get("value") is True:
        _inject(tags, protected, "outdoors", float(outdoors.get("confidence", 0.0)))
    elif outdoors.get("value") is False:
        _inject(tags, protected, "indoors", float(outdoors.get("confidence", 0.0)))
    return protected


def _remove_redundant_parents(
    tags: dict[str, float],
    parent_rules: dict[str, set[str]],
    audit: list[dict[str, Any]],
) -> None:
    removals = redundant_parent_removals(tags, parent_rules)
    for parent, child in removals.items():
        score = tags.pop(parent)
        _record_removal(
            audit,
            parent,
            score,
            "redundant_parent",
            child=child,
        )


def _resolve_exclusive(
    tags: dict[str, float],
    group: set[str],
    keep_count: int,
    margin: float,
    audit: list[dict[str, Any]],
) -> None:
    candidates = sorted(
        ((tag, tags[tag]) for tag in group if tag in tags),
        key=lambda item: (-item[1], item[0]),
    )
    if len(candidates) <= keep_count:
        return
    boundary = candidates[keep_count - 1][1] - candidates[keep_count][1]
    if boundary >= margin:
        winners = candidates[:keep_count]
        winner_names = [tag for tag, _ in winners]
        for tag, score in candidates[keep_count:]:
            tags.pop(tag, None)
            _record_removal(
                audit,
                tag,
                score,
                "exclusive_loser",
                winners=winner_names,
                margin=boundary,
            )
    else:
        names = [tag for tag, _ in candidates]
        for tag, score in candidates:
            tags.pop(tag, None)
            _record_removal(
                audit,
                tag,
                score,
                "exclusive_ambiguous",
                group=names,
                margin=boundary,
            )


def _resolve_pair(
    tags: dict[str, float],
    pair: frozenset[str],
    margin: float,
    audit: list[dict[str, Any]],
) -> None:
    if not pair <= set(tags):
        return
    candidates = sorted(
        ((tag, tags[tag]) for tag in pair),
        key=lambda item: (-item[1], item[0]),
    )
    difference = candidates[0][1] - candidates[1][1]
    if difference >= margin:
        winner, winner_score = candidates[0]
        loser, loser_score = candidates[1]
        tags.pop(loser, None)
        _record_removal(
            audit,
            loser,
            loser_score,
            "pair_conflict_loser",
            winner=winner,
            winner_score=winner_score,
            margin=difference,
        )
    else:
        names = [tag for tag, _ in candidates]
        for tag, score in candidates:
            tags.pop(tag, None)
            _record_removal(
                audit,
                tag,
                score,
                "pair_conflict_ambiguous",
                group=names,
                margin=difference,
            )


def _resolve_footwear(
    tags: dict[str, float],
    margin: float,
    audit: list[dict[str, Any]],
) -> None:
    worn = [(tag, tags[tag]) for tag in WORN_FOOTWEAR_TAGS if tag in tags]
    if "barefoot" not in tags or not worn or FOOTWEAR_EXCEPTIONS & set(tags):
        return
    best_worn, best_worn_score = max(worn, key=lambda item: (item[1], item[0]))
    barefoot_score = tags["barefoot"]
    difference = abs(barefoot_score - best_worn_score)
    if difference < margin:
        _remove_tags(
            tags,
            {"barefoot", *(tag for tag, _ in worn)},
            audit,
            "pair_conflict_ambiguous",
            group=["barefoot", *sorted(tag for tag, _ in worn)],
            margin=difference,
        )
    elif barefoot_score > best_worn_score:
        _remove_tags(
            tags,
            {tag for tag, _ in worn},
            audit,
            "pair_conflict_loser",
            winner="barefoot",
            winner_score=barefoot_score,
            margin=difference,
        )
    else:
        _remove_tags(
            tags,
            {"barefoot"},
            audit,
            "pair_conflict_loser",
            winner=best_worn,
            winner_score=best_worn_score,
            margin=difference,
        )


def _apply_single_person_rules(
    tags: dict[str, float],
    exclusive_margin: float,
    pair_margin: float,
    audit: list[dict[str, Any]],
) -> None:
    eye_keep = 2 if EYE_COLOR_EXCEPTIONS & set(tags) else 1
    _resolve_exclusive(tags, EYE_COLOR_TAGS, eye_keep, exclusive_margin, audit)
    if len(EYE_COLOR_TAGS & set(tags)) < 2:
        _remove_tags(tags, EYE_COLOR_EXCEPTIONS & set(tags), audit, "missing_support")

    hair_keep = 2 if HAIR_COLOR_EXCEPTIONS & set(tags) else 1
    _resolve_exclusive(tags, HAIR_COLOR_TAGS, hair_keep, exclusive_margin, audit)
    if len(HAIR_COLOR_TAGS & set(tags)) < 2:
        _remove_tags(tags, HAIR_COLOR_EXCEPTIONS & set(tags), audit, "missing_support")

    _resolve_exclusive(tags, HAIR_LENGTH_TAGS, 1, exclusive_margin, audit)
    _resolve_exclusive(tags, EYE_STATE_TAGS, 1, exclusive_margin, audit)
    _resolve_exclusive(tags, MOUTH_STATE_TAGS, 1, exclusive_margin, audit)
    breast_keep = 2 if BREAST_SIZE_EXCEPTIONS & set(tags) else 1
    _resolve_exclusive(tags, BREAST_SIZE_TAGS, breast_keep, exclusive_margin, audit)
    if len(AGE_APPEARANCE_TAGS & set(tags)) > 1:
        _remove_tags(
            tags,
            AGE_APPEARANCE_TAGS & set(tags),
            audit,
            "exclusive_ambiguous",
            group=sorted(AGE_APPEARANCE_TAGS & set(tags)),
        )
    _resolve_footwear(tags, pair_margin, audit)
    for pair in sorted(SOLO_CONFLICT_PAIRS, key=lambda item: tuple(sorted(item))):
        _resolve_pair(tags, pair, pair_margin, audit)


def _apply_global_conflicts(
    tags: dict[str, float],
    exclusive_margin: float,
    pair_margin: float,
    audit: list[dict[str, Any]],
) -> None:
    background_keep = 2 if BACKGROUND_COLOR_EXCEPTIONS & set(tags) else 1
    _resolve_exclusive(
        tags,
        BACKGROUND_COLOR_TAGS,
        background_keep,
        exclusive_margin,
        audit,
    )
    if not (TIME_EXCEPTIONS & set(tags)):
        _resolve_exclusive(tags, TIME_TAGS, 1, exclusive_margin, audit)
    if not (MULTI_VIEW_EXCEPTIONS & set(tags)):
        _resolve_exclusive(tags, CAMERA_ANGLE_TAGS, 1, exclusive_margin, audit)
    for pair in sorted(GLOBAL_CONFLICT_PAIRS, key=lambda item: tuple(sorted(item))):
        _resolve_pair(tags, pair, pair_margin, audit)


def _apply_support_rules(
    tags: dict[str, float],
    audit: list[dict[str, Any]],
) -> None:
    for concept, support_tags in ABSTRACT_SUPPORT_RULES.items():
        if concept not in tags:
            continue
        minimum = SUPPORT_MINIMUMS.get(concept, 1)
        support = sorted(support_tags & set(tags))
        if len(support) < minimum:
            score = tags.pop(concept)
            _record_removal(
                audit,
                concept,
                score,
                "missing_support",
                minimum_support_count=minimum,
                support_found=support,
            )


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


def _semantic_order(
    tags: dict[str, float],
    protected: list[str],
    limit: int,
    audit: list[dict[str, Any]],
) -> list[str]:
    protected_present = [tag for tag in protected if tag in tags]
    available = max(limit - len(protected_present), 0)
    buckets = {category: [] for category in CAPTION_CATEGORY_ORDER}
    for tag, score in tags.items():
        if tag in protected_present:
            continue
        buckets[_caption_category(tag)].append((tag, score))
    for entries in buckets.values():
        entries.sort(key=lambda item: (-item[1], item[0]))

    selected: list[str] = []
    max_rounds = max((len(entries) for entries in buckets.values()), default=0)
    for rank in range(max_rounds):
        for category in CAPTION_CATEGORY_ORDER:
            if len(selected) >= available:
                break
            if rank < len(buckets[category]):
                selected.append(buckets[category][rank][0])
        if len(selected) >= available:
            break

    selected_set = set(selected) | set(protected_present)
    for tag, score in tags.items():
        if tag not in selected_set:
            _record_removal(audit, tag, score, "over_limit")
    return [*protected_present, *selected]


def build_caption_result(
    item: dict[str, Any],
    trigger_prefix: str,
    threshold: float,
    denylist: set[str] | None = None,
    soft_max_tags: int = 48,
    hard_max_tags: int = 64,
    exclusive_margin: float = 0.15,
    pair_conflict_margin: float = 0.15,
    abstract_threshold: float = 0.65,
    remove_all_text_tags: bool = False,
    rule_data: CaptionRuleData | None = None,
) -> CaptionResult:
    if soft_max_tags < 8 or hard_max_tags < soft_max_tags:
        raise ValueError("caption limits must satisfy 8 <= soft_max_tags <= hard_max_tags")

    rules = rule_data or load_caption_rule_data()
    audit: list[dict[str, Any]] = []

    # Keep this runtime order explicit: raw normalization, threshold, denylist,
    # selection injection, then alias canonicalization.
    tags = _normalize_tags(item["general_tags"], audit)
    _filter_thresholds(tags, threshold, abstract_threshold, rules.aliases, audit)

    denied = {
        normalize_tag(tag)
        for tag in (
            DEFAULT_CAPTION_DENYLIST
            | set(denylist or set())
            | (OPTIONAL_TEXT_DENYLIST if remove_all_text_tags else set())
        )
        if normalize_tag(tag)
    }
    _filter_denylist(tags, denied, rules.aliases, audit)
    protected = _apply_selection_overrides(
        tags,
        item["selection_features"],
        rules.aliases,
        audit,
    )
    tags, protected = _apply_aliases(tags, rules.aliases, protected, audit)

    people_value = item["selection_features"]["people_count"].get("value")
    if people_value == 1:
        _apply_single_person_rules(
            tags,
            exclusive_margin,
            pair_conflict_margin,
            audit,
        )
    _apply_global_conflicts(
        tags,
        exclusive_margin,
        pair_conflict_margin,
        audit,
    )
    # Support is conflict post-processing: only surviving evidence counts.
    _apply_support_rules(tags, audit)
    _remove_redundant_parents(tags, rules.removable_parents, audit)

    content_limit = min(soft_max_tags, hard_max_tags) - 1
    ordered_tags = _semantic_order(tags, protected, content_limit, audit)
    final_tags = [trigger_prefix, *ordered_tags]
    if len(final_tags) > hard_max_tags:
        final_tags = final_tags[:hard_max_tags]
    return CaptionResult(
        caption=", ".join(final_tags),
        tags=ordered_tags,
        audit_log=audit,
    )
