from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.pipeline.pixai_parent_rules import (
    PIXAI_PARENT_OVERRIDES_SCHEMA_VERSION,
    PIXAI_PARENT_RULES_SCHEMA_VERSION,
    canonicalize_parent_tag,
    normalize_parent_tag,
    transitive_parent_closure,
    transitive_reduce_parent_graph,
)

MODEL_REPO_CACHE_NAME = "models--deepghs--pixai-tagger-v0.9-onnx"
PIXAI_TAG_FILENAME = "selected_tags.csv"
DEFAULT_RESOURCE_DIR = BACKEND_ROOT / "app" / "pipeline" / "resources"


def _json_bytes(payload: Any) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(_json_bytes(payload))
    temporary.replace(path)


def _load_json(path: Path | None, default: Any) -> Any:
    if path is None:
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _candidate_huggingface_hubs() -> list[Path]:
    roots: list[Path] = []
    if os.environ.get("HF_HUB_CACHE"):
        roots.append(Path(os.environ["HF_HUB_CACHE"]).expanduser())
    if os.environ.get("HF_HOME"):
        roots.append(Path(os.environ["HF_HOME"]).expanduser() / "hub")
    roots.append(Path.home() / ".cache" / "huggingface" / "hub")
    unique: list[Path] = []
    for root in roots:
        resolved = root.resolve()
        if resolved not in unique:
            unique.append(resolved)
    return unique


def discover_pixai_tag_file() -> Path:
    candidates: list[Path] = []
    for hub in _candidate_huggingface_hubs():
        snapshots = hub / MODEL_REPO_CACHE_NAME / "snapshots"
        if snapshots.is_dir():
            candidates.extend(snapshots.glob(f"*/{PIXAI_TAG_FILENAME}"))
    candidates = [candidate for candidate in candidates if candidate.is_file()]
    if not candidates:
        raise FileNotFoundError(
            "PixAI general-tag source was not found in the Hugging Face cache. "
            "Download deepghs/pixai-tagger-v0.9-onnx or pass --pixai-tags."
        )
    return max(candidates, key=lambda path: path.stat().st_mtime_ns)


def read_pixai_general_tags(path: Path) -> tuple[list[str], dict[str, int]]:
    tags: set[str] = set()
    category_counts: dict[str, int] = defaultdict(int)
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"name", "category"}
        if not required <= set(reader.fieldnames or []):
            raise ValueError(f"{path} does not contain the required columns: {sorted(required)}")
        for row in reader:
            category = str(row["category"]).strip()
            category_counts[category] += 1
            if category != "0":
                continue
            tag = normalize_parent_tag(row["name"])
            if tag:
                tags.add(tag)
    return sorted(tags), dict(sorted(category_counts.items()))


def _active_relationships(
    payload: object,
    relationship: str,
) -> tuple[list[tuple[str, str]], int]:
    if payload is None:
        return [], 0
    if not isinstance(payload, list):
        raise TypeError(f"{relationship} snapshot must be a JSON array with explicit active status")
    relationships: list[tuple[str, str]] = []
    ignored = 0
    for entry in payload:
        if not isinstance(entry, dict):
            ignored += 1
            continue
        if str(entry.get("status", "")).casefold() != "active":
            ignored += 1
            continue
        antecedent = normalize_parent_tag(
            entry.get("antecedent_name") or entry.get("antecedent") or ""
        )
        consequent = normalize_parent_tag(
            entry.get("consequent_name") or entry.get("consequent") or ""
        )
        if antecedent and consequent and antecedent != consequent:
            relationships.append((antecedent, consequent))
        else:
            ignored += 1
    return sorted(set(relationships)), ignored


def _read_overrides(path: Path) -> dict[str, Any]:
    payload = _load_json(path, {})
    if not isinstance(payload, dict):
        raise TypeError("PixAI parent overrides must contain a JSON object")
    if int(payload.get("schema_version", -1)) != PIXAI_PARENT_OVERRIDES_SCHEMA_VERSION:
        raise ValueError("unsupported PixAI parent override schema")
    for field in ("aliases", "add", "remove"):
        if not isinstance(payload.get(field, {}), dict):
            raise TypeError(f"override field {field!r} must be a JSON object")
    return payload


def _canonical_alias_map(
    active_aliases: list[tuple[str, str]],
    manual_aliases: dict[str, str],
    general_tags: set[str],
    unknown_tags: set[str],
) -> dict[str, str]:
    aliases = {
        normalize_parent_tag(left): normalize_parent_tag(right) for left, right in active_aliases
    }
    aliases.update(
        {
            normalize_parent_tag(left): normalize_parent_tag(right)
            for left, right in manual_aliases.items()
        }
    )
    valid: dict[str, str] = {}
    for left, right in sorted(aliases.items()):
        if left not in general_tags or right not in general_tags:
            unknown_tags.update({tag for tag in (left, right) if tag not in general_tags})
            continue
        if left != right:
            valid[left] = right
    for alias in valid:
        canonicalize_parent_tag(alias, valid)
    return valid


