from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from generate_pixai_parent_rules import (
    DEFAULT_RESOURCE_DIR,
    discover_pixai_tag_file,
    read_pixai_general_tags,
)

RELATION_TYPE_ALIASES = {
    "attribute_refinement": "specific_attribute",
    "specific_attribute": "specific_attribute",
    "strict_subtype": "strict_subtype",
    "strong_state": "strong_state",
    "strong_state_refinement": "strong_state",
}


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return payload


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _relation_set(payload: object) -> set[tuple[str, str]]:
    relations: set[tuple[str, str]] = set()
    if not isinstance(payload, dict):
        return relations
    for child, raw_parents in payload.items():
        parents = raw_parents if isinstance(raw_parents, list) else [raw_parents]
        for parent in parents:
            relations.add((str(child), str(parent)))
    return relations


def _is_high_confidence(value: object) -> bool:
    if isinstance(value, (int, float)):
        return float(value) >= 0.90
    return str(value).casefold() == "high"


def _detect_cycles(graph: dict[str, set[str]], label: str) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str, trail: list[str]) -> None:
        if node in visiting:
            start = trail.index(node)
            raise ValueError(f"{label} cycle detected: {' -> '.join(trail[start:])}")
        if node in visited:
            return
        visiting.add(node)
        for parent in sorted(graph.get(node, ())):
            visit(parent, [*trail, parent])
        visiting.remove(node)
        visited.add(node)

    for node in sorted(graph):
        visit(node, [node])


