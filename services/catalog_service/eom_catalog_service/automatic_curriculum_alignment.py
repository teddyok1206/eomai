"""Bounded, deterministic Graph-RAG policy for automatic Item curriculum alignment."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from eom_identifiers import content_sha256
from sqlalchemy import select
from sqlalchemy.orm import Session

from eom_catalog_service.knowledge_graph_models import (
    CurriculumUnitRecord,
    KnowledgeEdgeRecord,
    KnowledgeNodeRecord,
)

AUTOMATIC_ITEM_ALIGNMENT_POLICY_VERSION = "integrated-science-auto-alignment/1.0"
AUTOMATIC_ITEM_ALIGNMENT_MAX_DEPTH = 3
AUTOMATIC_ITEM_ALIGNMENT_MAX_UNITS = 8
AUTOMATIC_ITEM_ALIGNMENT_MAX_ASSOCIATIONS = 32768
AUTOMATIC_ITEM_ALIGNMENT_SOURCE_CLASSES = ("CURRICULUM", "TEXTBOOK")
AUTOMATIC_ITEM_ALIGNMENT_PERMISSION_KEYS = (
    "knowledge_graph:read",
    "knowledge_graph:retrieve",
)
AUTOMATIC_ITEM_ALIGNMENT_EVIDENCE_BUDGET = {
    "max_documents": 8,
    "max_item_revisions": 0,
    "max_graph_nodes": 64,
    "max_claims": 16,
    "max_context_tokens": 8000,
}
AUTOMATIC_ITEM_ALIGNMENT_POLICY = {
    "schema_version": AUTOMATIC_ITEM_ALIGNMENT_POLICY_VERSION,
    "graph_walk": "UNDIRECTED_SHORTEST_PATH",
    "maximum_depth": AUTOMATIC_ITEM_ALIGNMENT_MAX_DEPTH,
    "target_unit_level": "MINOR",
    "ranking": ["DESCENDING_EVIDENCE_SUPPORT", "ASCENDING_DISTANCE_SUM", "UNIT_ID"],
    "maximum_units": AUTOMATIC_ITEM_ALIGNMENT_MAX_UNITS,
    "maximum_node_seed_associations": AUTOMATIC_ITEM_ALIGNMENT_MAX_ASSOCIATIONS,
    "retrieval": {
        "query_kind": "ITEM_PREPARATION",
        "topic_selection": (
            "SORTED_UNIQUE_CONCEPTUAL_STABLE_KEYS_FIRST_20_ELSE_"
            "ITEM_ELEMENT_OR_ASSESSMENT_PATTERN_FIRST_20_ELSE_ITEM_REVISION_FIRST_20"
        ),
        "source_classes": list(AUTOMATIC_ITEM_ALIGNMENT_SOURCE_CLASSES),
        "requester_role": "ADMIN",
        "requester_permission_keys": list(AUTOMATIC_ITEM_ALIGNMENT_PERMISSION_KEYS),
        "evidence_budget": AUTOMATIC_ITEM_ALIGNMENT_EVIDENCE_BUDGET,
    },
}
AUTOMATIC_ITEM_ALIGNMENT_POLICY_SHA256 = content_sha256(AUTOMATIC_ITEM_ALIGNMENT_POLICY)
_ITEM_NODE_TYPES = frozenset({"ITEM_REVISION", "ITEM_ELEMENT", "ASSESSMENT_PATTERN"})
_FALLBACK_TOPIC_NODE_TYPES = frozenset({"ITEM_ELEMENT", "ASSESSMENT_PATTERN"})
_LAST_RESORT_TOPIC_NODE_TYPES = frozenset({"ITEM_REVISION"})


class AutomaticCurriculumAlignmentError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def automatic_item_alignment_topic_keys(
    nodes: Iterable[tuple[str, str]],
) -> tuple[str, ...]:
    """Select the bounded controlled-topic keys declared by one accepted proposal."""

    materialized = tuple(nodes)
    primary = {
        stable_key
        for node_type, stable_key in materialized
        if node_type not in _ITEM_NODE_TYPES and len(stable_key) <= 128
    }
    fallback = {
        stable_key
        for node_type, stable_key in materialized
        if node_type in _FALLBACK_TOPIC_NODE_TYPES and len(stable_key) <= 128
    }
    last_resort = {
        stable_key
        for node_type, stable_key in materialized
        if node_type in _LAST_RESORT_TOPIC_NODE_TYPES and len(stable_key) <= 128
    }
    values = tuple(sorted(primary or fallback or last_resort))[:20]
    if not values:
        raise AutomaticCurriculumAlignmentError(
            "AUTOMATIC_ALIGNMENT_TOPIC_MISSING",
            "accepted Item analysis has no controlled topic key eligible for Graph retrieval",
        )
    return values


def derive_automatic_item_curriculum_unit_ids(
    session: Session,
    *,
    graph_snapshot_revision_id: str,
    evidence_node_ids: tuple[str, ...],
) -> tuple[str, ...]:
    """Rank MINOR units over one bounded multi-source, three-hop graph traversal."""

    seeds = tuple(sorted(set(evidence_node_ids)))
    if not seeds or seeds != evidence_node_ids or len(seeds) > 64:
        raise AutomaticCurriculumAlignmentError(
            "AUTOMATIC_ALIGNMENT_EVIDENCE_INVALID",
            "automatic alignment evidence node IDs must be sorted, unique, and bounded",
        )
    existing_nodes = set(
        session.scalars(
            select(KnowledgeNodeRecord.node_id).where(
                KnowledgeNodeRecord.graph_snapshot_revision_id == graph_snapshot_revision_id,
                KnowledgeNodeRecord.node_id.in_(seeds),
            )
        )
    )
    if existing_nodes != set(seeds):
        raise AutomaticCurriculumAlignmentError(
            "AUTOMATIC_ALIGNMENT_EVIDENCE_INVALID",
            "automatic alignment evidence nodes do not resolve in the pinned snapshot",
        )

    reached_by: dict[str, set[str]] = {node_id: {node_id} for node_id in seeds}
    frontier: dict[str, set[str]] = {node_id: {node_id} for node_id in seeds}
    unit_distances: dict[str, dict[str, int]] = defaultdict(dict)
    association_count = len(seeds)

    for depth in range(AUTOMATIC_ITEM_ALIGNMENT_MAX_DEPTH + 1):
        frontier_node_ids = tuple(sorted(frontier))
        if not frontier_node_ids:
            break
        units = tuple(
            session.scalars(
                select(CurriculumUnitRecord)
                .where(
                    CurriculumUnitRecord.graph_snapshot_revision_id == graph_snapshot_revision_id,
                    CurriculumUnitRecord.unit_level == "MINOR",
                    CurriculumUnitRecord.node_id.in_(frontier_node_ids),
                )
                .order_by(CurriculumUnitRecord.curriculum_unit_id)
            )
        )
        for unit in units:
            distances = unit_distances[unit.curriculum_unit_id]
            for seed in frontier[unit.node_id]:
                distances.setdefault(seed, depth)
        if depth == AUTOMATIC_ITEM_ALIGNMENT_MAX_DEPTH:
            break

        rows = tuple(
            session.execute(
                select(KnowledgeEdgeRecord.from_node_id, KnowledgeEdgeRecord.to_node_id)
                .where(
                    KnowledgeEdgeRecord.graph_snapshot_revision_id == graph_snapshot_revision_id,
                    (
                        KnowledgeEdgeRecord.from_node_id.in_(frontier_node_ids)
                        | KnowledgeEdgeRecord.to_node_id.in_(frontier_node_ids)
                    ),
                )
                .order_by(KnowledgeEdgeRecord.edge_id)
                .limit(AUTOMATIC_ITEM_ALIGNMENT_MAX_ASSOCIATIONS + 1)
            )
        )
        if len(rows) > AUTOMATIC_ITEM_ALIGNMENT_MAX_ASSOCIATIONS:
            raise AutomaticCurriculumAlignmentError(
                "AUTOMATIC_ALIGNMENT_NEIGHBORHOOD_TOO_LARGE",
                "automatic alignment graph neighborhood exceeds the policy bound",
            )
        next_frontier: dict[str, set[str]] = defaultdict(set)
        for from_node_id, to_node_id in rows:
            for node_id, neighbor_id in (
                (from_node_id, to_node_id),
                (to_node_id, from_node_id),
            ):
                source_seeds = frontier.get(node_id)
                if source_seeds is None:
                    continue
                unseen = source_seeds.difference(reached_by.get(neighbor_id, set()))
                if unseen:
                    next_frontier[neighbor_id].update(unseen)
        for node_id, source_seeds in next_frontier.items():
            reached_by.setdefault(node_id, set()).update(source_seeds)
            association_count += len(source_seeds)
        if association_count > AUTOMATIC_ITEM_ALIGNMENT_MAX_ASSOCIATIONS:
            raise AutomaticCurriculumAlignmentError(
                "AUTOMATIC_ALIGNMENT_NEIGHBORHOOD_TOO_LARGE",
                "automatic alignment node-to-evidence associations exceed the policy bound",
            )
        frontier = dict(next_frontier)

    if not unit_distances:
        raise AutomaticCurriculumAlignmentError(
            "AUTOMATIC_ALIGNMENT_TARGET_MISSING",
            "no MINOR curriculum unit is reachable from the pinned Graph-RAG evidence",
        )
    ranked = sorted(
        unit_distances,
        key=lambda unit_id: (
            -len(unit_distances[unit_id]),
            sum(unit_distances[unit_id].values()),
            unit_id,
        ),
    )
    return tuple(sorted(ranked[:AUTOMATIC_ITEM_ALIGNMENT_MAX_UNITS]))
