import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest
from app.pipeline.caption_rules import build_caption_result
from app.pipeline.pixai_parent_rules import (
    PIXAI_PARENT_OVERRIDES_SCHEMA_VERSION,
    PIXAI_PARENT_RULES_SCHEMA_VERSION,
    load_pixai_parent_rules,
    remove_redundant_parent_tags,
    transitive_reduce_parent_graph,
)


def _caption_item(tags: dict[str, float]) -> dict:
    return {
        "general_tags": tags,
        "selection_features": {
            "people_count": {
                "value": 1,
                "confidence": 0.95,
                "source_tag": "1girl",
            },
            "framing": {
                "value": "cowboy_shot",
                "confidence": 0.90,
                "source_tag": "cowboy_shot",
            },
            "outdoors": {
                "value": None,
                "confidence": 0.0,
                "source_tag": None,
            },
        },
    }


def test_parent_cleanup_handles_direct_multiple_and_transitive_parents():
    rules = {
        "school_bag": {"bag"},
        "plaid_skirt": {"skirt", "plaid_clothes"},
        "specific_child": {"direct_parent", "broad_parent"},
    }
    tags = [
        "school_bag",
        "bag",
        "plaid_skirt",
        "skirt",
        "plaid_clothes",
        "specific_child",
        "direct_parent",
        "broad_parent",
    ]

    assert remove_redundant_parent_tags(tags, rules) == [
        "school_bag",
        "plaid_skirt",
        "specific_child",
    ]


def test_parent_cleanup_preserves_siblings_dimensions_and_parent_without_child():
    rules = {
        "plaid_skirt": {"skirt", "plaid_clothes"},
        "red_collar": {"collar"},
        "animal_collar": {"collar"},
        "serafuku": {"school_uniform"},
    }
    tags = [
        "school_uniform",
        "plaid_skirt",
        "pleated_skirt",
        "red_collar",
        "animal_collar",
        "collar",
        "sailor_collar",
    ]

    assert remove_redundant_parent_tags(tags, rules) == [
        "school_uniform",
        "plaid_skirt",
        "pleated_skirt",
        "red_collar",
        "animal_collar",
        "sailor_collar",
    ]


def test_parent_cleanup_alias_order_scores_and_idempotency():
    rules = {"canonical_child": {"parent"}}
    aliases = {"old_child": "canonical_child"}
    tags = {
        "first": 0.9,
        "old_child": 0.7,
        "canonical_child": 0.8,
        "parent": 0.6,
        "last": 0.5,
    }

    cleaned = remove_redundant_parent_tags(tags, rules, aliases)

    assert list(cleaned) == ["first", "canonical_child", "last"]
    assert cleaned["canonical_child"] == 0.8
    assert remove_redundant_parent_tags(cleaned, rules, aliases) == cleaned


def test_packaged_rules_clean_current_example_without_touching_prefix():
    input_tags = [
        "blue_reflection",
        "1girl",
        "solo",
        "cowboy_shot",
        "looking_at_viewer",
        "school_uniform",
        "bag",
        "closed_mouth",
        "simple_background",
        "serafuku",
        "skirt",
        "school_bag",
        "white_background",
        "midriff_peek",
        "plaid_skirt",
        "sailor_collar",
        "thigh_gap",
        "short_hair",
        "bow",
        "plaid_clothes",
        "pleated_skirt",
        "short_sleeves",
        "shirt",
        "black_hair",
        "white_shirt",
    ]
    rules = load_pixai_parent_rules()

    cleaned = remove_redundant_parent_tags(
        input_tags,
        rules.child_to_parents,
        rules.aliases,
    )

    assert not {
        "school_uniform",
        "bag",
        "skirt",
        "plaid_clothes",
    } & set(cleaned)
    assert {
        "serafuku",
        "school_bag",
        "simple_background",
        "white_background",
        "plaid_skirt",
        "pleated_skirt",
        "sailor_collar",
        "shirt",
        "white_shirt",
    } <= set(cleaned)

    result = build_caption_result(
        _caption_item(
            {
                "1girl": 0.98,
                "cowboy_shot": 0.95,
                "serafuku": 0.90,
                "school_uniform": 0.82,
            }
        ),
        "school_uniform",
        0.50,
    )
    assert result.caption.split(", ")[0] == "school_uniform"
    assert "school_uniform" not in result.tags
    assert "serafuku" in result.tags


