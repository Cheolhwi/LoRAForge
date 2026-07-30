from __future__ import annotations

import numpy as np
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import pdist

from .types import Cluster, ImageRecord


def complete_linkage_clusters(
    records: list[ImageRecord], similarity_threshold: float
) -> list[Cluster]:
    if not records:
        return []
    if len(records) == 1:
        cluster = Cluster(0, records)
        _set_medoid_and_backups(cluster)
        return [cluster]
    embeddings = np.stack([record.embedding for record in records])
    distances = pdist(embeddings, metric="cosine")
    tree = linkage(distances, method="complete")
    labels = fcluster(tree, t=1.0 - similarity_threshold, criterion="distance")
    grouped: dict[int, list[ImageRecord]] = {}
    for label, record in zip(labels, records):
        grouped.setdefault(int(label), []).append(record)
    clusters: list[Cluster] = []
    for cluster_id, members in enumerate(sorted(grouped.values(), key=lambda group: min(str(x.path) for x in group))):
        cluster = Cluster(cluster_id, members)
        _set_medoid_and_backups(cluster)
        clusters.append(cluster)
    return clusters


def _set_medoid_and_backups(cluster: Cluster) -> None:
    embeddings = np.stack([record.embedding for record in cluster.members])
    similarities = embeddings @ embeddings.T
    medoid_index = int(np.argmax(similarities.sum(axis=1)))
    cluster.medoid = cluster.members[medoid_index]
    member_index = {id(record): index for index, record in enumerate(cluster.members)}
    cluster.backup_candidates = sorted(
        [record for index, record in enumerate(cluster.members) if index != medoid_index],
        key=lambda record: (-float(similarities[medoid_index, member_index[id(record)]]), str(record.path)),
    )
