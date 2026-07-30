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

from app.pipeline.pixai_parent_rules import (
    PIXAI_PARENT_OVERRIDES_SCHEMA_VERSION,
    transitive_reduce_parent_graph,
)
from generate_pixai_parent_rules import DEFAULT_RESOURCE_DIR

ALLOWED_DECISIONS = {"accept", "ambiguous", "reject"}


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


def _flatten_source_relations(payload: dict[str, Any]) -> set[tuple[str, str]]:
    relations: set[tuple[str, str]] = set()
    for entry in payload.get("accepted", []):
        child = str(entry["child"])
        for parent in entry["parents"]:
            pair = (child, str(parent))
            if pair in relations:
                raise ValueError(f"duplicate source relation {pair!r}")
            relations.add(pair)
    return relations


def _mapping_relations(payload: object) -> set[tuple[str, str]]:
    relations: set[tuple[str, str]] = set()
    if not isinstance(payload, dict):
        return relations
    for child, raw_parents in payload.items():
        parents = raw_parents if isinstance(raw_parents, list) else [raw_parents]
        relations.update((str(child), str(parent)) for parent in parents)
    return relations


def _relations_to_mapping(relations: set[tuple[str, str]]) -> dict[str, list[str]]:
    mapping: dict[str, set[str]] = defaultdict(set)
    for child, parent in relations:
        mapping[child].add(parent)
    return {child: sorted(parents) for child, parents in sorted(mapping.items()) if parents}


def _relation_graph(
    relations: set[tuple[str, str]],
) -> dict[str, set[str]]:
    graph: dict[str, set[str]] = defaultdict(set)
    for child, parent in relations:
        graph[child].add(parent)
    return graph


