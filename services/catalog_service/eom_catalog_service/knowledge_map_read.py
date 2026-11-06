"""Bounded, metadata-only exploration of the existing published Knowledge Graph."""

from __future__ import annotations

from collections import defaultdict
from typing import get_args

from eom_catalog_contracts.knowledge_map import (
    KnowledgeMapEdge,
)
from eom_catalog_contracts.knowledge_map_v2 import KnowledgeMapNodeV2 as KnowledgeMapNode
from eom_catalog_contracts.knowledge_map_v2 import KnowledgeMapSourceV2 as KnowledgeMapSource
from eom_catalog_contracts.knowledge_map_v2 import KnowledgeMapViewV2 as KnowledgeMapView
from eom_catalog_contracts.knowledge_map_v2 import MapLayerV2 as MapLayer
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.knowledge_analysis_models import KnowledgeAnalysisRunRecord
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord
from eom_workflow_runner.models import WorkflowInstanceRecord
from sqlalchemy import Engine, Select, and_, or_, select, text
from sqlalchemy.orm import Session, aliased

from eom_catalog_service.item_origin_models import ItemOriginProfileRecord
from eom_catalog_service.knowledge_graph_models import (
    KnowledgeCorpusRecord,
    KnowledgeEdgeRecord,
    KnowledgeEdgeSourcePointerRecord,
    KnowledgeGraphSnapshotRecord,
    KnowledgeNodeRecord,
    KnowledgeNodeSourcePointerRecord,
    KnowledgeNodeTermRecord,
    KnowledgeSnapshotAnalysisRecord,
)
from eom_catalog_service.knowledge_graph_projection import knowledge_node_terms
from eom_catalog_service.knowledge_map_layers import (
    PRIMARY_MAP_LAYERS,
    source_classes_for_layer,
    source_layer,
    source_layer_expression,
)
from eom_catalog_service.knowledge_retrieval_service import KnowledgeRetrievalApplicationService
from eom_catalog_service.models import (
    EducationalDocumentRecord,
    EducationalDocumentRevisionRecord,
    ItemRecord,
    ItemRevisionRecord,
)
from eom_catalog_service.settings import CatalogSettings

MAX_NODES = 120
MAX_EDGES = 240
MAX_SOURCES = 20


class KnowledgeMapReadError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def layer_node_ids(snapshot_id: str, layer: MapLayer) -> Select[tuple[str]]:
    """Snapshot/source-class index, then exact origin/Workflow PK joins.

    Matching occurs before the caller's LIMIT; no bounded client neighborhood is
    mistaken for the complete layer. No Artifact or report bytes are read.
    """
    pointer = KnowledgeNodeSourcePointerRecord
    statement = (
        select(pointer.node_id)
        .outerjoin(
            ItemOriginProfileRecord,
            ItemOriginProfileRecord.item_revision_id == pointer.source_revision_id,
        )
        .outerjoin(
            ItemRevisionRecord, ItemRevisionRecord.item_revision_id == pointer.source_revision_id
        )
        .outerjoin(
            WorkflowInstanceRecord,
            WorkflowInstanceRecord.workflow_id == ItemRevisionRecord.workflow_id,
        )
        .where(
            pointer.graph_snapshot_revision_id == snapshot_id,
            source_layer_expression(
                pointer.source_class,
                ItemOriginProfileRecord.source_domain,
                WorkflowInstanceRecord.definition_key,
            )
            == layer,
        )
        .distinct()
    )
    classes = source_classes_for_layer(layer)
    return statement.where(pointer.source_class.in_(classes)) if classes else statement


