from __future__ import annotations

import json
import re
import warnings
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TypeVar

PIXAI_PARENT_RULES_SCHEMA_VERSION = 2
PIXAI_PARENT_OVERRIDES_SCHEMA_VERSION = 1
LEGACY_PIXAI_PARENT_RULES_SCHEMA_VERSION = 1
DEFAULT_PIXAI_PARENT_RULES_PATH = (
    Path(__file__).resolve().parent / "resources" / "pixai_parent_rules.json"
)

Score = TypeVar("Score")


@dataclass(frozen=True)
class PixAIParentRuleSet:
    schema_version: int
    pixai_model: str
    general_tag_count: int
    aliases: dict[str, str]
    child_to_direct_parents: dict[str, frozenset[str]]
    blocked_child_to_parents: dict[str, frozenset[str]]
    child_to_parents: dict[str, frozenset[str]]
    source: str

    @property
    def direct_relation_count(self) -> int:
        return sum(len(parents) for parents in self.child_to_direct_parents.values())

    @property
    def parent_relation_count(self) -> int:
        return sum(len(parents) for parents in self.child_to_parents.values())

    @property
    def blocked_relation_count(self) -> int:
        return sum(len(parents) for parents in self.blocked_child_to_parents.values())

    @property
    def relation_count(self) -> int:
        return self.parent_relation_count


def normalize_parent_tag(tag: object) -> str:
    normalized = str(tag).strip().strip(",").casefold().replace(" ", "_")
    return re.sub(r"_+", "_", normalized).strip("_")


def canonicalize_parent_tag(tag: str, aliases: Mapping[str, str]) -> str:
    current = normalize_parent_tag(tag)
    seen: set[str] = set()
    while current in aliases:
        if current in seen:
            raise ValueError(f"alias cycle detected at {current!r}")
        seen.add(current)
        current = aliases[current]
    return current


def _empty_rule_set(source: str) -> PixAIParentRuleSet:
    return PixAIParentRuleSet(
        schema_version=PIXAI_PARENT_RULES_SCHEMA_VERSION,
        pixai_model="pixai-tagger-v0.9",
        general_tag_count=0,
        aliases={},
        child_to_direct_parents={},
        blocked_child_to_parents={},
        child_to_parents={},
        source=source,
    )


def _validate_string_mapping(payload: object, field_name: str) -> dict[str, str]:
    if not isinstance(payload, dict):
        raise TypeError(f"{field_name} must be a JSON object")
    result: dict[str, str] = {}
    for raw_left, raw_right in payload.items():
        left = normalize_parent_tag(raw_left)
        right = normalize_parent_tag(raw_right)
        if not left or not right or left == right:
            raise ValueError(f"invalid {field_name} entry: {raw_left!r} -> {raw_right!r}")
        result[left] = right
    for alias in result:
        canonicalize_parent_tag(alias, result)
    return result


def _validate_parent_mapping(
    payload: object,
    field_name: str,
) -> dict[str, frozenset[str]]:
    if not isinstance(payload, dict):
        raise TypeError(f"{field_name} must be a JSON object")
    result: dict[str, frozenset[str]] = {}
    for raw_child, raw_parents in payload.items():
        child = normalize_parent_tag(raw_child)
        if not child or not isinstance(raw_parents, list):
            raise ValueError(f"invalid {field_name} rule for {raw_child!r}")
        parents = {
            normalize_parent_tag(parent) for parent in raw_parents if normalize_parent_tag(parent)
        }
        if child in parents:
            raise ValueError(f"parent rule contains a self-cycle for {child!r}")
        if parents:
            result[child] = frozenset(parents)
    return result


def _canonicalize_parent_graph(
    graph: Mapping[str, Collection[str]],
    aliases: Mapping[str, str],
) -> dict[str, frozenset[str]]:
    canonicalized: dict[str, set[str]] = {}
    for raw_child, raw_parents in graph.items():
        child = canonicalize_parent_tag(raw_child, aliases)
        parents = {
            canonicalize_parent_tag(parent, aliases) for parent in raw_parents
        }
        if child in parents:
            raise ValueError(
                f"alias canonicalization creates a parent self-cycle for {child!r}"
            )
        if parents:
            canonicalized.setdefault(child, set()).update(parents)
    return {
        child: frozenset(parents)
        for child, parents in sorted(canonicalized.items())
    }