def _add_candidate(
    candidates: dict[tuple[str, str], set[str]],
    child: str,
    parent: str,
    source: str,
) -> None:
    if child and parent and child != parent:
        candidates[(child, parent)].add(source)


def _structural_candidates(general_tags: set[str]) -> set[tuple[str, str]]:
    candidates: set[tuple[str, str]] = set()
    for child in general_tags:
        parts = child.split("_")
        for index in range(1, len(parts)):
            parent = "_".join(parts[index:])
            if parent in general_tags and parent != child:
                candidates.add((child, parent))
    return candidates


def _read_relation_override(
    payload: object,
    aliases: dict[str, str],
    general_tags: set[str],
    unknown_tags: set[str],
) -> set[tuple[str, str]]:
    relations: set[tuple[str, str]] = set()
    if not isinstance(payload, dict):
        return relations
    for raw_child, raw_parents in payload.items():
        parents = raw_parents if isinstance(raw_parents, list) else [raw_parents]
        child = canonicalize_parent_tag(normalize_parent_tag(raw_child), aliases)
        for raw_parent in parents:
            parent = canonicalize_parent_tag(normalize_parent_tag(raw_parent), aliases)
            missing = {tag for tag in (child, parent) if tag not in general_tags}
            if missing:
                unknown_tags.update(missing)
                continue
            if child != parent:
                relations.add((child, parent))
    return relations


def _relations_to_mapping(
    relations: set[tuple[str, str]],
) -> dict[str, list[str]]:
    mapping: dict[str, set[str]] = defaultdict(set)
    for child, parent in relations:
        mapping[child].add(parent)
    return {
        child: sorted(parents)
        for child, parents in sorted(mapping.items())
        if parents
    }


def _fingerprint(paths: list[Path | None]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        if path is None:
            digest.update(b"<none>")
        else:
            digest.update(path.name.encode("utf-8"))
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _stable_generated_at(output: Path, input_fingerprint: str) -> str:
    try:
        existing = json.loads(output.read_text(encoding="utf-8"))
        if existing.get("input_fingerprint") == input_fingerprint:
            return str(existing["generated_at"])
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        pass
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(BACKEND_ROOT.parent))
    except ValueError:
        return str(path.resolve())