def neighborhood_edges(snapshot_id: str, seeds: set[str]) -> Select[tuple[KnowledgeEdgeRecord]]:
    """The existing forward/reverse adjacency indexes bound this lookup."""
    return (
        select(KnowledgeEdgeRecord)
        .where(
            KnowledgeEdgeRecord.graph_snapshot_revision_id == snapshot_id,
            or_(
                KnowledgeEdgeRecord.from_node_id.in_(seeds),
                KnowledgeEdgeRecord.to_node_id.in_(seeds),
            ),
        )
        .order_by(KnowledgeEdgeRecord.edge_id)
        .limit(MAX_EDGES + 1)
    )


class KnowledgeMapReadService:
    """Caller supplies authenticated administrator authority, not model-supplied roles."""

    def __init__(self, engine: Engine) -> None:
        self.sessions = build_session_factory(engine)
        # This existing public resolver validates DB/manifest metadata only. Map
        # never invokes retrieval/materialization/commit methods on this owner.
        self.snapshots = KnowledgeRetrievalApplicationService(engine, CatalogSettings())

    def item_reference(
        self, snapshot_id: str, snapshot_hash: str, revision_id: str, manifest_hash: str
    ) -> str:
        with self.sessions() as session:
            session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
            session.execute(text("SET LOCAL statement_timeout = '8s'"))
            self.snapshots.resolve_snapshot_pointer(session, snapshot_id)
            snapshot = session.get(KnowledgeGraphSnapshotRecord, snapshot_id)
            if snapshot is None or snapshot.snapshot_sha256 != snapshot_hash:
                raise KnowledgeMapReadError("KNOWLEDGE_MAP_STALE")
            association = session.scalar(
                select(KnowledgeSnapshotAnalysisRecord.snapshot_analysis_id)
                .where(
                    KnowledgeSnapshotAnalysisRecord.graph_snapshot_revision_id == snapshot_id,
                    KnowledgeSnapshotAnalysisRecord.source_kind == "APPROVED_ITEM_REVISION",
                    KnowledgeSnapshotAnalysisRecord.source_revision_id == revision_id,
                )
                .limit(1)
            )
            item = session.get(ItemRevisionRecord, revision_id)
            logical = session.get(ItemRecord, item.item_id) if item else None
            if (
                association is None
                or item is None
                or item.manifest_sha256 != manifest_hash
                or item.revision_state not in {"APPROVED", "SUPERSEDED"}
                or logical is None
                or logical.lifecycle_state != "ACTIVE"
            ):
                raise KnowledgeMapReadError("KNOWLEDGE_MAP_ITEM_STALE")
            return item.item_id

    def read(
        self,
        *,
        graph_snapshot_revision_id: str | None = None,
        snapshot_sha256: str | None = None,
        query: str = "",
        node_id: str | None = None,
        edge_id: str | None = None,
        layer: MapLayer | None = None,
    ) -> KnowledgeMapView:
        if (graph_snapshot_revision_id is None) != (snapshot_sha256 is None):
            raise KnowledgeMapReadError("KNOWLEDGE_MAP_PIN_REQUIRED")
        if (node_id and edge_id) or ((node_id or edge_id) and graph_snapshot_revision_id is None):
            raise KnowledgeMapReadError("KNOWLEDGE_MAP_PIN_REQUIRED")
        if layer is not None and layer not in get_args(MapLayer):
            raise KnowledgeMapReadError("KNOWLEDGE_MAP_LAYER_INVALID")
        with self.sessions() as session:
            session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
            session.execute(text("SET LOCAL statement_timeout = '8s'"))
            snapshot_id = graph_snapshot_revision_id
            if snapshot_id is None:
                snapshot_id = session.scalar(
                    select(KnowledgeCorpusRecord.current_graph_snapshot_revision_id).where(
                        KnowledgeCorpusRecord.corpus_key == "integrated-science-textbooks",
                        KnowledgeCorpusRecord.lifecycle_state == "ACTIVE",
                    )
                )
            if snapshot_id is None:
                raise KnowledgeMapReadError("KNOWLEDGE_MAP_UNAVAILABLE")
            self.snapshots.resolve_snapshot_pointer(session, snapshot_id)
            snapshot = session.get(KnowledgeGraphSnapshotRecord, snapshot_id)
            assert snapshot is not None
            if snapshot_sha256 is not None and snapshot.snapshot_sha256 != snapshot_sha256:
                raise KnowledgeMapReadError("KNOWLEDGE_MAP_STALE")
            seeds = self._seeds(session, snapshot_id, query, node_id, edge_id, layer)
            edges = list(session.scalars(neighborhood_edges(snapshot_id, seeds))) if seeds else []
            truncated = len(edges) > MAX_EDGES
            edges = edges[:MAX_EDGES]
            if edge_id and all(edge.edge_id != edge_id for edge in edges):
                selected_edge = session.get(KnowledgeEdgeRecord, (snapshot_id, edge_id))
                assert selected_edge is not None
                edges = sorted(
                    [*edges[: MAX_EDGES - 1], selected_edge], key=lambda edge: edge.edge_id
                )
            visible = set(seeds)
            accepted_edges: list[KnowledgeEdgeRecord] = []
            for edge in edges:
                endpoints = {edge.from_node_id, edge.to_node_id}
                if len(visible | endpoints) > MAX_NODES:
                    truncated = True
                    continue
                visible.update(endpoints)
                accepted_edges.append(edge)
            nodes = (
                tuple(
                    session.scalars(
                        select(KnowledgeNodeRecord)
                        .where(
                            KnowledgeNodeRecord.graph_snapshot_revision_id == snapshot_id,
                            KnowledgeNodeRecord.node_id.in_(visible),
                        )
                        .order_by(KnowledgeNodeRecord.node_id)
                    )
                )
                if visible
                else ()
            )
            if len(nodes) != len(visible):
                raise KnowledgeMapReadError("KNOWLEDGE_MAP_STALE")
            layers = self._layers(session, snapshot_id, visible)
            sources, more_sources = self._sources(session, snapshot_id, node_id, edge_id, layer)
            return KnowledgeMapView(
                graph_snapshot_revision_id=snapshot_id,
                snapshot_sha256=snapshot.snapshot_sha256,
                nodes=tuple(
                    KnowledgeMapNode(
                        node_id=row.node_id,
                        node_type=row.node_type,
                        label=row.label[:1024] or row.node_type,
                        layers=tuple(sorted(layers.get(row.node_id, set()))),
                    )
                    for row in nodes
                ),
                edges=tuple(
                    KnowledgeMapEdge(
                        edge_id=row.edge_id,
                        from_node_id=row.from_node_id,
                        to_node_id=row.to_node_id,
                        edge_type=row.edge_type,
                    )
                    for row in accepted_edges
                ),
                sources=sources,
                focus_node_id=node_id,
                selected_edge_id=edge_id,
                truncated=truncated or more_sources,
                total_nodes=snapshot.node_count,
                total_edges=snapshot.edge_count,
            )

    @staticmethod
    def _seeds(
        session: Session,
        snapshot_id: str,
        query: str,
        node_id: str | None,
        edge_id: str | None,
        layer: MapLayer | None = None,
    ) -> set[str]:
        if node_id:
            if session.get(KnowledgeNodeRecord, (snapshot_id, node_id)) is None:
                raise KnowledgeMapReadError("KNOWLEDGE_MAP_NODE_NOT_FOUND")
            return {node_id}
        if edge_id:
            edge = session.get(KnowledgeEdgeRecord, (snapshot_id, edge_id))
            if edge is None:
                raise KnowledgeMapReadError("KNOWLEDGE_MAP_EDGE_NOT_FOUND")
            return {edge.from_node_id, edge.to_node_id}
        if query.strip():
            terms = knowledge_node_terms("", query.strip())
            if not terms:
                return set()
            statement = (
                select(KnowledgeNodeTermRecord.node_id)
                .where(
                    KnowledgeNodeTermRecord.graph_snapshot_revision_id == snapshot_id,
                    KnowledgeNodeTermRecord.term.in_(terms),
                )
                .distinct()
                .order_by(KnowledgeNodeTermRecord.node_id)
                .limit(20)
            )
            if layer is not None:
                statement = statement.where(
                    KnowledgeNodeTermRecord.node_id.in_(layer_node_ids(snapshot_id, layer))
                )
        elif layer is not None:
            return set(
                session.scalars(
                    layer_node_ids(snapshot_id, layer)
                    .order_by(KnowledgeNodeSourcePointerRecord.node_id)
                    .limit(20)
                )
            )
        else:
            # One shared Graph: show a small sample from each real layer rather
            # than only curriculum roots. The fixed five reads are not N+1 IO.
            seeds = {
                node_id
                for source_layer_key in PRIMARY_MAP_LAYERS
                for node_id in session.scalars(
                    layer_node_ids(snapshot_id, source_layer_key)
                    .order_by(KnowledgeNodeSourcePointerRecord.node_id)
                    .limit(2)
                )
            }
            statement = (
                select(KnowledgeNodeRecord.node_id)
                .where(
                    KnowledgeNodeRecord.graph_snapshot_revision_id == snapshot_id,
                    KnowledgeNodeRecord.node_type == "CURRICULUM_UNIT",
                )
                .order_by(KnowledgeNodeRecord.stable_key)
                .limit(10)
            )
            return seeds | set(session.scalars(statement))
        return set(session.scalars(statement))

    @staticmethod
    def _layers(session: Session, snapshot_id: str, visible: set[str]) -> dict[str, set[MapLayer]]:
        pointers = KnowledgeNodeSourcePointerRecord
        statement = (
            select(
                pointers.node_id,
                pointers.source_class,
                ItemOriginProfileRecord.source_domain,
                WorkflowInstanceRecord.definition_key,
            )
            .outerjoin(
                ItemOriginProfileRecord,
                ItemOriginProfileRecord.item_revision_id == pointers.source_revision_id,
            )
            .outerjoin(
                ItemRevisionRecord,
                ItemRevisionRecord.item_revision_id == pointers.source_revision_id,
            )
            .outerjoin(
                WorkflowInstanceRecord,
                WorkflowInstanceRecord.workflow_id == ItemRevisionRecord.workflow_id,
            )
            .where(
                pointers.graph_snapshot_revision_id == snapshot_id, pointers.node_id.in_(visible)
            )
            .distinct()
        )
        layers: dict[str, set[MapLayer]] = defaultdict(set)
        if visible:
            for node_id, source_class, domain, workflow_key in session.execute(statement):
                layers[node_id].add(source_layer(source_class, domain, workflow_key))
        return layers

    @staticmethod
    def _sources(
        session: Session,
        snapshot_id: str,
        node_id: str | None,
        edge_id: str | None,
        layer: MapLayer | None = None,
    ) -> tuple[tuple[KnowledgeMapSource, ...], bool]:
        if node_id is None and edge_id is None:
            return (), False
        pointer = KnowledgeNodeSourcePointerRecord if node_id else KnowledgeEdgeSourcePointerRecord
        target = (
            KnowledgeNodeSourcePointerRecord.node_id
            if node_id
            else KnowledgeEdgeSourcePointerRecord.edge_id
        )
        analysis = KnowledgeSnapshotAnalysisRecord
        run = KnowledgeAnalysisRunRecord
        artifact = aliased(ArtifactRecord)
        revision = aliased(ArtifactRevisionRecord)
        item = ItemRevisionRecord
        document = EducationalDocumentRevisionRecord
        statement = (
            select(
                pointer,
                analysis.source_kind,
                analysis.accepted_result_artifact_revision_id,
                analysis.accepted_result_sha256,
                run.state,
                run.accepted_result_artifact_revision_id,
                run.accepted_result_sha256,
                revision.logical_artifact_id,
                revision.approved,
                artifact.approved,
                item.item_id,
                item.manifest_sha256,
                item.revision_state,
                ItemRecord.lifecycle_state,
                ItemOriginProfileRecord.source_domain,
                WorkflowInstanceRecord.definition_key,
                document.title,
                document.revision_state,
                EducationalDocumentRecord.lifecycle_state,
            )
            .outerjoin(
                analysis,
                and_(
                    analysis.graph_snapshot_revision_id == pointer.graph_snapshot_revision_id,
                    analysis.analysis_run_id == pointer.analysis_run_id,
                    analysis.source_revision_id == pointer.source_revision_id,
                ),
            )
            .outerjoin(run, run.analysis_run_id == pointer.analysis_run_id)
            .outerjoin(
                revision,
                revision.revision_id == pointer.artifact_revision_id,
            )
            .outerjoin(artifact, artifact.logical_artifact_id == pointer.source_artifact_id)
            .outerjoin(
                item,
                item.item_revision_id == pointer.source_revision_id,
            )
            .outerjoin(ItemRecord, ItemRecord.item_id == item.item_id)
            .outerjoin(
                WorkflowInstanceRecord, WorkflowInstanceRecord.workflow_id == item.workflow_id
            )
            .outerjoin(
                ItemOriginProfileRecord,
                ItemOriginProfileRecord.item_revision_id == item.item_revision_id,
            )
            .outerjoin(document, document.document_revision_id == pointer.source_revision_id)
            .outerjoin(
                EducationalDocumentRecord,
                EducationalDocumentRecord.document_id == document.document_id,
            )
            .where(
                pointer.graph_snapshot_revision_id == snapshot_id, target == (node_id or edge_id)
            )
            .order_by(
                pointer.pointer_id,
            )
            .limit(MAX_SOURCES + 1)
        )
        if layer is not None:
            statement = statement.where(
                source_layer_expression(
                    pointer.source_class,
                    ItemOriginProfileRecord.source_domain,
                    WorkflowInstanceRecord.definition_key,
                )
                == layer
            )
        rows = list(session.execute(statement))
        values: list[KnowledgeMapSource] = []
        for row in rows[:MAX_SOURCES]:
            (
                p,
                kind,
                accepted_revision,
                accepted_hash,
                run_state,
                run_revision,
                run_hash,
                artifact_id,
                revision_approved,
                artifact_approved,
                item_id,
                manifest_hash,
                item_state,
                item_lifecycle,
                domain,
                workflow_key,
                title,
                doc_state,
                doc_lifecycle,
            ) = row
            available = bool(
                run_state == "ACCEPTED"
                and accepted_revision == run_revision
                and accepted_hash == run_hash
                and artifact_id == p.source_artifact_id
                and revision_approved
                and artifact_approved
            )
            if kind == "APPROVED_ITEM_REVISION":
                available = (
                    available
                    and item_state in {"APPROVED", "SUPERSEDED"}
                    and item_lifecycle == "ACTIVE"
                )
            elif kind == "DOCUMENT_REVISION":
                available = available and doc_state == "APPROVED" and doc_lifecycle == "ACTIVE"
            values.append(
                KnowledgeMapSource(
                    source_revision_id=p.source_revision_id,
                    source_class=p.source_class,
                    layer=source_layer(p.source_class, domain, workflow_key),
                    analysis_run_id=p.analysis_run_id,
                    source_artifact_id=p.source_artifact_id,
                    artifact_revision_id=p.artifact_revision_id,
                    source_sha256=p.source_sha256,
                    anchor_id=p.anchor_id,
                    excerpt_sha256=p.excerpt_sha256,
                    available=available,
                    title=(title or ("등록 문항" if item_id else "원본 자료"))[:512],
                    item_id=item_id,
                    item_manifest_sha256=manifest_hash,
                )
            )
        return tuple(values), len(rows) > MAX_SOURCES