def _validate_parent_dag(graph: Mapping[str, Collection[str]]) -> None:
    for child, parents in graph.items():
        for parent in parents:
            if child in graph.get(parent, ()):
                raise ValueError(
                    "parent-rule cycle detected (reverse parent-rule conflict): "
                    f"{child!r} -> {parent!r} and {parent!r} -> {child!r}"
                )

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str, trail: list[str]) -> None:
        if node in visiting:
            cycle_start = trail.index(node)
            cycle = trail[cycle_start:]
            raise ValueError(f"parent-rule cycle detected: {' -> '.join(cycle)}")
        if node in visited:
            return
        visiting.add(node)
        for parent in sorted(graph.get(node, ())):
            visit(parent, [*trail, parent])
        visiting.remove(node)
        visited.add(node)

    for node in sorted(graph):
        visit(node, [node])


def transitive_parent_closure(
    graph: Mapping[str, Collection[str]],
) -> dict[str, frozenset[str]]:
    _validate_parent_dag(graph)
    cache: dict[str, frozenset[str]] = {}

    def ancestors(node: str) -> frozenset[str]:
        if node in cache:
            return cache[node]
        result: set[str] = set()
        for parent in graph.get(node, ()):
            result.add(parent)
            result.update(ancestors(parent))
        cache[node] = frozenset(result)
        return cache[node]

    return {child: ancestors(child) for child in sorted(graph) if ancestors(child)}


def transitive_reduce_parent_graph(
    graph: Mapping[str, Collection[str]],
) -> dict[str, frozenset[str]]:
    closure = transitive_parent_closure(graph)
    reduced: dict[str, frozenset[str]] = {}
    for child in sorted(graph):
        parents = set(graph.get(child, ()))
        necessary = {
            parent
            for parent in parents
            if not any(
                parent in closure.get(other_parent, ())
                for other_parent in parents
                if other_parent != parent
            )
        }
        if necessary:
            reduced[child] = frozenset(necessary)
    return reduced


