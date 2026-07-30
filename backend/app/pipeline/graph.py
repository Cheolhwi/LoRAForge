from __future__ import annotations

from collections import deque

import numpy as np


def cosine_matrix(vectors: np.ndarray) -> np.ndarray:
    vectors = vectors / np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-12)
    return vectors @ vectors.T


def build_mutual_topk_graph(embeddings: np.ndarray, top_k: int, min_similarity: float) -> dict[int, set[int]]:
    count = len(embeddings)
    graph = {index: set() for index in range(count)}
    if count < 2:
        return graph
    similarities = cosine_matrix(embeddings)
    top_lists: list[set[int]] = []
    for index in range(count):
        order = np.argsort(-similarities[index])
        candidates = [int(candidate) for candidate in order if int(candidate) != index]
        top_lists.append(set(candidates[:top_k]))
    for left in range(count):
        for right in top_lists[left]:
            if left in top_lists[int(right)] and similarities[left, right] >= min_similarity:
                graph[left].add(right)
                graph[right].add(left)
    return graph


def iterative_k_core(graph: dict[int, set[int]], degree: int) -> dict[int, set[int]]:
    active = set(graph)
    changed = True
    while changed:
        changed = False
        remove = {node for node in active if len(graph[node] & active) < degree}
        if remove:
            active -= remove
            changed = True
    return {node: (graph[node] & active) for node in active}


def connected_components(graph: dict[int, set[int]]) -> list[set[int]]:
    remaining = set(graph)
    components: list[set[int]] = []
    while remaining:
        start = remaining.pop()
        component = {start}
        queue = deque([start])
        while queue:
            node = queue.popleft()
            for neighbor in graph[node] & remaining:
                remaining.remove(neighbor)
                component.add(neighbor)
                queue.append(neighbor)
        components.append(component)
    return sorted(components, key=lambda component: (-len(component), min(component)))