def merge_reviews(
    pixai_tags_path: Path,
    reviews_dir: Path,
    overrides_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    general_tags, category_counts = read_pixai_general_tags(pixai_tags_path)
    vocabulary = set(general_tags)
    review_files = sorted(reviews_dir.glob("batch_*.json"))
    if not review_files:
        raise FileNotFoundError(f"no batch_*.json files found in {reviews_dir}")

    covered_by: list[str | None] = [None] * len(general_tags)
    accepted_by_pair: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    aliases_by_pair: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    ambiguous: list[dict[str, Any]] = []
    models: set[str] = set()

    for review_file in review_files:
        payload = _load_json(review_file)
        if int(payload.get("schema_version", -1)) != 1:
            raise ValueError(f"{review_file} has an unsupported schema")
        model = str(payload.get("model", ""))
        if model != "gpt-5.6-sol":
            raise ValueError(f"{review_file} used unexpected model {model!r}")
        models.add(model)
        start = int(payload["range_start"])
        end = int(payload["range_end"])
        if start < 0 or end < start or end >= len(general_tags):
            raise ValueError(f"{review_file} has invalid range {start}..{end}")
        reviewed_tags = payload.get("reviewed_tags")
        if not isinstance(reviewed_tags, list):
            raise TypeError(f"{review_file} reviewed_tags must be an array")
        expected_tags = general_tags[start : end + 1]
        if reviewed_tags != expected_tags:
            raise ValueError(
                f"{review_file} reviewed_tags do not exactly match sorted range {start}..{end}"
            )
        if int(payload.get("reviewed_tag_count", -1)) != len(expected_tags):
            raise ValueError(f"{review_file} reviewed_tag_count is incorrect")
        for index in range(start, end + 1):
            if covered_by[index] is not None:
                raise ValueError(
                    f"tag index {index} is covered by both {covered_by[index]} "
                    f"and {review_file.name}"
                )
            covered_by[index] = review_file.name
        reviewed_set = set(reviewed_tags)

        accepted = payload.get("accepted", [])
        if not isinstance(accepted, list):
            raise TypeError(f"{review_file} accepted must be an array")
        for entry in accepted:
            if not isinstance(entry, dict):
                raise TypeError(f"{review_file} contains a non-object accepted entry")
            child = str(entry.get("child", ""))
            parents = entry.get("parents", [])
            raw_relation_type = str(entry.get("relation_type", ""))
            relation_type = RELATION_TYPE_ALIASES.get(raw_relation_type, "")
            confidence = entry.get("confidence", "")
            if child not in reviewed_set:
                raise ValueError(f"{review_file}: accepted child {child!r} is outside its batch")
            if not _is_high_confidence(confidence) or not relation_type:
                raise ValueError(
                    f"{review_file}: accepted relation for {child!r} is not high-confidence "
                    "or uses an unsupported type"
                )
            if not isinstance(parents, list) or not parents:
                raise ValueError(f"{review_file}: accepted child {child!r} has no parents")
            for raw_parent in parents:
                parent = str(raw_parent)
                if parent not in vocabulary or parent == child:
                    raise ValueError(
                        f"{review_file}: invalid parent relation {child!r} -> {parent!r}"
                    )
                accepted_by_pair[(child, parent)].append(
                    {
                        "batch": review_file.name,
                        "relation_type": relation_type,
                        "rationale": str(entry.get("rationale", "")),
                    }
                )

        aliases = payload.get("aliases", [])
        if not isinstance(aliases, list):
            raise TypeError(f"{review_file} aliases must be an array")
        for entry in aliases:
            if not isinstance(entry, dict):
                raise TypeError(f"{review_file} contains a non-object alias entry")
            alias = str(entry.get("alias", ""))
            canonical = str(entry.get("canonical", ""))
            confidence = entry.get("confidence", "")
            if alias not in reviewed_set:
                raise ValueError(f"{review_file}: alias {alias!r} is outside its batch")
            if (
                canonical not in vocabulary
                or alias == canonical
                or not _is_high_confidence(confidence)
            ):
                raise ValueError(
                    f"{review_file}: invalid or non-high-confidence alias "
                    f"{alias!r} -> {canonical!r}"
                )
            aliases_by_pair[(alias, canonical)].append(
                {
                    "batch": review_file.name,
                    "rationale": str(entry.get("rationale", "")),
                }
            )

        batch_ambiguous = payload.get("ambiguous", [])
        if not isinstance(batch_ambiguous, list):
            raise TypeError(f"{review_file} ambiguous must be an array")
        for entry in batch_ambiguous:
            if not isinstance(entry, dict):
                raise TypeError(f"{review_file} contains a non-object ambiguous entry")
            child = str(entry.get("child", ""))
            if child not in reviewed_set:
                raise ValueError(f"{review_file}: ambiguous child {child!r} is outside its batch")
            ambiguous.append({"batch": review_file.name, **entry})

    missing_indices = [index for index, owner in enumerate(covered_by) if owner is None]
    overrides = _load_json(overrides_path)
    blocked_relations = _relation_set(overrides.get("remove", {}))
    existing_relations = _relation_set(overrides.get("add", {}))
    accepted_records: list[dict[str, Any]] = []
    blocked_records: list[dict[str, Any]] = []
    for (child, parent), evidence in sorted(accepted_by_pair.items()):
        record = {
            "child": child,
            "parent": parent,
            "evidence": evidence,
        }
        if (child, parent) in blocked_relations:
            blocked_records.append(record)
        else:
            accepted_records.append(record)

    graph: dict[str, set[str]] = defaultdict(set)
    for child, parent in existing_relations:
        graph[child].add(parent)
    for record in accepted_records:
        graph[record["child"]].add(record["parent"])
    _detect_cycles(graph, "parent relation")

    alias_graph: dict[str, set[str]] = defaultdict(set)
    for alias, canonical in aliases_by_pair:
        alias_graph[alias].add(canonical)
    _detect_cycles(alias_graph, "alias")

    summary = {
        "schema_version": 1,
        "model": sorted(models),
        "pixai_general_tags": category_counts.get("0", 0),
        "normalized_general_tags": len(general_tags),
        "batch_count": len(review_files),
        "reviewed_tag_count": len(general_tags) - len(missing_indices),
        "coverage_complete": not missing_indices,
        "missing_indices": missing_indices,
        "accepted_relation_count": len(accepted_records),
        "accepted": accepted_records,
        "blocked_by_manual_remove_count": len(blocked_records),
        "blocked_by_manual_remove": blocked_records,
        "alias_count": len(aliases_by_pair),
        "aliases": [
            {
                "alias": alias,
                "canonical": canonical,
                "evidence": evidence,
            }
            for (alias, canonical), evidence in sorted(aliases_by_pair.items())
        ],
        "ambiguous_count": len(ambiguous),
        "ambiguous": sorted(
            ambiguous,
            key=lambda entry: (
                str(entry.get("child", "")),
                str(entry.get("possible_parent", "")),
                str(entry.get("batch", "")),
            ),
        ),
    }
    _write_json(output_path, summary)
    return summary


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate and merge GPT-5.6-sol PixAI parent-tag review batches."
    )
    parser.add_argument("--pixai-tags", type=Path)
    parser.add_argument(
        "--reviews-dir",
        type=Path,
        default=DEFAULT_RESOURCE_DIR / "pixai_parent_llm_reviews",
    )
    parser.add_argument(
        "--overrides",
        type=Path,
        default=DEFAULT_RESOURCE_DIR / "pixai_parent_overrides.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_RESOURCE_DIR / "pixai_parent_llm_review_summary.json",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    summary = merge_reviews(
        args.pixai_tags or discover_pixai_tag_file(),
        args.reviews_dir.resolve(),
        args.overrides.resolve(),
        args.output.resolve(),
    )
    print(
        f"Reviewed tags: {summary['reviewed_tag_count']}/"
        f"{summary['normalized_general_tags']}"
    )
    print(f"Coverage complete: {summary['coverage_complete']}")
    print(f"Accepted relations: {summary['accepted_relation_count']}")
    print(f"Aliases: {summary['alias_count']}")
    print(f"Ambiguous: {summary['ambiguous_count']}")
    print(f"Summary: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