def test_parent_rule_loader_warns_and_falls_back_but_supports_strict_mode(tmp_path):
    missing = tmp_path / "missing.json"

    with pytest.warns(RuntimeWarning, match="continuing without parent tag cleanup"):
        rules = load_pixai_parent_rules(str(missing), False)
    assert rules.child_to_parents == {}
    assert rules.child_to_direct_parents == {}

    with pytest.raises(RuntimeError, match="failed to load PixAI parent rules"):
        load_pixai_parent_rules(str(missing), True)


def test_parent_rule_loader_v2_expands_direct_diamond_to_runtime_closure(tmp_path):
    rules_path = tmp_path / "rules_v2.json"
    rules_path.write_text(
        json.dumps(
            {
                "schema_version": PIXAI_PARENT_RULES_SCHEMA_VERSION,
                "pixai_model": "pixai-tagger-v0.9",
                "general_tag_count": 4,
                "aliases": {},
                "blocked_child_to_parents": {
                    "specific_child": ["root_parent"],
                },
                "child_to_direct_parents": {
                    "specific_child": ["left_parent", "right_parent"],
                    "left_parent": ["root_parent"],
                    "right_parent": ["root_parent"],
                },
            }
        ),
        encoding="utf-8",
    )

    rules = load_pixai_parent_rules(str(rules_path), True)

    assert rules.child_to_direct_parents == {
        "left_parent": frozenset({"root_parent"}),
        "right_parent": frozenset({"root_parent"}),
        "specific_child": frozenset({"left_parent", "right_parent"}),
    }
    assert rules.child_to_parents == {
        "left_parent": frozenset({"root_parent"}),
        "right_parent": frozenset({"root_parent"}),
        "specific_child": frozenset({"left_parent", "right_parent"}),
    }
    assert rules.blocked_child_to_parents == {
        "specific_child": frozenset({"root_parent"}),
    }
    assert rules.direct_relation_count == 4
    assert rules.blocked_relation_count == 1
    assert rules.parent_relation_count == 4
    assert rules.relation_count == 4

    siblings = ["left_parent", "right_parent", "root_parent", "unrelated"]
    cleaned = remove_redundant_parent_tags(
        siblings,
        rules.child_to_parents,
        rules.aliases,
    )
    assert cleaned == ["left_parent", "right_parent", "unrelated"]
    assert (
        remove_redundant_parent_tags(
            cleaned,
            rules.child_to_parents,
            rules.aliases,
        )
        == cleaned
    )


def test_parent_rule_loader_canonicalizes_graph_nodes_through_aliases(tmp_path):
    rules_path = tmp_path / "aliased_rules_v2.json"
    rules_path.write_text(
        json.dumps(
            {
                "schema_version": PIXAI_PARENT_RULES_SCHEMA_VERSION,
                "aliases": {
                    "old_leaf": "leaf",
                    "old_middle": "middle",
                },
                "child_to_direct_parents": {
                    "old_leaf": ["old_middle"],
                    "old_middle": ["root"],
                },
            }
        ),
        encoding="utf-8",
    )

    rules = load_pixai_parent_rules(str(rules_path), True)

    assert rules.child_to_direct_parents == {
        "leaf": frozenset({"middle"}),
        "middle": frozenset({"root"}),
    }
    assert rules.child_to_parents == {
        "leaf": frozenset({"middle", "root"}),
        "middle": frozenset({"root"}),
    }


