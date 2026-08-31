"""Pure deterministic construction of immutable Education Graph projections."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from eom_catalog_contracts import (
    ApprovedItemKnowledgeSourceV2,
    CurriculumUnitBinding,
    EducationalDocumentKnowledgeSourceV3,
    EducationalDocumentKnowledgeSourceV4,
    ItemElementBinding,
    KnowledgeAnalysisSourceV3,
    KnowledgeAnalysisWorkerProposal,
    KnowledgeAnalysisWorkerProposalV2,
    KnowledgeAnalysisWorkerProposalV3,
    KnowledgeAnalysisWorkerProposalV4,
    KnowledgeArtifactMemberPointer,
    KnowledgeGraphStructureManifest,
    KnowledgeGraphStructureManifestV2,
    KnowledgeNodeType,
    ProposedKnowledgeEdgeV2,
    validate_knowledge_edge_endpoint_types,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes

_LEXICAL_TOKEN = re.compile(r"[0-9A-Za-z가-힣]+")
_MAX_NODE_ALIASES = 256
_CURRICULUM_ALIGNED_NODE_TYPES = frozenset(
    {
        KnowledgeNodeType.CONCEPT,
        KnowledgeNodeType.CLAIM,
        KnowledgeNodeType.PROCESS,
        KnowledgeNodeType.OBSERVABLE_PROPERTY,
        KnowledgeNodeType.FORMULA,
    }
)


def knowledge_node_terms(stable_key: str, label: str) -> tuple[str, ...]:
    """Return the deterministic bounded lexical keys stored with one immutable node."""

    return tuple(
        sorted(
            {
                token
                for token in _LEXICAL_TOKEN.findall(f"{stable_key} {label}".casefold())
                if 2 <= len(token) <= 128
            }
        )
    )


class KnowledgeGraphProjectionError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, order=True)
class GraphSourcePointer:
    analysis_run_id: str
    source_kind: str
    source_class: str
    source_revision_id: str
    source_artifact_id: str
    source_artifact_revision_id: str
    source_sha256: str
    member_path: str
    anchor_id: str
    anchor_kind: str
    locator: str
    excerpt_sha256: str

    def document(self) -> dict[str, Any]:
        return {
            "analysis_run_id": self.analysis_run_id,
            "source_kind": self.source_kind,
            "source_class": self.source_class,
            "source_revision_id": self.source_revision_id,
            "source_artifact_id": self.source_artifact_id,
            "source_artifact_revision_id": self.source_artifact_revision_id,
            "source_sha256": self.source_sha256,
            "member_path": self.member_path,
            "anchor_id": self.anchor_id,
            "anchor_kind": self.anchor_kind,
            "locator": self.locator,
            "excerpt_sha256": self.excerpt_sha256,
        }


@dataclass(frozen=True)
class AcceptedAnalysisProposal:
    analysis_run_id: str
    source: KnowledgeAnalysisSourceV3 | EducationalDocumentKnowledgeSourceV4
    accepted_result: KnowledgeArtifactMemberPointer
    proposal: (
        KnowledgeAnalysisWorkerProposal
        | KnowledgeAnalysisWorkerProposalV2
        | KnowledgeAnalysisWorkerProposalV3
        | KnowledgeAnalysisWorkerProposalV4
    )


def _proposal_edge_type(edge: object) -> str:
    if isinstance(edge, ProposedKnowledgeEdgeV2):
        return str(edge.relationship.edge_type)
    edge_type = getattr(edge, "edge_type", None)
    if not isinstance(edge_type, str):
        raise KnowledgeGraphProjectionError(
            "KNOWLEDGE_GRAPH_EDGE_INCOMPATIBLE",
            "knowledge graph edge type is unavailable",
        )
    return edge_type


@dataclass(frozen=True)
class ProjectedKnowledgeNode:
    node_id: str
    node_type: str
    stable_key: str
    label: str
    aliases: tuple[str, ...]
    answer_bearing: bool
    source_pointers: tuple[GraphSourcePointer, ...]

    def document(self, *, include_aliases: bool = False) -> dict[str, Any]:
        document = {
            "node_id": self.node_id,
            "node_type": self.node_type,
            "stable_key": self.stable_key,
            "label": self.label,
            "answer_bearing": self.answer_bearing,
            "source_pointers": [item.document() for item in self.source_pointers],
        }
        if include_aliases:
            document["aliases"] = list(self.aliases)
        return document


@dataclass(frozen=True)
class ProjectedKnowledgeEdge:
    edge_id: str
    edge_type: str
    from_node_id: str
    to_node_id: str
    confidence_milli: int
    answer_bearing: bool
    source_pointers: tuple[GraphSourcePointer, ...]

    def document(self) -> dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "edge_type": self.edge_type,
            "from_node_id": self.from_node_id,
            "to_node_id": self.to_node_id,
            "confidence_milli": self.confidence_milli,
            "answer_bearing": self.answer_bearing,
            "source_pointers": [item.document() for item in self.source_pointers],
        }


@dataclass(frozen=True, order=True)
class CurriculumClosure:
    framework_revision_id: str
    ancestor_unit_id: str
    descendant_unit_id: str
    depth: int

    def document(self) -> dict[str, Any]:
        return {
            "framework_revision_id": self.framework_revision_id,
            "ancestor_unit_id": self.ancestor_unit_id,
            "descendant_unit_id": self.descendant_unit_id,
            "depth": self.depth,
        }


@dataclass(frozen=True)
class EducationGraphProjection:
    analyses: tuple[AcceptedAnalysisProposal, ...]
    nodes: tuple[ProjectedKnowledgeNode, ...]
    edges: tuple[ProjectedKnowledgeEdge, ...]
    curriculum_units: tuple[CurriculumUnitBinding, ...]
    curriculum_closure: tuple[CurriculumClosure, ...]
    item_elements: tuple[ItemElementBinding, ...]
    anchor_count: int
    projection_schema_version: str


@dataclass(frozen=True)
class EducationGraphProjectionFiles:
    members: dict[str, bytes]
    metadata: dict[str, dict[str, str]]
    snapshot_sha256: str


@dataclass
class _NodeAccumulator:
    node_id: str
    node_type: str
    stable_key: str
    label_counts: dict[str, int]
    reviewed_label: str | None
    source_pointers: set[GraphSourcePointer]

    def add_label(self, label: str, *, reviewed: bool = False) -> None:
        self.label_counts[label] = self.label_counts.get(label, 0) + 1
        if reviewed:
            self.reviewed_label = label

    def preferred_label(self) -> str:
        if self.reviewed_label is not None:
            return self.reviewed_label
        return min(
            self.label_counts,
            key=lambda label: (
                -int(bool(re.search(r"[가-힣]", label))),
                -self.label_counts[label],
                label,
            ),
        )

    def aliases(self) -> tuple[str, ...]:
        preferred = self.preferred_label()
        return tuple(sorted(label for label in self.label_counts if label != preferred))


@dataclass
class _EdgeAccumulator:
    edge_id: str
    edge_type: str
    from_node_id: str
    to_node_id: str
    confidence_milli: int
    source_pointers: set[GraphSourcePointer]


def _stable_id(prefix: str, value: dict[str, object]) -> str:
    digest = content_sha256(value).removeprefix("sha256:")[:32]
    return f"{prefix}{digest}"


def _source_revision_id(
    source: KnowledgeAnalysisSourceV3 | EducationalDocumentKnowledgeSourceV4,
) -> str:
    if isinstance(source, ApprovedItemKnowledgeSourceV2):
        return source.item_revision_id
    if isinstance(
        source, (EducationalDocumentKnowledgeSourceV3, EducationalDocumentKnowledgeSourceV4)
    ):
        return source.document_revision_id
    return source.source_file_id


def _validate_document_page_coverage(analyses: tuple[AcceptedAnalysisProposal, ...]) -> None:
    """Reject page overlap within one immutable Document Revision publication source set.

    Historical runs remain immutable and may overlap in storage, but one canonical snapshot may
    select at most one accepted observation for a physical page.  Sorting each sparse adjacency
    bucket gives O(n log n) validation without a quadratic pairwise scan.
    """

    by_revision: dict[str, list[tuple[int, int, str]]] = {}
    for analysis in analyses:
        source = analysis.source
        if not isinstance(
            source, EducationalDocumentKnowledgeSourceV3 | EducationalDocumentKnowledgeSourceV4
        ):
            continue
        by_revision.setdefault(source.document_revision_id, []).append(
            (source.first_physical_page, source.last_physical_page, analysis.analysis_run_id)
        )
    for ranges in by_revision.values():
        previous: tuple[int, int, str] | None = None
        for current in sorted(ranges):
            if previous is not None and current[0] <= previous[1]:
                raise KnowledgeGraphProjectionError(
                    "KNOWLEDGE_GRAPH_DOCUMENT_PAGE_OVERLAP",
                    "one graph snapshot cannot select the same document page more than once",
                )
            previous = current


def _source_pointer(
    analysis: AcceptedAnalysisProposal,
    anchor_id: str,
) -> GraphSourcePointer:
    anchors = {item.anchor_id: item for item in analysis.proposal.anchors}
    anchor = anchors[anchor_id]
    member = analysis.source.artifact_member
    return GraphSourcePointer(
        analysis_run_id=analysis.analysis_run_id,
        source_kind=analysis.source.source_kind,
        source_class=analysis.source.source_class,
        source_revision_id=_source_revision_id(analysis.source),
        source_artifact_id=member.artifact_id,
        source_artifact_revision_id=member.artifact_revision_id,
        source_sha256=member.sha256,
        member_path=anchor.member_path,
        anchor_id=anchor.anchor_id,
        anchor_kind=anchor.anchor_kind,
        locator=anchor.locator,
        excerpt_sha256=anchor.excerpt_sha256,
    )


def _curriculum_closure(
    units: tuple[CurriculumUnitBinding, ...],
) -> tuple[CurriculumClosure, ...]:
    by_key = {(item.framework_revision_id, item.curriculum_unit_id): item for item in units}
    closure: set[CurriculumClosure] = set()
    for unit in units:
        closure.add(
            CurriculumClosure(
                framework_revision_id=unit.framework_revision_id,
                ancestor_unit_id=unit.curriculum_unit_id,
                descendant_unit_id=unit.curriculum_unit_id,
                depth=0,
            )
        )
        current = unit
        depth = 0
        visited = {unit.curriculum_unit_id}
        while current.parent_unit_id is not None:
            if current.parent_unit_id in visited:
                raise KnowledgeGraphProjectionError(
                    "KNOWLEDGE_GRAPH_CURRICULUM_CYCLE",
                    "curriculum hierarchy contains a cycle",
                )
            visited.add(current.parent_unit_id)
            parent = by_key.get((unit.framework_revision_id, current.parent_unit_id))
            if parent is None:
                raise KnowledgeGraphProjectionError(
                    "KNOWLEDGE_GRAPH_CURRICULUM_POINTER_INVALID",
                    "curriculum parent pointer does not resolve",
                )
            depth += 1
            closure.add(
                CurriculumClosure(
                    framework_revision_id=unit.framework_revision_id,
                    ancestor_unit_id=parent.curriculum_unit_id,
                    descendant_unit_id=unit.curriculum_unit_id,
                    depth=depth,
                )
            )
            current = parent
    return tuple(sorted(closure))


def _merge_edge(
    accumulators: dict[tuple[str, str, str], _EdgeAccumulator],
    *,
    edge_type: str,
    from_node_id: str,
    to_node_id: str,
    confidence_milli: int,
    source_pointers: set[GraphSourcePointer],
) -> None:
    key = (edge_type, from_node_id, to_node_id)
    existing = accumulators.get(key)
    if existing is None:
        accumulators[key] = _EdgeAccumulator(
            edge_id=_stable_id(
                "kedge_",
                {
                    "edge_type": edge_type,
                    "from_node_id": from_node_id,
                    "to_node_id": to_node_id,
                },
            ),
            edge_type=edge_type,
            from_node_id=from_node_id,
            to_node_id=to_node_id,
            confidence_milli=confidence_milli,
            source_pointers=set(source_pointers),
        )
        return
    existing.confidence_milli = min(existing.confidence_milli, confidence_milli)
    existing.source_pointers.update(source_pointers)


def _add_reviewed_curriculum_structure(
    analyses: tuple[AcceptedAnalysisProposal, ...],
    structure: KnowledgeGraphStructureManifestV2,
    node_accumulators: dict[str, _NodeAccumulator],
    local_node_ids: dict[tuple[str, str], str],
    edge_accumulators: dict[tuple[str, str, str], _EdgeAccumulator],
) -> None:
    analysis_by_id = {analysis.analysis_run_id: analysis for analysis in analyses}
    units_by_id = {unit.curriculum_unit_id: unit for unit in structure.curriculum_units}
    bindings_by_run = {
        binding.analysis_run_id: binding for binding in structure.analysis_curriculum_bindings
    }
    expected_bound_runs = {
        analysis.analysis_run_id
        for analysis in analyses
        if isinstance(analysis.source, EducationalDocumentKnowledgeSourceV4)
        and analysis.source.curriculum_unit_keys
    }
    if set(bindings_by_run) != expected_bound_runs:
        raise KnowledgeGraphProjectionError(
            "KNOWLEDGE_GRAPH_CURRICULUM_BINDING_COVERAGE_INVALID",
            "reviewed curriculum bindings must exactly cover classified source ranges",
        )
    direct_pointers: dict[str, set[GraphSourcePointer]] = {
        unit.curriculum_unit_id: set() for unit in structure.curriculum_units
    }
    node_pointers_by_run: dict[str, dict[str, set[GraphSourcePointer]]] = {}

    for run_id, binding in bindings_by_run.items():
        analysis = analysis_by_id[run_id]
        source = analysis.source
        if not isinstance(source, EducationalDocumentKnowledgeSourceV4):
            raise KnowledgeGraphProjectionError(
                "KNOWLEDGE_GRAPH_CURRICULUM_SOURCE_INVALID",
                "reviewed curriculum bindings require a multimodal document source",
            )
        bound_units = tuple(units_by_id[unit_id] for unit_id in binding.curriculum_unit_ids)
        if tuple(sorted(unit.unit_code for unit in bound_units)) != source.curriculum_unit_keys:
            raise KnowledgeGraphProjectionError(
                "KNOWLEDGE_GRAPH_CURRICULUM_SOURCE_MISMATCH",
                "reviewed curriculum binding differs from the accepted source range",
            )
        proposal_nodes = {node.node_id: node for node in analysis.proposal.nodes}
        pointers_by_stable_key: dict[str, set[GraphSourcePointer]] = {}
        range_pointers: set[GraphSourcePointer] = set()
        for node in proposal_nodes.values():
            pointers = {_source_pointer(analysis, anchor_id) for anchor_id in node.anchor_ids}
            pointers_by_stable_key[node.stable_key] = pointers
            range_pointers.update(pointers)
        if not range_pointers:
            raise KnowledgeGraphProjectionError(
                "KNOWLEDGE_GRAPH_CURRICULUM_SOURCE_MISSING",
                "reviewed curriculum binding has no source evidence",
            )
        node_pointers_by_run[run_id] = pointers_by_stable_key
        for unit in bound_units:
            direct_pointers[unit.curriculum_unit_id].update(range_pointers)

    children_by_parent: dict[str, list[str]] = {}
    for unit in structure.curriculum_units:
        if unit.parent_unit_id is not None:
            children_by_parent.setdefault(unit.parent_unit_id, []).append(unit.curriculum_unit_id)

    pointer_cache: dict[str, frozenset[GraphSourcePointer]] = {}

    def descendant_pointers(
        unit_id: str, visiting: frozenset[str] = frozenset()
    ) -> frozenset[GraphSourcePointer]:
        cached = pointer_cache.get(unit_id)
        if cached is not None:
            return cached
        if unit_id in visiting:
            raise KnowledgeGraphProjectionError(
                "KNOWLEDGE_GRAPH_CURRICULUM_CYCLE", "curriculum hierarchy contains a cycle"
            )
        values = set(direct_pointers[unit_id])
        for child_id in children_by_parent.get(unit_id, []):
            values.update(descendant_pointers(child_id, visiting | {unit_id}))
        result = frozenset(values)
        pointer_cache[unit_id] = result
        return result

    pointers_by_unit = {
        unit.curriculum_unit_id: descendant_pointers(unit.curriculum_unit_id)
        for unit in structure.curriculum_units
    }
    if any(not values for values in pointers_by_unit.values()):
        raise KnowledgeGraphProjectionError(
            "KNOWLEDGE_GRAPH_CURRICULUM_COVERAGE_MISSING",
            "every reviewed curriculum unit must resolve to accepted source evidence",
        )

    unit_node_ids: dict[str, str] = {}
    for unit in structure.curriculum_units:
        node_id = _stable_id(
            "knode_",
            {"node_type": KnowledgeNodeType.CURRICULUM_UNIT, "stable_key": unit.node_stable_key},
        )
        unit_node_ids[unit.curriculum_unit_id] = node_id
        existing = node_accumulators.get(unit.node_stable_key)
        if existing is None:
            node_accumulators[unit.node_stable_key] = _NodeAccumulator(
                node_id=node_id,
                node_type=KnowledgeNodeType.CURRICULUM_UNIT,
                stable_key=unit.node_stable_key,
                label_counts={unit.label: 1},
                reviewed_label=unit.label,
                source_pointers=set(pointers_by_unit[unit.curriculum_unit_id]),
            )
        elif existing.node_id != node_id or existing.node_type != KnowledgeNodeType.CURRICULUM_UNIT:
            raise KnowledgeGraphProjectionError(
                "KNOWLEDGE_GRAPH_CURRICULUM_NODE_CONFLICT",
                "reviewed curriculum node conflicts with an accepted proposal",
            )
        else:
            existing.add_label(unit.label, reviewed=True)
            existing.source_pointers.update(pointers_by_unit[unit.curriculum_unit_id])

    for unit in structure.curriculum_units:
        if unit.parent_unit_id is None:
            continue
        _merge_edge(
            edge_accumulators,
            edge_type="CONTAINS_CURRICULUM_UNIT",
            from_node_id=unit_node_ids[unit.parent_unit_id],
            to_node_id=unit_node_ids[unit.curriculum_unit_id],
            confidence_milli=1000,
            source_pointers=set(pointers_by_unit[unit.curriculum_unit_id]),
        )

    for run_id, binding in bindings_by_run.items():
        analysis = analysis_by_id[run_id]
        pointers_by_stable_key = node_pointers_by_run[run_id]
        for proposed_node in analysis.proposal.nodes:
            if proposed_node.node_type not in _CURRICULUM_ALIGNED_NODE_TYPES:
                continue
            from_node_id = local_node_ids[(run_id, proposed_node.node_id)]
            for unit_id in binding.curriculum_unit_ids:
                _merge_edge(
                    edge_accumulators,
                    edge_type="ALIGNS_WITH_CURRICULUM",
                    from_node_id=from_node_id,
                    to_node_id=unit_node_ids[unit_id],
                    confidence_milli=1000,
                    source_pointers=set(pointers_by_stable_key[proposed_node.stable_key]),
                )


def build_education_graph_projection(
    analyses: tuple[AcceptedAnalysisProposal, ...],
    structure: KnowledgeGraphStructureManifest | KnowledgeGraphStructureManifestV2 | None,
) -> EducationGraphProjection:
    """Merge accepted proposals by stable identity and fail closed on conflicts."""

    if not analyses:
        raise KnowledgeGraphProjectionError(
            "KNOWLEDGE_GRAPH_SOURCE_MISSING", "at least one accepted analysis is required"
        )
    run_ids = tuple(item.analysis_run_id for item in analyses)
    if tuple(sorted(run_ids)) != run_ids or len(run_ids) != len(set(run_ids)):
        raise KnowledgeGraphProjectionError(
            "KNOWLEDGE_GRAPH_SOURCE_ORDER_INVALID",
            "accepted analysis runs must be sorted and unique",
        )
    _validate_document_page_coverage(analyses)
    if structure is not None and structure.source_analysis_run_ids != run_ids:
        raise KnowledgeGraphProjectionError(
            "KNOWLEDGE_GRAPH_STRUCTURE_SOURCE_MISMATCH",
            "structure manifest does not pin the exact publication source set",
        )

    node_accumulators: dict[str, _NodeAccumulator] = {}
    allow_label_aliases = isinstance(structure, KnowledgeGraphStructureManifestV2)
    local_node_ids: dict[tuple[str, str], str] = {}
    edge_accumulators: dict[tuple[str, str, str], _EdgeAccumulator] = {}
    anchor_count = 0
    for analysis in analyses:
        anchor_count += len(analysis.proposal.anchors)
        for proposed_node in analysis.proposal.nodes:
            node_id = _stable_id(
                "knode_",
                {
                    "node_type": proposed_node.node_type,
                    "stable_key": proposed_node.stable_key,
                },
            )
            local_node_ids[(analysis.analysis_run_id, proposed_node.node_id)] = node_id
            pointers = {
                _source_pointer(analysis, anchor_id) for anchor_id in proposed_node.anchor_ids
            }
            existing = node_accumulators.get(proposed_node.stable_key)
            if existing is None:
                node_accumulators[proposed_node.stable_key] = _NodeAccumulator(
                    node_id=node_id,
                    node_type=proposed_node.node_type,
                    stable_key=proposed_node.stable_key,
                    label_counts={proposed_node.label: 1},
                    reviewed_label=None,
                    source_pointers=pointers,
                )
            elif (
                existing.node_id != node_id
                or existing.node_type != proposed_node.node_type
                or (not allow_label_aliases and proposed_node.label not in existing.label_counts)
            ):
                raise KnowledgeGraphProjectionError(
                    "KNOWLEDGE_GRAPH_NODE_CONFLICT",
                    "one stable node key has conflicting type or label",
                )
            else:
                existing.add_label(proposed_node.label)
                existing.source_pointers.update(pointers)

        proposal_nodes = {item.node_id: item for item in analysis.proposal.nodes}
        for proposed_edge in analysis.proposal.edges:
            from_node = proposal_nodes[proposed_edge.from_node_id]
            to_node = proposal_nodes[proposed_edge.to_node_id]
            edge_type = _proposal_edge_type(proposed_edge)
            try:
                validate_knowledge_edge_endpoint_types(
                    edge_type, from_node.node_type, to_node.node_type
                )
            except ValueError as exc:
                raise KnowledgeGraphProjectionError(
                    "KNOWLEDGE_GRAPH_EDGE_INCOMPATIBLE",
                    "knowledge graph edge endpoint types are incompatible",
                ) from exc
            from_id = local_node_ids[(analysis.analysis_run_id, proposed_edge.from_node_id)]
            to_id = local_node_ids[(analysis.analysis_run_id, proposed_edge.to_node_id)]
            pointers = {
                _source_pointer(analysis, anchor_id) for anchor_id in proposed_edge.anchor_ids
            }
            _merge_edge(
                edge_accumulators,
                edge_type=edge_type,
                from_node_id=from_id,
                to_node_id=to_id,
                confidence_milli=proposed_edge.confidence_milli,
                source_pointers=pointers,
            )

    if isinstance(structure, KnowledgeGraphStructureManifestV2):
        _add_reviewed_curriculum_structure(
            analyses, structure, node_accumulators, local_node_ids, edge_accumulators
        )

    curriculum_units = structure.curriculum_units if structure is not None else ()
    item_elements = structure.item_elements if structure is not None else ()
    for curriculum_binding in curriculum_units:
        node = node_accumulators.get(curriculum_binding.node_stable_key)
        expected_type = (
            KnowledgeNodeType.ACHIEVEMENT_STANDARD
            if curriculum_binding.unit_level == "ACHIEVEMENT_STANDARD"
            else KnowledgeNodeType.CURRICULUM_UNIT
        )
        if node is None or node.node_type != expected_type:
            raise KnowledgeGraphProjectionError(
                "KNOWLEDGE_GRAPH_CURRICULUM_NODE_INVALID",
                "curriculum binding does not resolve to a compatible graph node",
            )
    answer_bearing_keys = {item.node_stable_key for item in item_elements if item.answer_bearing}
    for item_binding in item_elements:
        node = node_accumulators.get(item_binding.node_stable_key)
        if node is None or node.node_type != KnowledgeNodeType.ITEM_ELEMENT:
            raise KnowledgeGraphProjectionError(
                "KNOWLEDGE_GRAPH_ITEM_ELEMENT_NODE_INVALID",
                "Item element binding does not resolve to an ITEM_ELEMENT node",
            )

    if any(len(item.aliases()) > _MAX_NODE_ALIASES for item in node_accumulators.values()):
        raise KnowledgeGraphProjectionError(
            "KNOWLEDGE_GRAPH_NODE_ALIAS_LIMIT_EXCEEDED",
            "one stable node key exceeds the bounded alias contract",
        )

    nodes = tuple(
        ProjectedKnowledgeNode(
            node_id=item.node_id,
            node_type=item.node_type,
            stable_key=item.stable_key,
            label=item.preferred_label(),
            aliases=item.aliases(),
            answer_bearing=item.stable_key in answer_bearing_keys,
            source_pointers=tuple(sorted(item.source_pointers)),
        )
        for item in sorted(node_accumulators.values(), key=lambda value: value.node_id)
    )
    answer_bearing_node_ids = {item.node_id for item in nodes if item.answer_bearing}
    edges = tuple(
        ProjectedKnowledgeEdge(
            edge_id=item.edge_id,
            edge_type=item.edge_type,
            from_node_id=item.from_node_id,
            to_node_id=item.to_node_id,
            confidence_milli=item.confidence_milli,
            answer_bearing=(
                item.from_node_id in answer_bearing_node_ids
                or item.to_node_id in answer_bearing_node_ids
            ),
            source_pointers=tuple(sorted(item.source_pointers)),
        )
        for item in sorted(edge_accumulators.values(), key=lambda value: value.edge_id)
    )
    return EducationGraphProjection(
        analyses=analyses,
        nodes=nodes,
        edges=edges,
        curriculum_units=curriculum_units,
        curriculum_closure=_curriculum_closure(curriculum_units),
        item_elements=item_elements,
        anchor_count=anchor_count,
        projection_schema_version=(
            "3.0"
            if isinstance(structure, KnowledgeGraphStructureManifestV2)
            else (
                "2.0"
                if any(
                    isinstance(analysis.source, EducationalDocumentKnowledgeSourceV3)
                    for analysis in analyses
                )
                else "1.0"
            )
        ),
    )


def serialize_education_graph_projection(
    projection: EducationGraphProjection,
) -> EducationGraphProjectionFiles:
    """Serialize projection members canonically for Artifact publication."""

    include_aliases = projection.projection_schema_version == "3.0"
    node_documents = [item.document(include_aliases=include_aliases) for item in projection.nodes]
    edge_documents = [item.document() for item in projection.edges]
    closure_documents = [item.document() for item in projection.curriculum_closure]
    lexical: dict[str, set[str]] = {}
    for node in projection.nodes:
        for label in (node.label, *node.aliases):
            for token in knowledge_node_terms(node.stable_key, label):
                lexical.setdefault(token, set()).add(node.node_id)
    lexical_document = {
        "schema_version": (
            "knowledge-graph-lexical-index/2.0"
            if include_aliases
            else "knowledge-graph-lexical-index/1.0"
        ),
        "entries": [
            {"term": term, "node_ids": sorted(node_ids)}
            for term, node_ids in sorted(lexical.items())
        ],
    }
    markdown_lines = ["# Education Knowledge Graph", "", "## Nodes", ""]
    markdown_lines.extend(
        f"- `{item.node_id}` [{item.node_type}] {item.label}" for item in projection.nodes
    )
    markdown_lines.extend(["", "## Edges", ""])
    markdown_lines.extend(
        f"- `{item.from_node_id}` --{item.edge_type}--> `{item.to_node_id}`"
        for item in projection.edges
    )
    markdown = ("\n".join(markdown_lines) + "\n").encode("utf-8")
    members = {
        "projections/nodes.jsonl": b"".join(
            canonical_json_bytes(value) + b"\n" for value in node_documents
        ),
        "projections/edges.jsonl": b"".join(
            canonical_json_bytes(value) + b"\n" for value in edge_documents
        ),
        "projections/graph.md": markdown,
        "projections/lexical-index.json": canonical_json_bytes(lexical_document),
    }
    if closure_documents:
        members["projections/curriculum-closure.jsonl"] = b"".join(
            canonical_json_bytes(value) + b"\n" for value in closure_documents
        )
    projection_schema = (
        f"eom://schemas/knowledge/knowledge-graph-projection/{projection.projection_schema_version}"
    )
    metadata = {
        "projections/nodes.jsonl": {
            "schema_ref": projection_schema,
            "media_type": "application/x-ndjson",
        },
        "projections/edges.jsonl": {
            "schema_ref": projection_schema,
            "media_type": "application/x-ndjson",
        },
        "projections/graph.md": {
            "schema_ref": "eom://schemas/knowledge/knowledge-graph-markdown/1.0",
            "media_type": "text/markdown",
        },
        "projections/lexical-index.json": {
            "schema_ref": projection_schema,
            "media_type": "application/json",
        },
    }
    if closure_documents:
        metadata["projections/curriculum-closure.jsonl"] = {
            "schema_ref": projection_schema,
            "media_type": "application/x-ndjson",
        }
    descriptors = [
        {"member_path": path, "sha256": sha256_bytes(value), "bytes": len(value)}
        for path, value in sorted(members.items())
    ]
    return EducationGraphProjectionFiles(
        members=members,
        metadata=metadata,
        snapshot_sha256=content_sha256(
            {
                "analysis_run_ids": [item.analysis_run_id for item in projection.analyses],
                "members": descriptors,
            }
        ),
    )