def finalize_validations(
    reviews_dir: Path,
    validations_dir: Path,
    overrides_path: Path,
    proposed_overrides_path: Path,
    report_path: Path,
    require_complete: bool = True,
) -> dict[str, Any]:
    review_files = sorted(reviews_dir.glob("batch_*.json"))
    validation_files = sorted(validations_dir.glob("batch_*.json"))
    if not review_files:
        raise FileNotFoundError(f"no review batches found in {reviews_dir}")
    validation_by_source: dict[str, Path] = {}
    for validation_file in validation_files:
        payload = _load_json(validation_file)
        source_batch = str(payload.get("source_batch", ""))
        if not source_batch:
            raise ValueError(f"{validation_file} does not name source_batch")
        if source_batch in validation_by_source:
            raise ValueError(f"duplicate validation for {source_batch}")
        validation_by_source[source_batch] = validation_file

    missing_validations: list[str] = []
    decisions_by_pair: dict[tuple[str, str], dict[str, Any]] = {}
    decision_counts = {decision: 0 for decision in sorted(ALLOWED_DECISIONS)}
    for review_file in review_files:
        source_relations = _flatten_source_relations(_load_json(review_file))
        validation_file = validation_by_source.get(review_file.name)
        if validation_file is None:
            missing_validations.append(review_file.name)
            continue
        payload = _load_json(validation_file)
        if str(payload.get("model", "")) != "gpt-5.6-sol":
            raise ValueError(f"{validation_file} used an unexpected model")
        decisions = payload.get("decisions", [])
        if not isinstance(decisions, list):
            raise TypeError(f"{validation_file} decisions must be an array")
        batch_pairs: set[tuple[str, str]] = set()
        for entry in decisions:
            if not isinstance(entry, dict):
                raise TypeError(f"{validation_file} contains a non-object decision")
            pair = (str(entry.get("child", "")), str(entry.get("parent", "")))
            decision = str(entry.get("decision", "")).casefold()
            if decision not in ALLOWED_DECISIONS:
                raise ValueError(f"{validation_file} has invalid decision {decision!r}")
            if pair in batch_pairs:
                raise ValueError(f"{validation_file} duplicates relation {pair!r}")
            batch_pairs.add(pair)
            decisions_by_pair[pair] = {
                "source_batch": review_file.name,
                "validation_batch": validation_file.name,
                "decision": decision,
                "rationale": str(entry.get("rationale", "")),
            }
            decision_counts[decision] += 1
        if batch_pairs != source_relations:
            missing = sorted(source_relations - batch_pairs)
            extra = sorted(batch_pairs - source_relations)
            raise ValueError(
                f"{validation_file} does not exactly cover source relations; "
                f"missing={missing[:5]}, extra={extra[:5]}"
            )
        if int(payload.get("reviewed_relation_count", -1)) != len(source_relations):
            raise ValueError(f"{validation_file} reviewed_relation_count is incorrect")

    if require_complete and missing_validations:
        raise ValueError("missing second-pass validation files: " + ", ".join(missing_validations))

    overrides = _load_json(overrides_path)
    if int(overrides.get("schema_version", -1)) != PIXAI_PARENT_OVERRIDES_SCHEMA_VERSION:
        raise ValueError("unsupported PixAI parent override schema")
    existing_additions = _mapping_relations(overrides.get("add", {}))
    protected_removals = _mapping_relations(overrides.get("remove", {}))
    llm_accepted = {
        pair for pair, evidence in decisions_by_pair.items() if evidence["decision"] == "accept"
    }
    llm_non_accept = set(decisions_by_pair) - llm_accepted
    blocked = llm_accepted & protected_removals
    promoted = llm_accepted - protected_removals
    # The validated GPT decision is authoritative. Existing additions may come
    # from an older/manual rule set and must not reintroduce a relation that the
    # second pass rejected, marked ambiguous, or never reviewed.
    discarded_existing_non_accept = existing_additions - llm_accepted
    unreduced_relations = promoted
    reduced_graph = transitive_reduce_parent_graph(_relation_graph(unreduced_relations))
    final_relations = {
        (child, parent) for child, parents in reduced_graph.items() for parent in parents
    }

    proposed_overrides = {
        "schema_version": PIXAI_PARENT_OVERRIDES_SCHEMA_VERSION,
        "aliases": overrides.get("aliases", {}),
        "add": _relations_to_mapping(final_relations),
        "remove": _relations_to_mapping(protected_removals | llm_non_accept),
    }
    report = {
        "schema_version": PIXAI_PARENT_OVERRIDES_SCHEMA_VERSION,
        "model": "gpt-5.6-sol",
        "first_pass_batch_count": len(review_files),
        "second_pass_batch_count": len(validation_files),
        "missing_validations": missing_validations,
        "first_pass_relation_count": sum(decision_counts.values()),
        "second_pass_counts": decision_counts,
        "manual_existing_relation_count": len(existing_additions),
        "promoted_llm_relation_count": len(promoted),
        "non_accept_relation_count": len(llm_non_accept),
        "blocked_by_manual_remove_count": len(blocked),
        "blocked_by_manual_remove": [
            {"child": child, "parent": parent} for child, parent in sorted(blocked)
        ],
        "discarded_existing_non_accept_count": len(discarded_existing_non_accept),
        "discarded_existing_non_accept": [
            {"child": child, "parent": parent}
            for child, parent in sorted(discarded_existing_non_accept)
        ],
        "proposed_unreduced_relation_count": len(unreduced_relations),
        "proposed_reduced_relation_count": len(final_relations),
        "proposed_direct_relation_count": len(final_relations),
        "proposed_removed_relation_count": (len(unreduced_relations) - len(final_relations)),
        "decisions": [
            {
                "child": child,
                "parent": parent,
                **evidence,
            }
            for (child, parent), evidence in sorted(decisions_by_pair.items())
        ],
    }
    _write_json(proposed_overrides_path, proposed_overrides)
    _write_json(report_path, report)
    return report


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate second-pass GPT review and build proposed PixAI overrides."
    )
    parser.add_argument(
        "--reviews-dir",
        type=Path,
        default=DEFAULT_RESOURCE_DIR / "pixai_parent_llm_reviews",
    )
    parser.add_argument(
        "--validations-dir",
        type=Path,
        default=DEFAULT_RESOURCE_DIR / "pixai_parent_llm_validations",
    )
    parser.add_argument(
        "--overrides",
        type=Path,
        default=DEFAULT_RESOURCE_DIR / "pixai_parent_overrides.json",
    )
    parser.add_argument(
        "--proposed-overrides",
        type=Path,
        default=DEFAULT_RESOURCE_DIR / "pixai_parent_llm_proposed_overrides.json",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_RESOURCE_DIR / "pixai_parent_llm_validation_report.json",
    )
    parser.add_argument("--allow-incomplete", action="store_true")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    report = finalize_validations(
        args.reviews_dir.resolve(),
        args.validations_dir.resolve(),
        args.overrides.resolve(),
        args.proposed_overrides.resolve(),
        args.report.resolve(),
        require_complete=not args.allow_incomplete,
    )
    print(f"First-pass relations: {report['first_pass_relation_count']}")
    print(f"Second-pass decisions: {report['second_pass_counts']}")
    print(f"Promoted LLM relations: {report['promoted_llm_relation_count']}")
    print(f"Proposed direct relations: {report['proposed_direct_relation_count']}")
    print(f"Proposed overrides: {args.proposed_overrides.resolve()}")
    print(f"Validation report: {args.report.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