@lru_cache(maxsize=8)
def load_pixai_parent_rules(
    path: str = "",
    strict: bool = False,
) -> PixAIParentRuleSet:
    source = Path(path).expanduser().resolve() if path else DEFAULT_PIXAI_PARENT_RULES_PATH
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise TypeError("PixAI parent rule file must contain a JSON object")
        schema_version = int(payload.get("schema_version", -1))
        if schema_version not in {
            LEGACY_PIXAI_PARENT_RULES_SCHEMA_VERSION,
            PIXAI_PARENT_RULES_SCHEMA_VERSION,
        }:
            raise ValueError(
                f"unsupported PixAI parent rule schema {schema_version}; "
                "expected "
                f"{LEGACY_PIXAI_PARENT_RULES_SCHEMA_VERSION} or "
                f"{PIXAI_PARENT_RULES_SCHEMA_VERSION}"
            )
        aliases = _validate_string_mapping(payload.get("aliases", {}), "aliases")
        if schema_version == PIXAI_PARENT_RULES_SCHEMA_VERSION:
            if "child_to_parents" in payload:
                raise ValueError(
                    "schema 2 must store only child_to_direct_parents, not child_to_parents"
                )
            child_to_direct_parents = _validate_parent_mapping(
                payload.get("child_to_direct_parents", {}),
                "child_to_direct_parents",
            )
            child_to_direct_parents = _canonicalize_parent_graph(
                child_to_direct_parents,
                aliases,
            )
            blocked_child_to_parents = _validate_parent_mapping(
                payload.get("blocked_child_to_parents", {}),
                "blocked_child_to_parents",
            )
            blocked_child_to_parents = _canonicalize_parent_graph(
                blocked_child_to_parents,
                aliases,
            )
            reduced = transitive_reduce_parent_graph(child_to_direct_parents)
            if reduced != child_to_direct_parents:
                redundant = sorted(
                    (child, parent)
                    for child, parents in child_to_direct_parents.items()
                    for parent in parents - reduced.get(child, frozenset())
                )
                raise ValueError(
                    "schema 2 child_to_direct_parents must be transitively reduced; "
                    f"redundant relations: {redundant[:5]}"
                )
            blocked_direct = sorted(
                (child, parent)
                for child, parents in child_to_direct_parents.items()
                for parent in parents & blocked_child_to_parents.get(child, frozenset())
            )
            if blocked_direct:
                raise ValueError(
                    "schema 2 contains directly blocked parent relations: "
                    f"{blocked_direct[:5]}"
                )
        else:
            legacy_relations = _validate_parent_mapping(
                payload.get("child_to_parents", {}),
                "child_to_parents",
            )
            legacy_relations = _canonicalize_parent_graph(
                legacy_relations,
                aliases,
            )
            child_to_direct_parents = transitive_reduce_parent_graph(legacy_relations)
            blocked_child_to_parents = {}
        unfiltered_parents = transitive_parent_closure(child_to_direct_parents)
        child_to_parents = {
            child: frozenset(
                parents - blocked_child_to_parents.get(child, frozenset())
            )
            for child, parents in unfiltered_parents.items()
            if parents - blocked_child_to_parents.get(child, frozenset())
        }
        return PixAIParentRuleSet(
            schema_version=schema_version,
            pixai_model=str(payload.get("pixai_model", "pixai-tagger-v0.9")),
            general_tag_count=int(payload.get("general_tag_count", 0)),
            aliases=aliases,
            child_to_direct_parents=child_to_direct_parents,
            blocked_child_to_parents=blocked_child_to_parents,
            child_to_parents=child_to_parents,
            source=str(source),
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        if strict:
            raise RuntimeError(f"failed to load PixAI parent rules from {source}: {exc}") from exc
        warnings.warn(
            f"PixAI parent rules unavailable at {source}; continuing without parent "
            f"tag cleanup: {exc}",
            RuntimeWarning,
            stacklevel=2,
        )
        return _empty_rule_set(str(source))


def redundant_parent_removals(
    present_tags: Collection[str],
    parent_rules: Mapping[str, Collection[str]],
) -> dict[str, str]:
    present = set(present_tags)
    removals: dict[str, str] = {}
    for child in sorted(present):
        for parent in sorted(parent_rules.get(child, ())):
            if parent in present and parent != child:
                removals.setdefault(parent, child)
    return removals


def _canonicalize_list(tags: list[str], aliases: Mapping[str, str]) -> list[str]:
    canonicalized: list[str] = []
    seen: set[str] = set()
    for raw_tag in tags:
        tag = canonicalize_parent_tag(raw_tag, aliases)
        if tag and tag not in seen:
            canonicalized.append(tag)
            seen.add(tag)
    return canonicalized


def _canonicalize_mapping(
    tags: Mapping[str, Score],
    aliases: Mapping[str, str],
) -> dict[str, Score]:
    canonicalized: dict[str, Score] = {}
    for raw_tag, score in tags.items():
        tag = canonicalize_parent_tag(raw_tag, aliases)
        if not tag:
            continue
        if tag not in canonicalized:
            canonicalized[tag] = score
            continue
        try:
            canonicalized[tag] = max(canonicalized[tag], score)
        except TypeError:
            continue
    return canonicalized


def remove_redundant_parent_tags(
    tags: list[str] | Mapping[str, Score],
    parent_rules: Mapping[str, Collection[str]],
    aliases: Mapping[str, str] | None = None,
) -> list[str] | dict[str, Score]:
    alias_map = aliases or {}
    if isinstance(tags, list):
        canonicalized = _canonicalize_list(tags, alias_map)
        removals = redundant_parent_removals(canonicalized, parent_rules)
        return [tag for tag in canonicalized if tag not in removals]
    if isinstance(tags, Mapping):
        canonicalized_mapping = _canonicalize_mapping(tags, alias_map)
        removals = redundant_parent_removals(canonicalized_mapping, parent_rules)
        return {tag: score for tag, score in canonicalized_mapping.items() if tag not in removals}
    raise TypeError("tags must be a list or mapping")