def test_parent_rule_loader_rejects_alias_induced_self_cycle(tmp_path):
    rules_path = tmp_path / "alias_self_cycle_v2.json"
    rules_path.write_text(
        json.dumps(
            {
                "schema_version": PIXAI_PARENT_RULES_SCHEMA_VERSION,
                "aliases": {"old_leaf": "leaf"},
                "child_to_direct_parents": {"old_leaf": ["leaf"]},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        RuntimeError,
        match="alias canonicalization creates a parent self-cycle",
    ):
        load_pixai_parent_rules(str(rules_path), True)


def test_parent_rule_loader_rejects_directly_blocked_relation(tmp_path):
    rules_path = tmp_path / "directly_blocked_v2.json"
    rules_path.write_text(
        json.dumps(
            {
                "schema_version": PIXAI_PARENT_RULES_SCHEMA_VERSION,
                "aliases": {},
                "child_to_direct_parents": {"child": ["parent"]},
                "blocked_child_to_parents": {"child": ["parent"]},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="directly blocked parent relations"):
        load_pixai_parent_rules(str(rules_path), True)


def test_parent_rule_loader_keeps_v1_closure_compatible(tmp_path):
    rules_path = tmp_path / "rules_v1.json"
    rules_path.write_text(
        json.dumps(
            {
                "schema_version": PIXAI_PARENT_OVERRIDES_SCHEMA_VERSION,
                "aliases": {},
                "child_to_parents": {
                    "specific_child": ["direct_parent", "root_parent"],
                    "direct_parent": ["root_parent"],
                },
            }
        ),
        encoding="utf-8",
    )

    rules = load_pixai_parent_rules(str(rules_path), True)

    assert rules.schema_version == 1
    assert rules.child_to_direct_parents == {
        "direct_parent": frozenset({"root_parent"}),
        "specific_child": frozenset({"direct_parent"}),
    }
    assert rules.child_to_parents == {
        "direct_parent": frozenset({"root_parent"}),
        "specific_child": frozenset({"direct_parent", "root_parent"}),
    }
    assert rules.direct_relation_count == 2
    assert rules.parent_relation_count == 3


@pytest.mark.parametrize(
    ("direct_mapping", "message"),
    [
        (
            {"first": ["second"], "second": ["first"]},
            "reverse parent-rule conflict",
        ),
        (
            {
                "first": ["second"],
                "second": ["third"],
                "third": ["first"],
            },
            "parent-rule cycle detected",
        ),
    ],
)
def test_parent_rule_loader_v2_rejects_cycles(
    tmp_path,
    direct_mapping,
    message,
):
    rules_path = tmp_path / "cyclic_rules.json"
    rules_path.write_text(
        json.dumps(
            {
                "schema_version": PIXAI_PARENT_RULES_SCHEMA_VERSION,
                "aliases": {},
                "child_to_direct_parents": direct_mapping,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match=message):
        load_pixai_parent_rules(str(rules_path), True)


def test_transitive_reduction_removes_shortcut_but_preserves_diamond(tmp_path):
    graph = {
        "specific_child": {"left_parent", "right_parent", "root_parent"},
        "left_parent": {"root_parent"},
        "right_parent": {"root_parent"},
    }

    assert transitive_reduce_parent_graph(graph) == {
        "left_parent": frozenset({"root_parent"}),
        "right_parent": frozenset({"root_parent"}),
        "specific_child": frozenset({"left_parent", "right_parent"}),
    }

    rules_path = tmp_path / "unreduced_rules.json"
    rules_path.write_text(
        json.dumps(
            {
                "schema_version": PIXAI_PARENT_RULES_SCHEMA_VERSION,
                "aliases": {},
                "child_to_direct_parents": {
                    child: sorted(parents) for child, parents in graph.items()
                },
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="must be transitively reduced"):
        load_pixai_parent_rules(str(rules_path), True)


def test_generator_reads_only_general_tags_and_keeps_candidates_out_of_runtime(tmp_path):
    tags_path = tmp_path / "selected_tags.csv"
    with tags_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["name", "category"])
        writer.writeheader()
        for name in (
            "old_child",
            "canonical_child",
            "direct_parent",
            "alternate_parent",
            "broad_parent",
            "cooccurring_tag",
        ):
            writer.writerow({"name": name, "category": 0})
        writer.writerow({"name": "character_name", "category": 4})

    overrides_path = tmp_path / "overrides.json"
    overrides_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "aliases": {"old_child": "canonical_child"},
                "add": {
                    "canonical_child": [
                        "alternate_parent",
                        "broad_parent",
                        "direct_parent",
                    ],
                    "alternate_parent": ["broad_parent"],
                    "direct_parent": ["broad_parent"],
                },
                "remove": {},
            }
        ),
        encoding="utf-8",
    )
    implications_path = tmp_path / "implications.json"
    implications_path.write_text(
        json.dumps(
            [
                {
                    "antecedent_name": "canonical_child",
                    "consequent_name": "cooccurring_tag",
                    "status": "active",
                },
                {
                    "antecedent_name": "canonical_child",
                    "consequent_name": "broad_parent",
                    "status": "active",
                },
                {
                    "antecedent_name": "canonical_child",
                    "consequent_name": "character_name",
                    "status": "deleted",
                },
            ]
        ),
        encoding="utf-8",
    )
    output_path = tmp_path / "rules.json"
    report_path = tmp_path / "report.json"
    candidates_path = tmp_path / "candidates.json"
    script = (
        Path(__file__).resolve().parents[1]
        / "backend"
        / "scripts"
        / "generate_pixai_parent_rules.py"
    )
    command = [
        sys.executable,
        str(script),
        "--pixai-tags",
        str(tags_path),
        "--overrides",
        str(overrides_path),
        "--implications",
        str(implications_path),
        "--output",
        str(output_path),
        "--report",
        str(report_path),
        "--review-candidates",
        str(candidates_path),
    ]

    first = subprocess.run(command, check=True, capture_output=True, text=True)
    first_rules = json.loads(output_path.read_text(encoding="utf-8"))
    first_generated_at = first_rules["generated_at"]
    subprocess.run(command, check=True, capture_output=True, text=True)
    second_rules = json.loads(output_path.read_text(encoding="utf-8"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    candidates = json.loads(candidates_path.read_text(encoding="utf-8"))

    assert "PixAI general tags: 6" in first.stdout
    assert first_rules["schema_version"] == PIXAI_PARENT_RULES_SCHEMA_VERSION
    assert first_rules["general_tag_count"] == 6
    assert first_rules["aliases"] == {"old_child": "canonical_child"}
    assert "child_to_parents" not in first_rules
    assert first_rules["blocked_child_to_parents"] == {}
    assert first_rules["child_to_direct_parents"]["canonical_child"] == [
        "alternate_parent",
        "direct_parent",
    ]
    assert first_rules["child_to_direct_parents"]["alternate_parent"] == ["broad_parent"]
    assert first_rules["child_to_direct_parents"]["direct_parent"] == ["broad_parent"]
    assert report["pixai_category_counts"] == {"0": 6, "4": 1}
    assert report["implications_loaded"] == 2
    assert report["implications_ignored_non_active_or_invalid"] == 1
    assert report["input_relation_count"] == 5
    assert report["direct_relation_count"] == 4
    assert report["closure_relation_count"] == 5
    assert report["blocked_relation_count"] == 0
    assert report["removed_relation_count"] == 1
    assert candidates["candidate_count"] >= 1
    assert any(
        candidate["child"] == "canonical_child" and candidate["parent"] == "cooccurring_tag"
        for candidate in candidates["candidates"]
    )
    assert not any(
        candidate["child"] == "canonical_child" and candidate["parent"] == "broad_parent"
        for candidate in candidates["candidates"]
    )
    assert second_rules["generated_at"] == first_generated_at


def test_generator_rejects_parent_cycles(tmp_path):
    tags_path = tmp_path / "selected_tags.csv"
    tags_path.write_text("name,category\na,0\nb,0\n", encoding="utf-8")
    overrides_path = tmp_path / "overrides.json"
    overrides_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "aliases": {},
                "add": {"a": ["b"], "b": ["a"]},
                "remove": {},
            }
        ),
        encoding="utf-8",
    )
    script = (
        Path(__file__).resolve().parents[1]
        / "backend"
        / "scripts"
        / "generate_pixai_parent_rules.py"
    )

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--pixai-tags",
            str(tags_path),
            "--overrides",
            str(overrides_path),
            "--output",
            str(tmp_path / "rules.json"),
            "--report",
            str(tmp_path / "report.json"),
            "--review-candidates",
            str(tmp_path / "candidates.json"),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "parent-rule cycle detected" in result.stderr


def test_llm_review_merger_requires_exact_complete_tag_coverage(tmp_path):
    tags_path = tmp_path / "selected_tags.csv"
    tags_path.write_text(
        "name,category\nchild,0\nparent,0\nother,0\ncharacter_name,4\n",
        encoding="utf-8",
    )
    reviews_dir = tmp_path / "reviews"
    reviews_dir.mkdir()
    (reviews_dir / "batch_00.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "model": "gpt-5.6-sol",
                "range_start": 0,
                "range_end": 2,
                "reviewed_tag_count": 3,
                "reviewed_tags": ["child", "other", "parent"],
                "accepted": [
                    {
                        "child": "child",
                        "parents": ["parent"],
                        "relation_type": "strict_subtype",
                        "confidence": "high",
                        "rationale": "test",
                    }
                ],
                "aliases": [],
                "ambiguous": [],
                "notes": [],
            }
        ),
        encoding="utf-8",
    )
    overrides_path = tmp_path / "overrides.json"
    overrides_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "aliases": {},
                "add": {},
                "remove": {},
            }
        ),
        encoding="utf-8",
    )
    output_path = tmp_path / "summary.json"
    script = (
        Path(__file__).resolve().parents[1]
        / "backend"
        / "scripts"
        / "merge_pixai_parent_llm_reviews.py"
    )

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--pixai-tags",
            str(tags_path),
            "--reviews-dir",
            str(reviews_dir),
            "--overrides",
            str(overrides_path),
            "--output",
            str(output_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    summary = json.loads(output_path.read_text(encoding="utf-8"))

    assert "Coverage complete: True" in result.stdout
    assert summary["reviewed_tag_count"] == 3
    assert summary["coverage_complete"] is True
    assert summary["accepted_relation_count"] == 1


def test_llm_validation_finalizer_promotes_only_second_pass_accepts(tmp_path):
    reviews_dir = tmp_path / "reviews"
    validations_dir = tmp_path / "validations"
    reviews_dir.mkdir()
    validations_dir.mkdir()
    (reviews_dir / "batch_00.json").write_text(
        json.dumps(
            {
                "accepted": [
                    {
                        "child": "manual_child",
                        "parents": ["broad_parent", "rejected_parent"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (validations_dir / "batch_00.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "model": "gpt-5.6-sol",
                "source_batch": "batch_00.json",
                "reviewed_relation_count": 2,
                "decisions": [
                    {
                        "child": "manual_child",
                        "parent": "broad_parent",
                        "decision": "accept",
                        "rationale": "strict subtype",
                    },
                    {
                        "child": "manual_child",
                        "parent": "rejected_parent",
                        "decision": "reject",
                        "rationale": "different semantic dimension",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    overrides_path = tmp_path / "overrides.json"
    overrides_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "aliases": {"old_name": "new_name"},
                "add": {
                    "manual_child": ["manual_parent", "rejected_parent"],
                    "manual_parent": ["broad_parent"],
                },
                "remove": {"blocked_child": ["blocked_parent"]},
            }
        ),
        encoding="utf-8",
    )
    proposed_path = tmp_path / "proposed.json"
    report_path = tmp_path / "report.json"
    script = (
        Path(__file__).resolve().parents[1]
        / "backend"
        / "scripts"
        / "finalize_pixai_parent_llm_validations.py"
    )

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--reviews-dir",
            str(reviews_dir),
            "--validations-dir",
            str(validations_dir),
            "--overrides",
            str(overrides_path),
            "--proposed-overrides",
            str(proposed_path),
            "--report",
            str(report_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    proposed = json.loads(proposed_path.read_text(encoding="utf-8"))
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert "Promoted LLM relations: 1" in result.stdout
    assert proposed["aliases"] == {"old_name": "new_name"}
    assert proposed["add"] == {"manual_child": ["broad_parent"]}
    assert proposed["remove"] == {
        "blocked_child": ["blocked_parent"],
        "manual_child": ["rejected_parent"],
    }
    assert report["second_pass_counts"] == {
        "accept": 1,
        "ambiguous": 0,
        "reject": 1,
    }
    assert report["non_accept_relation_count"] == 1
    assert report["discarded_existing_non_accept_count"] == 3
    assert report["discarded_existing_non_accept"] == [
        {"child": "manual_child", "parent": "manual_parent"},
        {"child": "manual_child", "parent": "rejected_parent"},
        {"child": "manual_parent", "parent": "broad_parent"},
    ]
    assert report["proposed_unreduced_relation_count"] == 1
    assert report["proposed_reduced_relation_count"] == 1
    assert report["proposed_direct_relation_count"] == 1
    assert report["proposed_removed_relation_count"] == 0