def generate_rules(
    pixai_tags_path: Path,
    overrides_path: Path,
    aliases_path: Path | None,
    implications_path: Path | None,
    output_path: Path,
    report_path: Path,
    candidates_path: Path,
) -> dict[str, Any]:
    general_tag_list, category_counts = read_pixai_general_tags(pixai_tags_path)
    general_tags = set(general_tag_list)
    raw_general_tag_count = category_counts.get("0", 0)
    overrides = _read_overrides(overrides_path)
    alias_payload = _load_json(aliases_path, None)
    implication_payload = _load_json(implications_path, None)
    active_aliases, aliases_ignored = _active_relationships(alias_payload, "alias")
    active_implications, implications_ignored = _active_relationships(
        implication_payload,
        "implication",
    )

    unknown_tags: set[str] = set()
    aliases = _canonical_alias_map(
        active_aliases,
        overrides.get("aliases", {}),
        general_tags,
        unknown_tags,
    )
    candidates: dict[tuple[str, str], set[str]] = defaultdict(set)
    for raw_child, raw_parent in active_implications:
        child = canonicalize_parent_tag(raw_child, aliases)
        parent = canonicalize_parent_tag(raw_parent, aliases)
        if child in general_tags and parent in general_tags:
            _add_candidate(candidates, child, parent, "danbooru_active_implication")
    structural = _structural_candidates(general_tags)
    for child, parent in structural:
        _add_candidate(candidates, child, parent, "name_structure")

    removals = _read_relation_override(
        overrides.get("remove", {}),
        aliases,
        general_tags,
        unknown_tags,
    )
    additions = _read_relation_override(
        overrides.get("add", {}),
        aliases,
        general_tags,
        unknown_tags,
    )
    contradictory_overrides = additions & removals
    if contradictory_overrides:
        raise ValueError(
            "parent relations cannot be both added and blocked: "
            f"{sorted(contradictory_overrides)[:5]}"
        )
    for relation in removals:
        candidates.pop(relation, None)
    graph: dict[str, set[str]] = defaultdict(set)
    for child, parent in sorted(additions):
        graph[child].add(parent)
    direct_graph = transitive_reduce_parent_graph(graph)
    closure_graph = transitive_parent_closure(direct_graph)
    direct_mapping = {child: sorted(parents) for child, parents in direct_graph.items()}
    blocked_mapping = _relations_to_mapping(removals)
    blocked_by_child = {
        child: set(parents) for child, parents in blocked_mapping.items()
    }
    runtime_graph = {
        child: frozenset(parents - blocked_by_child.get(child, set()))
        for child, parents in closure_graph.items()
    }
    closure = {
        child: sorted(parents) for child, parents in runtime_graph.items() if parents
    }

    accepted = {(child, parent) for child, parents in runtime_graph.items() for parent in parents}
    direct_relations = {
        (child, parent) for child, parents in direct_graph.items() for parent in parents
    }
    review_candidates = [
        {
            "child": child,
            "parent": parent,
            "sources": sorted(sources),
        }
        for (child, parent), sources in sorted(candidates.items())
        if (child, parent) not in accepted and (child, parent) not in removals
    ]

    input_fingerprint = _fingerprint(
        [
            Path(__file__),
            pixai_tags_path,
            overrides_path,
            aliases_path,
            implications_path,
        ]
    )
    generated_at = _stable_generated_at(output_path, input_fingerprint)
    source_label = (
        f"deepghs/pixai-tagger-v0.9-onnx:{PIXAI_TAG_FILENAME}@{pixai_tags_path.parent.name}"
    )
    sources = {
        "pixai_tags": source_label,
        "aliases": str(aliases_path.resolve()) if aliases_path else None,
        "implications": str(implications_path.resolve()) if implications_path else None,
        "overrides": _display_path(overrides_path),
    }
    rules_payload = {
        "schema_version": PIXAI_PARENT_RULES_SCHEMA_VERSION,
        "pixai_model": "pixai-tagger-v0.9",
        "general_tag_count": raw_general_tag_count,
        "generated_at": generated_at,
        "input_fingerprint": input_fingerprint,
        "sources": sources,
        "aliases": dict(sorted(aliases.items())),
        "child_to_direct_parents": direct_mapping,
        "blocked_child_to_parents": blocked_mapping,
    }
    report = {
        "schema_version": PIXAI_PARENT_RULES_SCHEMA_VERSION,
        "generated_at": generated_at,
        "input_fingerprint": input_fingerprint,
        "sources": sources,
        "pixai_general_tags": raw_general_tag_count,
        "normalized_general_tags": len(general_tags),
        "empty_general_tags_discarded": raw_general_tag_count - len(general_tags),
        "pixai_category_counts": category_counts,
        "aliases_loaded": len(active_aliases),
        "aliases_ignored_non_active_or_invalid": aliases_ignored,
        "implications_loaded": len(active_implications),
        "implications_ignored_non_active_or_invalid": implications_ignored,
        "accepted_parent_relations": len(accepted),
        "input_relation_count": len(additions),
        "direct_relation_count": len(direct_relations),
        "closure_relation_count": len(accepted),
        "blocked_relation_count": len(removals),
        "removed_relation_count": len(additions) - len(direct_relations),
        "rejected_non_taxonomic_relations": len(review_candidates),
        "structural_candidates": len(structural),
        "manual_additions": len(additions),
        "manual_removals": len(removals),
        "cycles_found": 0,
        "unknown_tags": sorted(unknown_tags),
        "examples": [
            {"child": child, "parents": parents} for child, parents in list(closure.items())[:25]
        ],
    }
    candidate_payload = {
        "schema_version": PIXAI_PARENT_RULES_SCHEMA_VERSION,
        "generated_at": generated_at,
        "input_fingerprint": input_fingerprint,
        "candidate_count": len(review_candidates),
        "note": (
            "Review candidates are never applied at runtime. Promote only strict "
            "taxonomic parent relations through pixai_parent_overrides.json."
        ),
        "candidates": review_candidates,
    }
    _write_json(output_path, rules_payload)
    _write_json(report_path, report)
    _write_json(candidates_path, candidate_payload)
    return report


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate strict PixAI v0.9 removable-parent rules."
    )
    parser.add_argument("--pixai-tags", type=Path)
    parser.add_argument(
        "--overrides",
        type=Path,
        default=DEFAULT_RESOURCE_DIR / "pixai_parent_overrides.json",
    )
    parser.add_argument("--aliases", type=Path)
    parser.add_argument("--implications", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_RESOURCE_DIR / "pixai_parent_rules.json",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_RESOURCE_DIR / "pixai_parent_rules_report.json",
    )
    parser.add_argument(
        "--review-candidates",
        type=Path,
        default=DEFAULT_RESOURCE_DIR / "pixai_parent_review_candidates.json",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    pixai_tags = args.pixai_tags or discover_pixai_tag_file()
    report = generate_rules(
        pixai_tags,
        args.overrides.resolve(),
        args.aliases.resolve() if args.aliases else None,
        args.implications.resolve() if args.implications else None,
        args.output.resolve(),
        args.report.resolve(),
        args.review_candidates.resolve(),
    )
    print(f"PixAI general tags: {report['pixai_general_tags']}")
    print(f"Accepted removable-parent relations: {report['accepted_parent_relations']}")
    print(
        "Review-only non-taxonomic/structural candidates: "
        f"{report['rejected_non_taxonomic_relations']}"
    )
    print(f"Rules: {args.output.resolve()}")
    print(f"Report: {args.report.resolve()}")
    print(f"Review candidates: {args.review_candidates.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
