"""Catalog-owned publication of immutable Education Knowledge Graph snapshots."""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from datetime import UTC
from pathlib import Path
from typing import Any, cast

from eom_catalog_contracts import (
    ApprovedItemKnowledgeSourceV2,
    AssessmentItemContent,
    ContentIntakeKnowledgeSourceV2,
    CurriculumUnitBinding,
    EducationalDocumentKnowledgeSourceV3,
    EducationalDocumentKnowledgeSourceV4,
    EducationRetrievalAccessPolicy,
    EducationRetrievalRequestV2,
    EvidenceBundleManifestV2,
    EvidenceBundleManifestV3,
    EvidenceBundleManifestV4,
    KnowledgeAnalysisProposalReceipt,
    KnowledgeAnalysisProposalReceiptV2,
    KnowledgeAnalysisProposalReceiptV3,
    KnowledgeAnalysisProposalReceiptV4,
    KnowledgeAnalysisProposalReceiptV5,
    KnowledgeAnalysisProposalReceiptV6,
    KnowledgeAnalysisProposalReceiptV7,
    KnowledgeAnalysisRequestV2,
    KnowledgeAnalysisRequestV3,
    KnowledgeAnalysisRequestV4,
    KnowledgeAnalysisRequestV5,
    KnowledgeAnalysisRequestV6,
    KnowledgeAnalysisRequestV7,
    KnowledgeAnalysisRequestV8,
    KnowledgeAnalysisResultV2,
    KnowledgeAnalysisResultV3,
    KnowledgeAnalysisResultV4,
    KnowledgeAnalysisResultV5,
    KnowledgeAnalysisResultV6,
    KnowledgeAnalysisResultV7,
    KnowledgeAnalysisResultV8,
    KnowledgeAnalysisWorkerProposal,
    KnowledgeAnalysisWorkerProposalV2,
    KnowledgeAnalysisWorkerProposalV3,
    KnowledgeAnalysisWorkerProposalV4,
    KnowledgeAnalysisWorkerProposalV5,
    KnowledgeAnalysisWorkerProposalV6,
    KnowledgeArtifactMemberPointer,
    KnowledgeGraphCounts,
    KnowledgeGraphProjections,
    KnowledgeGraphPublicationResult,
    KnowledgeGraphSnapshotManifestV2,
    KnowledgeGraphSnapshotManifestV3,
    KnowledgeGraphSnapshotManifestV4,
    KnowledgeGraphSnapshotManifestV5,
    KnowledgeGraphSnapshotManifestV6,
    KnowledgeGraphSnapshotManifestV7,
    KnowledgeGraphSnapshotPointer,
    KnowledgeGraphStructureManifest,
    KnowledgeGraphStructureManifestV2,
    KnowledgeGraphStructureManifestV3,
    KnowledgeGraphStructureManifestV4,
    PublishKnowledgeGraphSnapshotCommand,
    PublishKnowledgeGraphSnapshotCommandV2,
    PublishKnowledgeGraphSnapshotCommandV3,
    PublishKnowledgeGraphSnapshotCommandV4,
    validate_contract,
)
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_identity_service.models import OperatorRecord
from eom_item_registry import RegistryError
from eom_orchestrator.database import build_session_factory, transaction
from eom_orchestrator.knowledge_analysis_models import KnowledgeAnalysisRunRecord
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord, JobRecord
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from eom_catalog_service.artifacts import CatalogArtifact, CatalogArtifactService
from eom_catalog_service.automatic_curriculum_alignment import (
    AUTOMATIC_ITEM_ALIGNMENT_EVIDENCE_BUDGET,
    AUTOMATIC_ITEM_ALIGNMENT_PERMISSION_KEYS,
    AUTOMATIC_ITEM_ALIGNMENT_SOURCE_CLASSES,
    AutomaticCurriculumAlignmentError,
    automatic_item_alignment_policy,
    automatic_item_alignment_topic_keys,
    derive_automatic_item_curriculum_unit_ids,
)
from eom_catalog_service.curriculum_graph_structure import (
    CurriculumGraphStructureError,
    validate_integrated_science_structure_manifest,
)
from eom_catalog_service.knowledge_analysis_sources import (
    EducationalDocumentSourceResolutionCache,
    KnowledgeAnalysisSourceError,
    resolve_approved_item_source,
    resolve_content_intake_source,
    resolve_educational_document_source,
)
from eom_catalog_service.knowledge_graph_models import (
    CurriculumUnitClosureRecord,
    CurriculumUnitRecord,
    EducationRetrievalAccessPolicyRevisionRecord,
    EducationRetrievalRequestRecord,
    EvidenceBundleEntryRecord,
    EvidenceBundleRecord,
    EvidenceBundleRevisionRecord,
    ItemElementReferenceRecord,
    KnowledgeCorpusRecord,
    KnowledgeCorpusRevisionRecord,
    KnowledgeEdgeRecord,
    KnowledgeEdgeSourcePointerRecord,
    KnowledgeGraphPublicationRecord,
    KnowledgeGraphSnapshotRecord,
    KnowledgeNodeRecord,
    KnowledgeNodeSourcePointerRecord,
    KnowledgeNodeTermRecord,
    KnowledgeSnapshotAnalysisRecord,
)
from eom_catalog_service.knowledge_graph_projection import (
    AcceptedAnalysisProposal,
    EducationGraphProjection,
    EducationGraphProjectionFiles,
    KnowledgeGraphProjectionError,
    build_education_graph_projection,
    knowledge_node_terms,
    serialize_education_graph_projection,
)
from eom_catalog_service.knowledge_proposal_resolution import (
    KnowledgeProposalResolutionError,
    resolve_knowledge_analysis_proposal,
)
from eom_catalog_service.models import (
    ItemComponentRecord,
    ItemRecord,
    ItemRevisionRecord,
)
from eom_catalog_service.registry_service import RegistryService
from eom_catalog_service.settings import CatalogSettings

KNOWLEDGE_GRAPH_CATALOG_PROTOCOL = "catalog-knowledge-graph/1.0"
KNOWLEDGE_GRAPH_CATALOG_SCHEMA_HASH = content_sha256(
    {
        "protocol": KNOWLEDGE_GRAPH_CATALOG_PROTOCOL,
        "contracts": [
            "knowledge-graph-publication/1.0",
            "knowledge-graph-structure-manifest/1.0",
            "knowledge-graph-snapshot-manifest/2.0",
            "knowledge-graph-publication-result/1.0",
            "knowledge-graph-projection/1.0",
        ],
    }
)
KNOWLEDGE_GRAPH_DOCUMENT_CATALOG_PROTOCOL = "catalog-knowledge-graph/1.1"
KNOWLEDGE_GRAPH_DOCUMENT_CATALOG_SCHEMA_HASH = content_sha256(
    {
        "protocol": KNOWLEDGE_GRAPH_DOCUMENT_CATALOG_PROTOCOL,
        "contracts": [
            "knowledge-graph-publication/1.0",
            "knowledge-graph-structure-manifest/1.0",
            "knowledge-graph-snapshot-manifest/3.0",
            "knowledge-graph-publication-result/1.0",
            "knowledge-graph-projection/2.0",
        ],
    }
)
KNOWLEDGE_GRAPH_MULTIMODAL_DOCUMENT_CATALOG_PROTOCOL = "catalog-knowledge-graph/1.2"
KNOWLEDGE_GRAPH_MULTIMODAL_DOCUMENT_CATALOG_SCHEMA_HASH = content_sha256(
    {
        "protocol": KNOWLEDGE_GRAPH_MULTIMODAL_DOCUMENT_CATALOG_PROTOCOL,
        "contracts": [
            "knowledge-graph-publication/1.0",
            "knowledge-graph-structure-manifest/1.0",
            "knowledge-graph-snapshot-manifest/4.0",
            "knowledge-graph-publication-result/1.0",
            "knowledge-graph-projection/2.0",
        ],
    }
)
KNOWLEDGE_GRAPH_REVIEWED_CURRICULUM_CATALOG_PROTOCOL = "catalog-knowledge-graph/1.3"
KNOWLEDGE_GRAPH_REVIEWED_CURRICULUM_CATALOG_SCHEMA_HASH = content_sha256(
    {
        "protocol": KNOWLEDGE_GRAPH_REVIEWED_CURRICULUM_CATALOG_PROTOCOL,
        "contracts": [
            "knowledge-graph-publication/2.0",
            "knowledge-graph-structure-manifest/2.0",
            "knowledge-graph-snapshot-manifest/5.0",
            "knowledge-graph-publication-result/1.0",
            "knowledge-graph-projection/3.0",
        ],
    }
)
KNOWLEDGE_GRAPH_APPROVED_ITEM_CATALOG_PROTOCOL = "catalog-knowledge-graph/1.4"
KNOWLEDGE_GRAPH_APPROVED_ITEM_CATALOG_SCHEMA_HASH = content_sha256(
    {
        "protocol": KNOWLEDGE_GRAPH_APPROVED_ITEM_CATALOG_PROTOCOL,
        "contracts": [
            "knowledge-graph-publication/3.0",
            "knowledge-graph-structure-manifest/3.0",
            "knowledge-graph-snapshot-manifest/6.0",
            "knowledge-graph-publication-result/1.0",
            "knowledge-graph-projection/3.0",
        ],
    }
)
KNOWLEDGE_GRAPH_AUTOMATIC_ITEM_CATALOG_PROTOCOL = "catalog-knowledge-graph/1.5"
KNOWLEDGE_GRAPH_AUTOMATIC_ITEM_CATALOG_SCHEMA_HASH = content_sha256(
    {
        "protocol": KNOWLEDGE_GRAPH_AUTOMATIC_ITEM_CATALOG_PROTOCOL,
        "contracts": [
            "knowledge-graph-publication/4.0",
            "knowledge-graph-structure-manifest/4.0",
            "knowledge-graph-snapshot-manifest/7.0",
            "knowledge-graph-publication-result/1.0",
            "knowledge-graph-projection/3.0",
        ],
    }
)
type KnowledgeAnalysisRequestContract = (
    KnowledgeAnalysisRequestV2
    | KnowledgeAnalysisRequestV3
    | KnowledgeAnalysisRequestV4
    | KnowledgeAnalysisRequestV5
    | KnowledgeAnalysisRequestV6
    | KnowledgeAnalysisRequestV7
    | KnowledgeAnalysisRequestV8
)
type KnowledgeAnalysisReceiptContract = (
    KnowledgeAnalysisProposalReceipt
    | KnowledgeAnalysisProposalReceiptV2
    | KnowledgeAnalysisProposalReceiptV3
    | KnowledgeAnalysisProposalReceiptV4
    | KnowledgeAnalysisProposalReceiptV5
    | KnowledgeAnalysisProposalReceiptV6
    | KnowledgeAnalysisProposalReceiptV7
)
type KnowledgeGraphSnapshotContract = (
    KnowledgeGraphSnapshotManifestV2
    | KnowledgeGraphSnapshotManifestV3
    | KnowledgeGraphSnapshotManifestV4
    | KnowledgeGraphSnapshotManifestV5
    | KnowledgeGraphSnapshotManifestV6
    | KnowledgeGraphSnapshotManifestV7
)
type KnowledgeGraphPublicationCommand = (
    PublishKnowledgeGraphSnapshotCommand
    | PublishKnowledgeGraphSnapshotCommandV2
    | PublishKnowledgeGraphSnapshotCommandV3
    | PublishKnowledgeGraphSnapshotCommandV4
)
type KnowledgeGraphStructureContract = (
    KnowledgeGraphStructureManifest
    | KnowledgeGraphStructureManifestV2
    | KnowledgeGraphStructureManifestV3
    | KnowledgeGraphStructureManifestV4
)


class KnowledgeGraphPublicationError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class CurrentKnowledgeGraphStructure:
    corpus_key: str
    display_name: str
    graph_snapshot_revision_id: str
    accepted_analysis_run_ids: tuple[str, ...]
    structure: (
        KnowledgeGraphStructureManifestV2
        | KnowledgeGraphStructureManifestV3
        | KnowledgeGraphStructureManifestV4
    )


def _typed_id(prefix: str, value: dict[str, object]) -> str:
    return prefix + content_sha256(value).removeprefix("sha256:")[:32]


def _curriculum_unit_layers(
    units: tuple[CurriculumUnitBinding, ...],
) -> tuple[tuple[CurriculumUnitBinding, ...], ...]:
    """Return deterministic parent-before-child layers for FK-safe persistence."""

    unit_by_id = {unit.curriculum_unit_id: unit for unit in units}
    if len(unit_by_id) != len(units):
        raise KnowledgeGraphPublicationError(
            "KNOWLEDGE_GRAPH_FRAMEWORK_INVALID",
            "curriculum unit IDs must be unique",
        )
    children_by_parent: dict[str | None, list[CurriculumUnitBinding]] = {}
    for unit in units:
        if unit.parent_unit_id is not None and unit.parent_unit_id not in unit_by_id:
            raise KnowledgeGraphPublicationError(
                "KNOWLEDGE_GRAPH_FRAMEWORK_INVALID",
                "curriculum unit parent does not resolve",
            )
        children_by_parent.setdefault(unit.parent_unit_id, []).append(unit)

    def order_key(unit: CurriculumUnitBinding) -> tuple[str, str, int, str]:
        return (
            unit.framework_revision_id,
            unit.parent_unit_id or "",
            unit.ordinal,
            unit.curriculum_unit_id,
        )

    frontier = tuple(sorted(children_by_parent.get(None, ()), key=order_key))
    layers: list[tuple[CurriculumUnitBinding, ...]] = []
    visited: set[str] = set()
    while frontier:
        layers.append(frontier)
        next_frontier: list[CurriculumUnitBinding] = []
        for unit in frontier:
            visited.add(unit.curriculum_unit_id)
            next_frontier.extend(children_by_parent.get(unit.curriculum_unit_id, ()))
        frontier = tuple(sorted(next_frontier, key=order_key))
    if visited != unit_by_id.keys():
        raise KnowledgeGraphPublicationError(
            "KNOWLEDGE_GRAPH_FRAMEWORK_INVALID",
            "curriculum unit hierarchy contains a cycle or has no root",
        )
    return tuple(layers)


def _manifest_member_schema_ref(revision: ArtifactRevisionRecord) -> str:
    files = revision.manifest.get("files")
    if not isinstance(files, list):
        raise KnowledgeGraphPublicationError(
            "KNOWLEDGE_GRAPH_CURRENT_INVALID",
            "graph manifest Artifact has no member inventory",
        )
    matches = [
        item
        for item in files
        if isinstance(item, dict) and item.get("file_name") == "projections/manifest.json"
    ]
    allowed = {
        "eom://schemas/knowledge/knowledge-graph-snapshot-manifest/2.0",
        "eom://schemas/knowledge/knowledge-graph-snapshot-manifest/3.0",
        "eom://schemas/knowledge/knowledge-graph-snapshot-manifest/4.0",
        "eom://schemas/knowledge/knowledge-graph-snapshot-manifest/5.0",
        "eom://schemas/knowledge/knowledge-graph-snapshot-manifest/6.0",
        "eom://schemas/knowledge/knowledge-graph-snapshot-manifest/7.0",
    }
    if len(matches) != 1 or matches[0].get("schema_ref") not in allowed:
        raise KnowledgeGraphPublicationError(
            "KNOWLEDGE_GRAPH_CURRENT_INVALID",
            "graph manifest Artifact schema is incompatible",
        )
    return str(matches[0]["schema_ref"])


def _source_revision_id(
    source: ContentIntakeKnowledgeSourceV2
    | ApprovedItemKnowledgeSourceV2
    | EducationalDocumentKnowledgeSourceV3
    | EducationalDocumentKnowledgeSourceV4,
) -> str:
    if isinstance(source, ApprovedItemKnowledgeSourceV2):
        return source.item_revision_id
    if isinstance(
        source, (EducationalDocumentKnowledgeSourceV3, EducationalDocumentKnowledgeSourceV4)
    ):
        return source.document_revision_id
    return source.source_file_id


class KnowledgeGraphPublicationService:
    def __init__(self, engine: Engine, settings: CatalogSettings | None = None) -> None:
        self.settings = settings or CatalogSettings.from_environment()
        self.sessions = build_session_factory(engine)
        self.artifacts = CatalogArtifactService(engine, self.settings)
        self.registry = RegistryService(engine, self.settings)

    def current_structure_context(self, corpus_key: str) -> CurrentKnowledgeGraphStructure:
        """Resolve the current structured snapshot and its exact accepted source membership."""

        with self.sessions() as session:
            corpus = session.scalar(
                select(KnowledgeCorpusRecord).where(KnowledgeCorpusRecord.corpus_key == corpus_key)
            )
            snapshot = (
                session.get(
                    KnowledgeGraphSnapshotRecord,
                    corpus.current_graph_snapshot_revision_id,
                )
                if corpus is not None and corpus.current_graph_snapshot_revision_id is not None
                else None
            )
            if (
                corpus is None
                or corpus.lifecycle_state != "ACTIVE"
                or snapshot is None
                or snapshot.state != "PUBLISHED"
                or snapshot.graph_id != corpus.graph_id
            ):
                raise KnowledgeGraphPublicationError(
                    "KNOWLEDGE_GRAPH_CURRENT_INVALID",
                    "knowledge corpus has no valid current structured snapshot",
                )
            revision = self._exact_artifact_revision(
                session,
                artifact_id=snapshot.manifest_artifact_id,
                revision_id=snapshot.manifest_artifact_revision_id,
                content_hash=snapshot.manifest_sha256,
                logical_artifact_type="knowledge-graph-snapshot-manifest",
                manifest_artifact_type="knowledge-graph-snapshot-manifest",
                primary_file="projections/manifest.json",
            )
            schema_ref = _manifest_member_schema_ref(revision)
            pointer = KnowledgeArtifactMemberPointer(
                artifact_id=snapshot.manifest_artifact_id,
                artifact_revision_id=snapshot.manifest_artifact_revision_id,
                sha256=snapshot.manifest_sha256,
                schema_ref=schema_ref,
                media_type="application/json",
                logical_name="manifest.json",
                member_path="projections/manifest.json",
            )
            value = self._read_json_member(
                pointer,
                max_bytes=max(1, revision.content_bytes),
                expected_bytes=revision.content_bytes,
            )
            try:
                manifest: (
                    KnowledgeGraphSnapshotManifestV5
                    | KnowledgeGraphSnapshotManifestV6
                    | KnowledgeGraphSnapshotManifestV7
                )
                if schema_ref.endswith("/7.0"):
                    validate_contract("knowledge-graph-snapshot-manifest-v7", value)
                    manifest = KnowledgeGraphSnapshotManifestV7.model_validate(value)
                elif schema_ref.endswith("/6.0"):
                    validate_contract("knowledge-graph-snapshot-manifest-v6", value)
                    manifest = KnowledgeGraphSnapshotManifestV6.model_validate(value)
                elif schema_ref.endswith("/5.0"):
                    validate_contract("knowledge-graph-snapshot-manifest-v5", value)
                    manifest = KnowledgeGraphSnapshotManifestV5.model_validate(value)
                else:
                    raise ValueError("current snapshot has no curriculum structure")
            except (ValidationError, ValueError) as exc:
                raise KnowledgeGraphPublicationError(
                    "KNOWLEDGE_GRAPH_CURRENT_INVALID",
                    "current Graph snapshot manifest is invalid or unstructured",
                ) from exc
            run_ids = tuple(
                session.scalars(
                    select(KnowledgeSnapshotAnalysisRecord.analysis_run_id)
                    .where(
                        KnowledgeSnapshotAnalysisRecord.graph_snapshot_revision_id
                        == snapshot.graph_snapshot_revision_id
                    )
                    .order_by(KnowledgeSnapshotAnalysisRecord.analysis_run_id)
                )
            )
            structure = self._load_structure_manifest(manifest.structure_manifest)
            if (
                not isinstance(
                    structure,
                    (
                        KnowledgeGraphStructureManifestV2,
                        KnowledgeGraphStructureManifestV3,
                        KnowledgeGraphStructureManifestV4,
                    ),
                )
                or run_ids != structure.source_analysis_run_ids
                or len(run_ids) != snapshot.source_count
            ):
                raise KnowledgeGraphPublicationError(
                    "KNOWLEDGE_GRAPH_CURRENT_INVALID",
                    "current Graph membership differs from its structure and snapshot counts",
                )
            return CurrentKnowledgeGraphStructure(
                corpus_key=corpus.corpus_key,
                display_name=corpus.display_name,
                graph_snapshot_revision_id=snapshot.graph_snapshot_revision_id,
                accepted_analysis_run_ids=run_ids,
                structure=structure,
            )

    def commit_structure_manifest(
        self,
        structure: (
            KnowledgeGraphStructureManifestV2
            | KnowledgeGraphStructureManifestV3
            | KnowledgeGraphStructureManifestV4
        ),
    ) -> KnowledgeArtifactMemberPointer:
        """Commit one reviewed structure manifest through the Catalog Artifact boundary."""

        try:
            validate_integrated_science_structure_manifest(structure)
            schema_key = (
                "knowledge-graph-structure-manifest-v4"
                if isinstance(structure, KnowledgeGraphStructureManifestV4)
                else (
                    "knowledge-graph-structure-manifest-v3"
                    if isinstance(structure, KnowledgeGraphStructureManifestV3)
                    else "knowledge-graph-structure-manifest-v2"
                )
            )
            validate_contract(schema_key, structure.model_dump(mode="json"))
        except (CurriculumGraphStructureError, ValidationError, ValueError) as exc:
            raise KnowledgeGraphPublicationError(
                "KNOWLEDGE_GRAPH_FRAMEWORK_INVALID",
                "reviewed curriculum framework does not resolve exactly",
            ) from exc
        with self.sessions() as session:
            reviewer = session.get(OperatorRecord, structure.reviewed_by_operator_id)
            if reviewer is None or reviewer.status != "ACTIVE":
                raise KnowledgeGraphPublicationError(
                    "KNOWLEDGE_GRAPH_REVIEWER_INVALID",
                    "structure manifest reviewer is absent or inactive",
                )
        try:
            with tempfile.TemporaryDirectory(
                prefix="knowledge-graph-structure.", dir=self.settings.staging_root
            ) as raw_directory:
                source = Path(raw_directory) / "graph-structure-manifest.json"
                source.write_bytes(canonical_json_bytes(structure))
                source.chmod(0o640)
                artifact = self.artifacts.commit_file_set(
                    files={"evidence/graph-structure-manifest.json": source},
                    primary_file="evidence/graph-structure-manifest.json",
                    artifact_type="knowledge-graph-structure-manifest",
                    idempotency_key=(
                        "knowledge-graph-structure:"
                        + structure.manifest_sha256.removeprefix("sha256:")
                    ),
                    request={
                        "structure_manifest_id": structure.structure_manifest_id,
                        "framework_revision_id": structure.framework_revision_id,
                        "manifest_sha256": structure.manifest_sha256,
                    },
                    result={
                        "structure_manifest_id": structure.structure_manifest_id,
                        "framework_revision_id": structure.framework_revision_id,
                        "source_analysis_count": len(structure.source_analysis_run_ids),
                        "curriculum_unit_count": len(structure.curriculum_units),
                    },
                    file_metadata={
                        "evidence/graph-structure-manifest.json": {
                            "schema_ref": (
                                "eom://schemas/knowledge/knowledge-graph-structure-manifest/4.0"
                                if isinstance(structure, KnowledgeGraphStructureManifestV4)
                                else (
                                    "eom://schemas/knowledge/knowledge-graph-structure-manifest/3.0"
                                    if isinstance(structure, KnowledgeGraphStructureManifestV3)
                                    else "eom://schemas/knowledge/knowledge-graph-structure-manifest/2.0"
                                )
                            ),
                            "media_type": "application/json",
                        }
                    },
                    manifest_version="knowledge-graph-structure-file-set/1.0",
                    protocol_version=(
                        KNOWLEDGE_GRAPH_AUTOMATIC_ITEM_CATALOG_PROTOCOL
                        if isinstance(structure, KnowledgeGraphStructureManifestV4)
                        else (
                            KNOWLEDGE_GRAPH_APPROVED_ITEM_CATALOG_PROTOCOL
                            if isinstance(structure, KnowledgeGraphStructureManifestV3)
                            else KNOWLEDGE_GRAPH_REVIEWED_CURRICULUM_CATALOG_PROTOCOL
                        )
                    ),
                    protocol_schema_hash=(
                        KNOWLEDGE_GRAPH_AUTOMATIC_ITEM_CATALOG_SCHEMA_HASH
                        if isinstance(structure, KnowledgeGraphStructureManifestV4)
                        else (
                            KNOWLEDGE_GRAPH_APPROVED_ITEM_CATALOG_SCHEMA_HASH
                            if isinstance(structure, KnowledgeGraphStructureManifestV3)
                            else KNOWLEDGE_GRAPH_REVIEWED_CURRICULUM_CATALOG_SCHEMA_HASH
                        )
                    ),
                )
        except (OSError, RuntimeError, ValueError) as exc:
            raise KnowledgeGraphPublicationError(
                "KNOWLEDGE_GRAPH_ARTIFACT_COMMIT_FAILED",
                "knowledge graph structure Artifact commit failed",
            ) from exc
        files = artifact.manifest.get("files")
        member = (
            next(
                (
                    value
                    for value in files
                    if isinstance(value, dict)
                    and value.get("file_name") == "evidence/graph-structure-manifest.json"
                ),
                None,
            )
            if isinstance(files, list)
            else None
        )
        if not isinstance(member, dict):
            raise KnowledgeGraphPublicationError(
                "KNOWLEDGE_GRAPH_ARTIFACT_COMMIT_FAILED",
                "knowledge graph structure Artifact member is absent",
            )
        return KnowledgeArtifactMemberPointer(
            artifact_id=artifact.artifact_id,
            artifact_revision_id=artifact.revision_id,
            sha256=cast(str, member["sha256"]),
            schema_ref=cast(str, member["schema_ref"]),
            media_type=cast(str, member["media_type"]),
            logical_name="graph-structure-manifest.json",
            member_path="evidence/graph-structure-manifest.json",
        )

    def publish(self, command: KnowledgeGraphPublicationCommand) -> KnowledgeGraphPublicationResult:
        existing = self._existing_publication(command)
        if existing is not None:
            return existing

        with self.sessions() as session:
            publisher = session.get(OperatorRecord, command.published_by_operator_id)
            if publisher is None or publisher.status != "ACTIVE":
                raise KnowledgeGraphPublicationError(
                    "KNOWLEDGE_GRAPH_PUBLISHER_INVALID",
                    "graph publisher is absent or inactive",
                )
            corpus = session.scalar(
                select(KnowledgeCorpusRecord).where(
                    KnowledgeCorpusRecord.corpus_key == command.corpus_key
                )
            )
            if corpus is None:
                if command.expected_current_snapshot_revision_id is not None:
                    raise KnowledgeGraphPublicationError(
                        "KNOWLEDGE_GRAPH_STALE_CURRENT",
                        "new corpus cannot have an expected current snapshot",
                    )
                revision_number = 1
                previous_corpus_revision_id = None
                previous_snapshot_revision_id = None
            else:
                if (
                    corpus.lifecycle_state != "ACTIVE"
                    or corpus.display_name != command.display_name
                ):
                    raise KnowledgeGraphPublicationError(
                        "KNOWLEDGE_GRAPH_CORPUS_CONFLICT",
                        "knowledge corpus identity or lifecycle differs",
                    )
                if (
                    corpus.current_graph_snapshot_revision_id
                    != command.expected_current_snapshot_revision_id
                ):
                    raise KnowledgeGraphPublicationError(
                        "KNOWLEDGE_GRAPH_STALE_CURRENT",
                        "expected graph snapshot is no longer current",
                    )
                current_snapshot = session.get(
                    KnowledgeGraphSnapshotRecord, corpus.current_graph_snapshot_revision_id
                )
                if current_snapshot is None or corpus.current_corpus_revision_id is None:
                    raise KnowledgeGraphPublicationError(
                        "KNOWLEDGE_GRAPH_CURRENT_INVALID",
                        "knowledge corpus current pointers do not resolve",
                    )
                revision_number = current_snapshot.revision_number + 1
                previous_corpus_revision_id = corpus.current_corpus_revision_id
                previous_snapshot_revision_id = current_snapshot.graph_snapshot_revision_id

            document_source_cache = EducationalDocumentSourceResolutionCache()
            analyses = tuple(
                self._load_accepted_analysis(
                    session,
                    run_id,
                    document_source_cache=document_source_cache,
                )
                for run_id in command.accepted_analysis_run_ids
            )
            structure = self._load_structure_manifest(command.structure_manifest)
            if isinstance(structure, KnowledgeGraphStructureManifestV2):
                try:
                    validate_integrated_science_structure_manifest(structure)
                except CurriculumGraphStructureError as exc:
                    raise KnowledgeGraphPublicationError(
                        "KNOWLEDGE_GRAPH_FRAMEWORK_INVALID",
                        "reviewed curriculum framework does not resolve exactly",
                    ) from exc
            self._validate_item_curriculum_bindings(
                session,
                structure,
                analyses,
                previous_snapshot_revision_id=previous_snapshot_revision_id,
            )
            self._validate_item_elements(session, structure)

        try:
            projection = build_education_graph_projection(analyses, structure)
        except KnowledgeGraphProjectionError as exc:
            raise KnowledgeGraphPublicationError(exc.code, str(exc)) from exc
        projection_files = serialize_education_graph_projection(projection)
        ids = {
            "corpus_id": _typed_id("corpus_", {"corpus_key": command.corpus_key}),
            "graph_id": _typed_id("graph_", {"corpus_key": command.corpus_key}),
            "corpus_revision_id": _typed_id(
                "corpusrev_", {"request_sha256": command.request_sha256}
            ),
            "graph_snapshot_revision_id": _typed_id(
                "graphrev_", {"request_sha256": command.request_sha256}
            ),
            "publication_id": _typed_id("graphpub_", {"request_sha256": command.request_sha256}),
        }
        projection_artifact = self._commit_projection(command, projection_files)
        projections = self._projection_pointers(projection_artifact)
        counts = KnowledgeGraphCounts(
            source_revisions=len(projection.analyses),
            nodes=len(projection.nodes),
            edges=len(projection.edges),
            anchors=projection.anchor_count,
        )
        manifest_value = {
            "graph_id": ids["graph_id"],
            "graph_snapshot_revision_id": ids["graph_snapshot_revision_id"],
            "revision_number": revision_number,
            "previous_graph_snapshot_revision_id": previous_snapshot_revision_id,
            "publisher_version": command.publisher_version,
            "source_revisions": [
                item.source.model_dump(mode="json") for item in projection.analyses
            ],
            "analysis_results": [
                item.accepted_result.model_dump(mode="json") for item in projection.analyses
            ],
            "projections": projections.model_dump(mode="json"),
            "counts": counts.model_dump(mode="json"),
            "snapshot_sha256": projection_files.snapshot_sha256,
            "created_at": command.requested_at,
        }
        manifest: KnowledgeGraphSnapshotContract
        if isinstance(command, PublishKnowledgeGraphSnapshotCommandV4):
            manifest_value["structure_manifest"] = command.structure_manifest.model_dump(
                mode="json"
            )
            manifest = KnowledgeGraphSnapshotManifestV7.model_validate(manifest_value)
            validate_contract(
                "knowledge-graph-snapshot-manifest-v7", manifest.model_dump(mode="json")
            )
        elif isinstance(command, PublishKnowledgeGraphSnapshotCommandV3):
            manifest_value["structure_manifest"] = command.structure_manifest.model_dump(
                mode="json"
            )
            manifest = KnowledgeGraphSnapshotManifestV6.model_validate(manifest_value)
            validate_contract(
                "knowledge-graph-snapshot-manifest-v6", manifest.model_dump(mode="json")
            )
        elif isinstance(command, PublishKnowledgeGraphSnapshotCommandV2):
            manifest_value["structure_manifest"] = command.structure_manifest.model_dump(
                mode="json"
            )
            manifest = KnowledgeGraphSnapshotManifestV5.model_validate(manifest_value)
            validate_contract(
                "knowledge-graph-snapshot-manifest-v5", manifest.model_dump(mode="json")
            )
        elif any(
            isinstance(item.source, EducationalDocumentKnowledgeSourceV4)
            for item in projection.analyses
        ):
            manifest = KnowledgeGraphSnapshotManifestV4.model_validate(manifest_value)
            validate_contract(
                "knowledge-graph-snapshot-manifest-v4", manifest.model_dump(mode="json")
            )
        elif any(
            isinstance(item.source, EducationalDocumentKnowledgeSourceV3)
            for item in projection.analyses
        ):
            manifest = KnowledgeGraphSnapshotManifestV3.model_validate(manifest_value)
            validate_contract(
                "knowledge-graph-snapshot-manifest-v3", manifest.model_dump(mode="json")
            )
        else:
            manifest = KnowledgeGraphSnapshotManifestV2.model_validate(manifest_value)
            validate_contract(
                "knowledge-graph-snapshot-manifest-v2", manifest.model_dump(mode="json")
            )
        manifest_artifact = self._commit_manifest(command, manifest)
        return self._commit_database_snapshot(
            command=command,
            ids=ids,
            expected_revision_number=revision_number,
            previous_corpus_revision_id=previous_corpus_revision_id,
            projection=projection,
            projection_artifact=projection_artifact,
            manifest=manifest,
            manifest_artifact=manifest_artifact,
        )

    def _existing_publication(
        self, command: KnowledgeGraphPublicationCommand
    ) -> KnowledgeGraphPublicationResult | None:
        with self.sessions() as session:
            publication = session.scalar(
                select(KnowledgeGraphPublicationRecord).where(
                    KnowledgeGraphPublicationRecord.idempotency_key == command.idempotency_key
                )
            )
            if publication is None:
                return None
            if publication.request_sha256 != command.request_sha256:
                raise KnowledgeGraphPublicationError(
                    "KNOWLEDGE_GRAPH_IDEMPOTENCY_CONFLICT",
                    "graph publication idempotency key has different input",
                )
            return self._result(session, publication)

    def _load_accepted_analysis(
        self,
        session: Session,
        run_id: str,
        *,
        document_source_cache: EducationalDocumentSourceResolutionCache | None = None,
    ) -> AcceptedAnalysisProposal:
        run = session.get(KnowledgeAnalysisRunRecord, run_id)
        if (
            run is None
            or run.state != "ACCEPTED"
            or run.accepted_result_artifact_id is None
            or run.accepted_result_artifact_revision_id is None
            or run.accepted_result_sha256 is None
            or run.proposal_artifact_id is None
            or run.proposal_artifact_revision_id is None
            or run.proposal_content_set_sha256 is None
        ):
            raise KnowledgeGraphPublicationError(
                "KNOWLEDGE_GRAPH_ANALYSIS_INELIGIBLE",
                "publication source is missing or not accepted",
            )
        try:
            request_version = run.canonical_request.get("schema_version")
            request: KnowledgeAnalysisRequestContract
            if request_version == "knowledge-analysis-request/8.0":
                request = KnowledgeAnalysisRequestV8.model_validate(run.canonical_request)
            elif request_version == "knowledge-analysis-request/7.0":
                request = KnowledgeAnalysisRequestV7.model_validate(run.canonical_request)
            elif request_version == "knowledge-analysis-request/6.0":
                request = KnowledgeAnalysisRequestV6.model_validate(run.canonical_request)
            elif request_version == "knowledge-analysis-request/5.0":
                request = KnowledgeAnalysisRequestV5.model_validate(run.canonical_request)
            elif request_version == "knowledge-analysis-request/4.0":
                request = KnowledgeAnalysisRequestV4.model_validate(run.canonical_request)
            elif request_version == "knowledge-analysis-request/3.0":
                request = KnowledgeAnalysisRequestV3.model_validate(run.canonical_request)
            elif request_version == "knowledge-analysis-request/2.0":
                request = KnowledgeAnalysisRequestV2.model_validate(run.canonical_request)
            else:
                raise ValueError("unsupported accepted analysis request schema")
            resolved_source = self._resolve_source_again(
                session,
                request,
                document_source_cache=document_source_cache,
            )
        except (ValidationError, KnowledgeAnalysisSourceError) as exc:
            raise KnowledgeGraphPublicationError(
                "KNOWLEDGE_GRAPH_SOURCE_POINTER_INVALID",
                "accepted analysis source no longer resolves exactly",
            ) from exc
        if (
            resolved_source != request.source
            or run.request_sha256 != request.request_sha256
            or run.source_artifact_id != request.source.artifact_member.artifact_id
            or run.source_artifact_revision_id
            != request.source.artifact_member.artifact_revision_id
            or run.source_sha256 != request.source.artifact_member.sha256
        ):
            raise KnowledgeGraphPublicationError(
                "KNOWLEDGE_GRAPH_SOURCE_POINTER_INVALID",
                "accepted analysis source pointer is stale",
            )

        accepted_revision = self._exact_artifact_revision(
            session,
            artifact_id=run.accepted_result_artifact_id,
            revision_id=run.accepted_result_artifact_revision_id,
            content_hash=run.accepted_result_sha256,
            logical_artifact_type="knowledge-analysis-accepted-result",
            manifest_artifact_type="knowledge-analysis-accepted-result",
            primary_file="evidence/accepted-result.json",
        )
        stable_identity_multimodal = isinstance(request, KnowledgeAnalysisRequestV8)
        typed_identity_multimodal = isinstance(request, KnowledgeAnalysisRequestV7)
        multimodal_document = isinstance(
            request,
            (KnowledgeAnalysisRequestV6, KnowledgeAnalysisRequestV7, KnowledgeAnalysisRequestV8),
        )
        integrity_document = isinstance(
            request,
            (
                KnowledgeAnalysisRequestV5,
                KnowledgeAnalysisRequestV6,
                KnowledgeAnalysisRequestV7,
                KnowledgeAnalysisRequestV8,
            ),
        )
        endpoint_typed_document = isinstance(
            request,
            (
                KnowledgeAnalysisRequestV4,
                KnowledgeAnalysisRequestV5,
                KnowledgeAnalysisRequestV6,
                KnowledgeAnalysisRequestV7,
                KnowledgeAnalysisRequestV8,
            ),
        )
        document_source = isinstance(
            request,
            (
                KnowledgeAnalysisRequestV3,
                KnowledgeAnalysisRequestV4,
                KnowledgeAnalysisRequestV5,
                KnowledgeAnalysisRequestV6,
                KnowledgeAnalysisRequestV7,
                KnowledgeAnalysisRequestV8,
            ),
        )
        if stable_identity_multimodal:
            accepted_schema_ref = "eom://schemas/knowledge/knowledge-analysis-result/8.0"
        elif typed_identity_multimodal:
            accepted_schema_ref = "eom://schemas/knowledge/knowledge-analysis-result/7.0"
        elif multimodal_document:
            accepted_schema_ref = "eom://schemas/knowledge/knowledge-analysis-result/6.0"
        elif integrity_document:
            accepted_schema_ref = "eom://schemas/knowledge/knowledge-analysis-result/5.0"
        elif endpoint_typed_document:
            accepted_schema_ref = "eom://schemas/knowledge/knowledge-analysis-result/4.0"
        elif document_source:
            accepted_schema_ref = "eom://schemas/knowledge/knowledge-analysis-result/3.0"
        else:
            accepted_schema_ref = "eom://schemas/knowledge/knowledge-analysis-result/2.0"
        accepted_value = self._read_json_member(
            KnowledgeArtifactMemberPointer(
                artifact_id=run.accepted_result_artifact_id,
                artifact_revision_id=run.accepted_result_artifact_revision_id,
                sha256=run.accepted_result_sha256,
                schema_ref=accepted_schema_ref,
                media_type="application/json",
                logical_name="accepted-result.json",
                member_path="evidence/accepted-result.json",
            ),
            max_bytes=1_048_576,
            expected_bytes=accepted_revision.content_bytes,
        )
        accepted: (
            KnowledgeAnalysisResultV2
            | KnowledgeAnalysisResultV3
            | KnowledgeAnalysisResultV4
            | KnowledgeAnalysisResultV5
            | KnowledgeAnalysisResultV6
            | KnowledgeAnalysisResultV7
            | KnowledgeAnalysisResultV8
        )
        database_accepted: (
            KnowledgeAnalysisResultV2
            | KnowledgeAnalysisResultV3
            | KnowledgeAnalysisResultV4
            | KnowledgeAnalysisResultV5
            | KnowledgeAnalysisResultV6
            | KnowledgeAnalysisResultV7
            | KnowledgeAnalysisResultV8
        )
        try:
            if stable_identity_multimodal:
                validate_contract("knowledge-analysis-result-v8", accepted_value)
                accepted = KnowledgeAnalysisResultV8.model_validate(accepted_value)
                validate_contract("knowledge-analysis-result-v8", accepted_revision.result)
                database_accepted = KnowledgeAnalysisResultV8.model_validate(
                    accepted_revision.result
                )
            elif typed_identity_multimodal:
                validate_contract("knowledge-analysis-result-v7", accepted_value)
                accepted = KnowledgeAnalysisResultV7.model_validate(accepted_value)
                validate_contract("knowledge-analysis-result-v7", accepted_revision.result)
                database_accepted = KnowledgeAnalysisResultV7.model_validate(
                    accepted_revision.result
                )
            elif multimodal_document:
                validate_contract("knowledge-analysis-result-v6", accepted_value)
                accepted = KnowledgeAnalysisResultV6.model_validate(accepted_value)
                validate_contract("knowledge-analysis-result-v6", accepted_revision.result)
                database_accepted = KnowledgeAnalysisResultV6.model_validate(
                    accepted_revision.result
                )
            elif integrity_document:
                validate_contract("knowledge-analysis-result-v5", accepted_value)
                accepted = KnowledgeAnalysisResultV5.model_validate(accepted_value)
                validate_contract("knowledge-analysis-result-v5", accepted_revision.result)
                database_accepted = KnowledgeAnalysisResultV5.model_validate(
                    accepted_revision.result
                )
            elif endpoint_typed_document:
                validate_contract("knowledge-analysis-result-v4", accepted_value)
                accepted = KnowledgeAnalysisResultV4.model_validate(accepted_value)
                validate_contract("knowledge-analysis-result-v4", accepted_revision.result)
                database_accepted = KnowledgeAnalysisResultV4.model_validate(
                    accepted_revision.result
                )
            elif document_source:
                validate_contract("knowledge-analysis-result-v3", accepted_value)
                accepted = KnowledgeAnalysisResultV3.model_validate(accepted_value)
                validate_contract("knowledge-analysis-result-v3", accepted_revision.result)
                database_accepted = KnowledgeAnalysisResultV3.model_validate(
                    accepted_revision.result
                )
            else:
                validate_contract("knowledge-analysis-result-v2", accepted_value)
                accepted = KnowledgeAnalysisResultV2.model_validate(accepted_value)
                validate_contract("knowledge-analysis-result-v2", accepted_revision.result)
                database_accepted = KnowledgeAnalysisResultV2.model_validate(
                    accepted_revision.result
                )
        except (ValidationError, ValueError) as exc:
            raise KnowledgeGraphPublicationError(
                "KNOWLEDGE_GRAPH_RESULT_INVALID", "accepted analysis result is invalid"
            ) from exc
        if accepted != database_accepted:
            raise KnowledgeGraphPublicationError(
                "KNOWLEDGE_GRAPH_RESULT_POINTER_INVALID",
                "accepted result database projection differs from Artifact bytes",
            )

        proposal_revision = self._exact_artifact_revision(
            session,
            artifact_id=run.proposal_artifact_id,
            revision_id=run.proposal_artifact_revision_id,
            content_hash=accepted.proposal_receipt.sha256,
            logical_artifact_type="workflow_support",
            manifest_artifact_type="knowledge-analysis-proposal",
            primary_file="normalized/proposal-receipt.json",
        )
        proposal_receipt_value = self._read_json_member(
            KnowledgeArtifactMemberPointer(
                artifact_id=accepted.proposal_receipt.artifact_id,
                artifact_revision_id=accepted.proposal_receipt.artifact_revision_id,
                sha256=accepted.proposal_receipt.sha256,
                schema_ref=accepted.proposal_receipt.schema_ref,
                media_type=accepted.proposal_receipt.media_type,
                logical_name=accepted.proposal_receipt.logical_name,
                member_path=accepted.proposal_receipt.member_path,
            ),
            max_bytes=max(1, accepted.proposal_receipt.bytes),
            expected_bytes=accepted.proposal_receipt.bytes,
        )
        receipt: KnowledgeAnalysisReceiptContract
        database_receipt: KnowledgeAnalysisReceiptContract
        try:
            if stable_identity_multimodal:
                validate_contract("knowledge-analysis-proposal-receipt-v7", proposal_receipt_value)
                receipt = KnowledgeAnalysisProposalReceiptV7.model_validate(proposal_receipt_value)
                validate_contract(
                    "knowledge-analysis-proposal-receipt-v7", proposal_revision.result
                )
                database_receipt = KnowledgeAnalysisProposalReceiptV7.model_validate(
                    proposal_revision.result
                )
            elif typed_identity_multimodal:
                validate_contract("knowledge-analysis-proposal-receipt-v6", proposal_receipt_value)
                receipt = KnowledgeAnalysisProposalReceiptV6.model_validate(proposal_receipt_value)
                validate_contract(
                    "knowledge-analysis-proposal-receipt-v6", proposal_revision.result
                )
                database_receipt = KnowledgeAnalysisProposalReceiptV6.model_validate(
                    proposal_revision.result
                )
            elif multimodal_document:
                validate_contract("knowledge-analysis-proposal-receipt-v5", proposal_receipt_value)
                receipt = KnowledgeAnalysisProposalReceiptV5.model_validate(proposal_receipt_value)
                validate_contract(
                    "knowledge-analysis-proposal-receipt-v5", proposal_revision.result
                )
                database_receipt = KnowledgeAnalysisProposalReceiptV5.model_validate(
                    proposal_revision.result
                )
            elif integrity_document:
                validate_contract("knowledge-analysis-proposal-receipt-v4", proposal_receipt_value)
                receipt = KnowledgeAnalysisProposalReceiptV4.model_validate(proposal_receipt_value)
                validate_contract(
                    "knowledge-analysis-proposal-receipt-v4", proposal_revision.result
                )
                database_receipt = KnowledgeAnalysisProposalReceiptV4.model_validate(
                    proposal_revision.result
                )
            elif endpoint_typed_document:
                validate_contract("knowledge-analysis-proposal-receipt-v3", proposal_receipt_value)
                receipt = KnowledgeAnalysisProposalReceiptV3.model_validate(proposal_receipt_value)
                validate_contract(
                    "knowledge-analysis-proposal-receipt-v3", proposal_revision.result
                )
                database_receipt = KnowledgeAnalysisProposalReceiptV3.model_validate(
                    proposal_revision.result
                )
            elif document_source:
                validate_contract("knowledge-analysis-proposal-receipt-v2", proposal_receipt_value)
                receipt = KnowledgeAnalysisProposalReceiptV2.model_validate(proposal_receipt_value)
                validate_contract(
                    "knowledge-analysis-proposal-receipt-v2", proposal_revision.result
                )
                database_receipt = KnowledgeAnalysisProposalReceiptV2.model_validate(
                    proposal_revision.result
                )
            else:
                validate_contract("knowledge-analysis-proposal-receipt", proposal_receipt_value)
                receipt = KnowledgeAnalysisProposalReceipt.model_validate(proposal_receipt_value)
                validate_contract("knowledge-analysis-proposal-receipt", proposal_revision.result)
                database_receipt = KnowledgeAnalysisProposalReceipt.model_validate(
                    proposal_revision.result
                )
        except (ValidationError, ValueError) as exc:
            raise KnowledgeGraphPublicationError(
                "KNOWLEDGE_GRAPH_PROPOSAL_INVALID", "analysis proposal receipt is invalid"
            ) from exc
        if (
            receipt != database_receipt
            or accepted.proposal_receipt.bytes != proposal_revision.content_bytes
        ):
            raise KnowledgeGraphPublicationError(
                "KNOWLEDGE_GRAPH_PROPOSAL_POINTER_INVALID",
                "analysis proposal receipt bytes differ from its database projection",
            )
        if (
            accepted.analysis_request_id != run.analysis_request_id
            or accepted.analysis_request_sha256 != run.request_sha256
            or accepted.source != request.source
            or accepted.proposal_receipt.artifact_id != run.proposal_artifact_id
            or accepted.proposal_receipt.artifact_revision_id != run.proposal_artifact_revision_id
            or accepted.proposal_content_set_sha256 != run.proposal_content_set_sha256
            or receipt.analysis_request_id != run.analysis_request_id
            or receipt.source != request.source
            or receipt.content_set_sha256 != run.proposal_content_set_sha256
        ):
            raise KnowledgeGraphPublicationError(
                "KNOWLEDGE_GRAPH_PROPOSAL_POINTER_INVALID",
                "accepted result and proposal pointers are inconsistent",
            )
        proposal = self._load_proposal(receipt)
        if any(
            anchor.artifact_revision_id != request.source.artifact_member.artifact_revision_id
            or anchor.member_path != request.source.artifact_member.member_path
            for anchor in proposal.anchors
        ):
            raise KnowledgeGraphPublicationError(
                "KNOWLEDGE_GRAPH_SOURCE_ANCHOR_INVALID",
                "proposal anchor differs from its pinned source",
            )
        return AcceptedAnalysisProposal(
            analysis_run_id=run_id,
            source=request.source,
            accepted_result=KnowledgeArtifactMemberPointer(
                artifact_id=run.accepted_result_artifact_id,
                artifact_revision_id=run.accepted_result_artifact_revision_id,
                sha256=run.accepted_result_sha256,
                schema_ref=accepted_schema_ref,
                media_type="application/json",
                logical_name="accepted-result.json",
                member_path="evidence/accepted-result.json",
            ),
            proposal=proposal,
        )

    def _resolve_source_again(
        self,
        session: Session,
        request: KnowledgeAnalysisRequestContract,
        *,
        document_source_cache: EducationalDocumentSourceResolutionCache | None = None,
    ) -> (
        ContentIntakeKnowledgeSourceV2
        | ApprovedItemKnowledgeSourceV2
        | EducationalDocumentKnowledgeSourceV3
        | EducationalDocumentKnowledgeSourceV4
    ):
        source = request.source
        if isinstance(source, ContentIntakeKnowledgeSourceV2):
            return resolve_content_intake_source(
                session,
                intake_batch_id=source.intake_batch_id,
                source_file_id=source.source_file_id,
                source_class=source.source_class,
            )
        if isinstance(source, ApprovedItemKnowledgeSourceV2):
            return resolve_approved_item_source(
                session,
                item_revision_id=source.item_revision_id,
                source_class=source.source_class,
            )
        return resolve_educational_document_source(
            session,
            self.artifacts,
            document_revision_id=source.document_revision_id,
            source_class=source.source_class,
            first_physical_page=source.first_physical_page,
            last_physical_page=source.last_physical_page,
            curriculum_unit_keys=source.curriculum_unit_keys,
            cache=document_source_cache,
        )

    @staticmethod
    def _exact_artifact_revision(
        session: Session,
        *,
        artifact_id: str,
        revision_id: str,
        content_hash: str,
        logical_artifact_type: str,
        manifest_artifact_type: str,
        primary_file: str,
    ) -> ArtifactRevisionRecord:
        logical = session.get(ArtifactRecord, artifact_id)
        revision = session.get(ArtifactRevisionRecord, revision_id)
        job = session.get(JobRecord, revision.job_id) if revision is not None else None
        if (
            logical is None
            or revision is None
            or job is None
            or not logical.approved
            or not revision.approved
            or job.status != "SUCCEEDED"
            or job.error_code is not None
            or job.logical_artifact_id != artifact_id
            or job.revision_id != revision_id
            or logical.job_id != job.job_id
            or revision.job_id != job.job_id
            or logical.artifact_type != logical_artifact_type
            or job.task_type != logical_artifact_type
            or revision.logical_artifact_id != artifact_id
            or revision.content_hash != content_hash
            or revision.manifest.get("artifact_type") != manifest_artifact_type
            or revision.manifest.get("primary_file") != primary_file
        ):
            raise KnowledgeGraphPublicationError(
                "KNOWLEDGE_GRAPH_ARTIFACT_POINTER_INVALID",
                "knowledge graph source Artifact pointer does not resolve",
            )
        return revision

    def _read_json_member(
        self,
        pointer: KnowledgeArtifactMemberPointer,
        *,
        max_bytes: int,
        expected_bytes: int | None = None,
    ) -> dict[str, Any]:
        try:
            raw = self.artifacts.read_member(
                artifact_id=pointer.artifact_id,
                revision_id=pointer.artifact_revision_id,
                member_path=pointer.member_path,
                sha256=pointer.sha256,
                media_type=pointer.media_type,
                schema_ref=pointer.schema_ref,
                max_bytes=max_bytes,
            )
            if expected_bytes is not None and len(raw) != expected_bytes:
                raise ValueError("JSON member byte length differs from its pointer")
            value: object = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError("JSON member is not an object")
            return value
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
            raise KnowledgeGraphPublicationError(
                "KNOWLEDGE_GRAPH_ARTIFACT_POINTER_INVALID",
                "knowledge graph JSON Artifact member is invalid",
            ) from exc

    def _load_proposal(
        self, receipt: KnowledgeAnalysisReceiptContract
    ) -> (
        KnowledgeAnalysisWorkerProposal
        | KnowledgeAnalysisWorkerProposalV2
        | KnowledgeAnalysisWorkerProposalV3
        | KnowledgeAnalysisWorkerProposalV4
        | KnowledgeAnalysisWorkerProposalV5
        | KnowledgeAnalysisWorkerProposalV6
    ):
        try:
            return resolve_knowledge_analysis_proposal(self.artifacts, receipt)
        except KnowledgeProposalResolutionError as exc:
            code = (
                "KNOWLEDGE_GRAPH_PROPOSAL_POINTER_INVALID"
                if exc.kind == "POINTER_INVALID"
                else "KNOWLEDGE_GRAPH_PROPOSAL_INVALID"
            )
            raise KnowledgeGraphPublicationError(
                code, "analysis proposal cannot be resolved or validated"
            ) from exc

    def _load_structure_manifest(
        self, pointer: KnowledgeArtifactMemberPointer | None
    ) -> KnowledgeGraphStructureContract | None:
        if pointer is None:
            return None
        value = self._read_json_member(pointer, max_bytes=8 * 1024 * 1024)
        try:
            if pointer.schema_ref.endswith("/4.0"):
                validate_contract("knowledge-graph-structure-manifest-v4", value)
                return KnowledgeGraphStructureManifestV4.model_validate(value)
            if pointer.schema_ref.endswith("/3.0"):
                validate_contract("knowledge-graph-structure-manifest-v3", value)
                return KnowledgeGraphStructureManifestV3.model_validate(value)
            if pointer.schema_ref.endswith("/2.0"):
                validate_contract("knowledge-graph-structure-manifest-v2", value)
                return KnowledgeGraphStructureManifestV2.model_validate(value)
            validate_contract("knowledge-graph-structure-manifest", value)
            return KnowledgeGraphStructureManifest.model_validate(value)
        except (ValidationError, ValueError) as exc:
            raise KnowledgeGraphPublicationError(
                "KNOWLEDGE_GRAPH_STRUCTURE_INVALID",
                "reviewed graph structure manifest is invalid",
            ) from exc

    def _validate_item_elements(
        self, session: Session, structure: KnowledgeGraphStructureContract | None
    ) -> None:
        if structure is None:
            return
        reviewer = session.get(OperatorRecord, structure.reviewed_by_operator_id)
        if reviewer is None or reviewer.status != "ACTIVE":
            raise KnowledgeGraphPublicationError(
                "KNOWLEDGE_GRAPH_REVIEWER_INVALID",
                "structure manifest reviewer is absent or inactive",
            )
        content_by_revision: dict[str, AssessmentItemContent] = {}
        for binding in structure.item_elements:
            revision = session.get(ItemRevisionRecord, binding.item_revision_id)
            item = session.get(ItemRecord, binding.item_id)
            components = tuple(
                session.scalars(
                    select(ItemComponentRecord).where(
                        ItemComponentRecord.item_revision_id == binding.item_revision_id,
                        ItemComponentRecord.component_type == "ITEM_CONTENT",
                        ItemComponentRecord.ordinal == 0,
                    )
                )
            )
            if (
                revision is None
                or item is None
                or revision.item_id != binding.item_id
                or revision.revision_state != "APPROVED"
                or len(components) != 1
            ):
                raise KnowledgeGraphPublicationError(
                    "KNOWLEDGE_GRAPH_ITEM_POINTER_INVALID",
                    "Item element revision pointer does not resolve to approved content",
                )
            component = components[0]
            if (
                component.artifact_id != binding.item_content_artifact_id
                or component.artifact_revision_id != binding.item_content_artifact_revision_id
                or component.sha256 != binding.item_content_sha256
                or component.schema_ref != binding.schema_ref
                or component.media_type != "application/json"
                or not component.required
            ):
                raise KnowledgeGraphPublicationError(
                    "KNOWLEDGE_GRAPH_ITEM_POINTER_INVALID",
                    "Item element content pointer is stale",
                )
            content = content_by_revision.get(binding.item_revision_id)
            if content is None:
                try:
                    loaded_content = self.registry.load_item_content(binding.item_revision_id)
                except RegistryError as exc:
                    raise KnowledgeGraphPublicationError(
                        "KNOWLEDGE_GRAPH_ITEM_POINTER_INVALID",
                        "Item element canonical content is invalid",
                    ) from exc
                if not isinstance(loaded_content, AssessmentItemContent):
                    raise KnowledgeGraphPublicationError(
                        "KNOWLEDGE_GRAPH_ITEM_POINTER_INVALID",
                        "Item element bindings require assessment item content schema 1.0",
                    )
                content = loaded_content
                content_by_revision[binding.item_revision_id] = content
            answer_bearing = self._resolve_item_element(
                content, binding.element_kind, binding.element_id
            )
            if answer_bearing is None or answer_bearing != binding.answer_bearing:
                raise KnowledgeGraphPublicationError(
                    "KNOWLEDGE_GRAPH_ITEM_ELEMENT_INVALID",
                    "Item element identity or answer-bearing classification differs",
                )

    @staticmethod
    def _snapshot_ancestor_ids(
        session: Session, current_snapshot_revision_id: str
    ) -> frozenset[str]:
        """Validate and return one bounded immutable Graph revision chain."""

        seen: set[str] = set()
        cursor: str | None = current_snapshot_revision_id
        graph_id: str | None = None
        expected_revision_number: int | None = None
        while cursor is not None:
            if cursor in seen or len(seen) >= 10000:
                raise KnowledgeGraphPublicationError(
                    "KNOWLEDGE_GRAPH_ANCESTRY_INVALID",
                    "Graph snapshot ancestry is cyclic or exceeds the publication bound",
                )
            snapshot = session.get(KnowledgeGraphSnapshotRecord, cursor)
            if (
                snapshot is None
                or snapshot.state != "PUBLISHED"
                or (graph_id is not None and snapshot.graph_id != graph_id)
                or (
                    expected_revision_number is not None
                    and snapshot.revision_number != expected_revision_number
                )
                or (snapshot.revision_number == 1)
                != (snapshot.previous_graph_snapshot_revision_id is None)
            ):
                raise KnowledgeGraphPublicationError(
                    "KNOWLEDGE_GRAPH_ANCESTRY_INVALID",
                    "Graph snapshot ancestry is missing or non-contiguous",
                )
            graph_id = snapshot.graph_id
            expected_revision_number = snapshot.revision_number - 1
            seen.add(cursor)
            cursor = snapshot.previous_graph_snapshot_revision_id
        return frozenset(seen)

    def _validate_item_curriculum_bindings(
        self,
        session: Session,
        structure: KnowledgeGraphStructureContract | None,
        analyses: tuple[AcceptedAnalysisProposal, ...],
        *,
        previous_snapshot_revision_id: str | None,
    ) -> None:
        """Validate every reviewed and automatic Item binding against one ancestry snapshot."""

        if not isinstance(
            structure, (KnowledgeGraphStructureManifestV3, KnowledgeGraphStructureManifestV4)
        ):
            return
        if previous_snapshot_revision_id is None:
            raise KnowledgeGraphPublicationError(
                "KNOWLEDGE_GRAPH_ITEM_ALIGNMENT_PRIOR_MISSING",
                "Item curriculum alignment requires a prior Graph snapshot",
            )
        ancestor_snapshot_ids = self._snapshot_ancestor_ids(session, previous_snapshot_revision_id)
        self._validate_approved_item_curriculum_bindings(
            session,
            structure,
            analyses,
            expected_snapshot_revision_id=previous_snapshot_revision_id,
            ancestor_snapshot_ids=ancestor_snapshot_ids,
        )
        if isinstance(structure, KnowledgeGraphStructureManifestV4):
            self._validate_automatic_item_curriculum_bindings(
                session,
                structure,
                analyses,
                expected_snapshot_revision_id=previous_snapshot_revision_id,
                ancestor_snapshot_ids=ancestor_snapshot_ids,
            )

    def _validate_approved_item_curriculum_bindings(
        self,
        session: Session,
        structure: KnowledgeGraphStructureManifestV3 | KnowledgeGraphStructureManifestV4,
        analyses: tuple[AcceptedAnalysisProposal, ...],
        *,
        expected_snapshot_revision_id: str | None,
        ancestor_snapshot_ids: frozenset[str],
    ) -> None:
        """Resolve every reviewed Item alignment through its immutable evidence pointers."""

        if expected_snapshot_revision_id is None:
            raise KnowledgeGraphPublicationError(
                "KNOWLEDGE_GRAPH_ITEM_ALIGNMENT_PRIOR_MISSING",
                "approved Item alignment requires a prior graph snapshot",
            )
        analysis_by_id = {analysis.analysis_run_id: analysis for analysis in analyses}
        expected_item_runs = {
            analysis.analysis_run_id
            for analysis in analyses
            if isinstance(analysis.source, ApprovedItemKnowledgeSourceV2)
        }
        bindings = structure.approved_item_curriculum_bindings
        reviewed_run_ids = {binding.analysis_run_id for binding in bindings}
        if (
            reviewed_run_ids.union(
                binding.analysis_run_id
                for binding in (
                    structure.automatic_item_curriculum_bindings
                    if isinstance(structure, KnowledgeGraphStructureManifestV4)
                    else ()
                )
            )
            != expected_item_runs
        ):
            raise KnowledgeGraphPublicationError(
                "KNOWLEDGE_GRAPH_ITEM_ALIGNMENT_COVERAGE_INVALID",
                "reviewed and automatic Item alignments must cover Item source runs exactly",
            )
        for binding in bindings:
            analysis = analysis_by_id[binding.analysis_run_id]
            source = analysis.source
            reviewer = session.get(OperatorRecord, binding.reviewed_by_operator_id)
            if (
                not isinstance(source, ApprovedItemKnowledgeSourceV2)
                or reviewer is None
                or reviewer.status != "ACTIVE"
                or source.item_id != binding.item_id
                or source.item_revision_id != binding.item_revision_id
                or analysis.accepted_result != binding.accepted_result
                or binding.prior_graph_snapshot_revision_id not in ancestor_snapshot_ids
            ):
                raise KnowledgeGraphPublicationError(
                    "KNOWLEDGE_GRAPH_ITEM_ALIGNMENT_SOURCE_INVALID",
                    "approved Item alignment differs from its accepted analysis source",
                )
            bundle = session.get(EvidenceBundleRecord, binding.evidence_bundle_id)
            revision = session.get(
                EvidenceBundleRevisionRecord, binding.evidence_bundle_revision_id
            )
            request = session.get(EducationRetrievalRequestRecord, binding.retrieval_request_id)
            entries = tuple(
                session.scalars(
                    select(EvidenceBundleEntryRecord).where(
                        EvidenceBundleEntryRecord.evidence_bundle_revision_id
                        == binding.evidence_bundle_revision_id
                    )
                )
            )
            manifest = binding.evidence_manifest
            if (
                bundle is None
                or revision is None
                or request is None
                or bundle.current_revision_id != binding.evidence_bundle_revision_id
                or bundle.retrieval_request_id != binding.retrieval_request_id
                or revision.evidence_bundle_id != binding.evidence_bundle_id
                or revision.retrieval_request_id != binding.retrieval_request_id
                or revision.graph_snapshot_revision_id != binding.prior_graph_snapshot_revision_id
                or revision.state != "PUBLISHED"
                or revision.manifest_artifact_id != manifest.artifact_id
                or revision.manifest_artifact_revision_id != manifest.artifact_revision_id
                or request.request_sha256 != binding.retrieval_request_sha256
                or request.graph_snapshot_revision_id != binding.prior_graph_snapshot_revision_id
                or request.state != "PUBLISHED"
                or not entries
            ):
                raise KnowledgeGraphPublicationError(
                    "KNOWLEDGE_GRAPH_ITEM_ALIGNMENT_EVIDENCE_INVALID",
                    "approved Item alignment Evidence Bundle does not resolve exactly",
                )
            self._exact_artifact_revision(
                session,
                artifact_id=manifest.artifact_id,
                revision_id=manifest.artifact_revision_id,
                content_hash=manifest.sha256,
                logical_artifact_type="evidence-bundle-manifest",
                manifest_artifact_type="evidence-bundle-manifest",
                primary_file="evidence/manifest.json",
            )
            evidence_manifest_value = self._read_json_member(
                manifest,
                max_bytes=8 * 1024 * 1024,
            )
            try:
                validate_contract("evidence-bundle-manifest-v4", evidence_manifest_value)
                evidence_manifest = EvidenceBundleManifestV4.model_validate(evidence_manifest_value)
            except (ValidationError, ValueError) as exc:
                raise KnowledgeGraphPublicationError(
                    "KNOWLEDGE_GRAPH_ITEM_ALIGNMENT_EVIDENCE_INVALID",
                    "approved Item alignment Evidence Bundle manifest is invalid",
                ) from exc
            if (
                revision.manifest_sha256 != evidence_manifest.manifest_sha256
                or evidence_manifest.evidence_bundle_id != binding.evidence_bundle_id
                or evidence_manifest.evidence_bundle_revision_id
                != binding.evidence_bundle_revision_id
                or evidence_manifest.retrieval_request_id != binding.retrieval_request_id
                or evidence_manifest.retrieval_request_sha256 != binding.retrieval_request_sha256
                or evidence_manifest.graph_snapshot.graph_snapshot_revision_id
                != binding.prior_graph_snapshot_revision_id
                or {entry.evidence_id for entry in evidence_manifest.entries}
                != {entry.evidence_id for entry in entries}
            ):
                raise KnowledgeGraphPublicationError(
                    "KNOWLEDGE_GRAPH_ITEM_ALIGNMENT_EVIDENCE_INVALID",
                    "approved Item alignment Evidence Bundle manifest differs from its records",
                )
            evidence_node_ids = {node_id for entry in entries for node_id in entry.graph_node_ids}
            if not set(binding.evidence_node_ids).issubset(evidence_node_ids):
                raise KnowledgeGraphPublicationError(
                    "KNOWLEDGE_GRAPH_ITEM_ALIGNMENT_EVIDENCE_INVALID",
                    "approved Item alignment nodes are absent from the pinned Evidence Bundle",
                )
            resolved_nodes = set(
                session.scalars(
                    select(KnowledgeNodeRecord.node_id).where(
                        KnowledgeNodeRecord.graph_snapshot_revision_id
                        == binding.prior_graph_snapshot_revision_id,
                        KnowledgeNodeRecord.node_id.in_(binding.evidence_node_ids),
                    )
                )
            )
            target_units = tuple(
                session.scalars(
                    select(CurriculumUnitRecord).where(
                        CurriculumUnitRecord.graph_snapshot_revision_id
                        == binding.prior_graph_snapshot_revision_id,
                        CurriculumUnitRecord.curriculum_unit_id.in_(binding.curriculum_unit_ids),
                    )
                )
            )
            if resolved_nodes != set(binding.evidence_node_ids) or {
                unit.curriculum_unit_id for unit in target_units
            } != set(binding.curriculum_unit_ids):
                raise KnowledgeGraphPublicationError(
                    "KNOWLEDGE_GRAPH_ITEM_ALIGNMENT_TARGET_INVALID",
                    "approved Item alignment graph nodes or units do not resolve",
                )
            target_node_ids = {unit.node_id for unit in target_units}
            reachable = set(binding.evidence_node_ids)
            frontier = set(reachable)
            for _depth in range(3):
                if target_node_ids.issubset(reachable) or not frontier:
                    break
                rows = session.execute(
                    select(KnowledgeEdgeRecord.from_node_id, KnowledgeEdgeRecord.to_node_id)
                    .where(
                        KnowledgeEdgeRecord.graph_snapshot_revision_id
                        == binding.prior_graph_snapshot_revision_id,
                        (
                            KnowledgeEdgeRecord.from_node_id.in_(frontier)
                            | KnowledgeEdgeRecord.to_node_id.in_(frontier)
                        ),
                    )
                    .order_by(KnowledgeEdgeRecord.edge_id)
                    .limit(max(256, len(frontier) * 64))
                )
                next_frontier = {
                    node_id
                    for from_node_id, to_node_id in rows
                    for node_id in (from_node_id, to_node_id)
                    if node_id not in reachable
                }
                reachable.update(next_frontier)
                frontier = next_frontier
            if not target_node_ids.issubset(reachable):
                raise KnowledgeGraphPublicationError(
                    "KNOWLEDGE_GRAPH_ITEM_ALIGNMENT_UNSUPPORTED",
                    "reviewed curriculum unit lacks a bounded path from pinned Graph RAG evidence",
                )

    def _validate_automatic_item_curriculum_bindings(
        self,
        session: Session,
        structure: KnowledgeGraphStructureManifestV4,
        analyses: tuple[AcceptedAnalysisProposal, ...],
        *,
        expected_snapshot_revision_id: str | None,
        ancestor_snapshot_ids: frozenset[str],
    ) -> None:
        """Recompute every policy-derived Item alignment from its immutable evidence."""

        if expected_snapshot_revision_id is None:
            raise KnowledgeGraphPublicationError(
                "KNOWLEDGE_GRAPH_ITEM_ALIGNMENT_PRIOR_MISSING",
                "automatic Item alignment requires a prior Graph snapshot",
            )
        analysis_by_id = {analysis.analysis_run_id: analysis for analysis in analyses}
        for binding in structure.automatic_item_curriculum_bindings:
            try:
                alignment_policy = automatic_item_alignment_policy(binding.alignment_policy_version)
            except AutomaticCurriculumAlignmentError as exc:
                raise KnowledgeGraphPublicationError(exc.code, str(exc)) from exc
            analysis = analysis_by_id.get(binding.analysis_run_id)
            source = analysis.source if analysis is not None else None
            requester = session.get(OperatorRecord, binding.requested_by_operator_id)
            if (
                analysis is None
                or not isinstance(source, ApprovedItemKnowledgeSourceV2)
                or requester is None
                or requester.status != "ACTIVE"
                or source.item_id != binding.item_id
                or source.item_revision_id != binding.item_revision_id
                or analysis.accepted_result != binding.accepted_result
                or binding.prior_graph_snapshot_revision_id not in ancestor_snapshot_ids
                or binding.alignment_policy_sha256 != alignment_policy.sha256
            ):
                raise KnowledgeGraphPublicationError(
                    "KNOWLEDGE_GRAPH_AUTOMATIC_ALIGNMENT_SOURCE_INVALID",
                    "automatic Item alignment differs from its accepted source or policy",
                )
            bundle = session.get(EvidenceBundleRecord, binding.evidence_bundle_id)
            revision = session.get(
                EvidenceBundleRevisionRecord, binding.evidence_bundle_revision_id
            )
            request = session.get(EducationRetrievalRequestRecord, binding.retrieval_request_id)
            policy = (
                session.get(
                    EducationRetrievalAccessPolicyRevisionRecord, request.access_policy_revision_id
                )
                if request is not None
                else None
            )
            entries = tuple(
                session.scalars(
                    select(EvidenceBundleEntryRecord)
                    .where(
                        EvidenceBundleEntryRecord.evidence_bundle_revision_id
                        == binding.evidence_bundle_revision_id
                    )
                    .order_by(EvidenceBundleEntryRecord.evidence_id)
                )
            )
            try:
                validate_contract(
                    "education-retrieval-access-policy",
                    policy.canonical_document if policy is not None else {},
                )
                policy_model = EducationRetrievalAccessPolicy.model_validate(
                    policy.canonical_document if policy is not None else {}
                )
                validate_contract(
                    "education-retrieval-request-v2",
                    request.canonical_request if request is not None else {},
                )
                request_model = EducationRetrievalRequestV2.model_validate(
                    request.canonical_request if request is not None else {}
                )
            except (JsonSchemaValidationError, ValidationError) as exc:
                raise KnowledgeGraphPublicationError(
                    "KNOWLEDGE_GRAPH_AUTOMATIC_ALIGNMENT_EVIDENCE_INVALID",
                    "automatic alignment retrieval request is invalid",
                ) from exc
            requested_budget = request_model.evidence_budget
            maximum_budget = policy_model.maximum_budget
            budget_exceeds_policy = any(
                requested > maximum
                for requested, maximum in (
                    (requested_budget.max_documents, maximum_budget.max_documents),
                    (requested_budget.max_item_revisions, maximum_budget.max_item_revisions),
                    (requested_budget.max_graph_nodes, maximum_budget.max_graph_nodes),
                    (requested_budget.max_claims, maximum_budget.max_claims),
                    (requested_budget.max_context_tokens, maximum_budget.max_context_tokens),
                )
            )
            try:
                expected_topics = automatic_item_alignment_topic_keys(
                    (str(node.node_type), node.stable_key) for node in analysis.proposal.nodes
                )
            except AutomaticCurriculumAlignmentError as exc:
                raise KnowledgeGraphPublicationError(exc.code, str(exc)) from exc
            if (
                bundle is None
                or revision is None
                or request is None
                or policy is None
                or policy.state != "RELEASED"
                or policy.schema_version != "education-retrieval-access-policy/1.0"
                or policy.content_sha256 != request_model.access_policy_sha256
                or policy_model.access_policy_revision_id != request_model.access_policy_revision_id
                or policy_model.content_sha256 != policy.content_sha256
                or request_model.query_kind not in policy_model.allowed_query_kinds
                or request_model.requester_role not in policy_model.allowed_requester_roles
                or not set(request_model.source_classes).issubset(
                    policy_model.allowed_source_classes
                )
                or budget_exceeds_policy
                or bundle.current_revision_id != binding.evidence_bundle_revision_id
                or bundle.retrieval_request_id != binding.retrieval_request_id
                or bundle.created_by_operator_id != binding.requested_by_operator_id
                or revision.evidence_bundle_id != binding.evidence_bundle_id
                or revision.retrieval_request_id != binding.retrieval_request_id
                or revision.graph_snapshot_revision_id != binding.prior_graph_snapshot_revision_id
                or revision.access_policy_revision_id != request_model.access_policy_revision_id
                or revision.requester_permissions_sha256
                != request_model.requester_permissions_sha256
                or revision.created_by_operator_id != binding.requested_by_operator_id
                or revision.state != "PUBLISHED"
                or revision.manifest_artifact_id != binding.evidence_manifest.artifact_id
                or revision.manifest_artifact_revision_id
                != binding.evidence_manifest.artifact_revision_id
                or request.request_sha256 != binding.retrieval_request_sha256
                or request.state != "PUBLISHED"
                or request.graph_snapshot_revision_id != binding.prior_graph_snapshot_revision_id
                or request.access_policy_revision_id != request_model.access_policy_revision_id
                or request.query_kind != request_model.query_kind
                or request.requester_role != request_model.requester_role
                or request.requester_operator_id != request_model.requester_operator_id
                or request.requester_permissions_sha256
                != request_model.requester_permissions_sha256
                or request_model.request_sha256 != binding.retrieval_request_sha256
                or request_model.graph_snapshot.graph_snapshot_revision_id
                != binding.prior_graph_snapshot_revision_id
                or request_model.query_kind != "ITEM_PREPARATION"
                or request_model.curriculum_scope is not None
                or request_model.topic_keys != expected_topics
                or request_model.target_item_revision_id is not None
                or request_model.required_item_elements
                or request_model.source_classes != AUTOMATIC_ITEM_ALIGNMENT_SOURCE_CLASSES
                or request_model.evidence_budget.model_dump(mode="json")
                != AUTOMATIC_ITEM_ALIGNMENT_EVIDENCE_BUDGET
                or request_model.requester_role != "ADMIN"
                or request_model.requester_permission_keys
                != AUTOMATIC_ITEM_ALIGNMENT_PERMISSION_KEYS
                or request_model.requester_operator_id != binding.requested_by_operator_id
                or not entries
            ):
                raise KnowledgeGraphPublicationError(
                    "KNOWLEDGE_GRAPH_AUTOMATIC_ALIGNMENT_EVIDENCE_INVALID",
                    "automatic Item alignment Evidence Bundle does not resolve exactly",
                )
            self._exact_artifact_revision(
                session,
                artifact_id=binding.evidence_manifest.artifact_id,
                revision_id=binding.evidence_manifest.artifact_revision_id,
                content_hash=binding.evidence_manifest.sha256,
                logical_artifact_type="evidence-bundle-manifest",
                manifest_artifact_type="evidence-bundle-manifest",
                primary_file="evidence/manifest.json",
            )
            evidence_manifest_value = self._read_json_member(
                binding.evidence_manifest,
                max_bytes=8 * 1024 * 1024,
            )
            evidence_manifest: (
                EvidenceBundleManifestV2 | EvidenceBundleManifestV3 | EvidenceBundleManifestV4
            )
            try:
                if binding.evidence_manifest.schema_ref.endswith("/4.0"):
                    validate_contract("evidence-bundle-manifest-v4", evidence_manifest_value)
                    evidence_manifest = EvidenceBundleManifestV4.model_validate(
                        evidence_manifest_value
                    )
                elif binding.evidence_manifest.schema_ref.endswith("/3.0"):
                    validate_contract("evidence-bundle-manifest-v3", evidence_manifest_value)
                    evidence_manifest = EvidenceBundleManifestV3.model_validate(
                        evidence_manifest_value
                    )
                else:
                    validate_contract("evidence-bundle-manifest-v2", evidence_manifest_value)
                    evidence_manifest = EvidenceBundleManifestV2.model_validate(
                        evidence_manifest_value
                    )
            except (ValidationError, ValueError) as exc:
                raise KnowledgeGraphPublicationError(
                    "KNOWLEDGE_GRAPH_AUTOMATIC_ALIGNMENT_EVIDENCE_INVALID",
                    "automatic alignment Evidence Bundle manifest is invalid",
                ) from exc
            manifest_entries = {
                entry.evidence_id: cast(Any, entry) for entry in evidence_manifest.entries
            }
            rows_match_manifest = len(manifest_entries) == len(entries)
            for entry_record in entries:
                manifest_entry = manifest_entries.get(entry_record.evidence_id)
                source = getattr(manifest_entry, "source", None)
                member = getattr(source, "artifact_member", None)
                if (
                    manifest_entry is None
                    or entry_record.evidence_kind != manifest_entry.evidence_kind
                    or entry_record.evidence_use != manifest_entry.use
                    or entry_record.source_kind != getattr(source, "source_kind", None)
                    or entry_record.source_class != getattr(source, "source_class", None)
                    or entry_record.intake_batch_id != getattr(source, "intake_batch_id", None)
                    or entry_record.source_file_id != getattr(source, "source_file_id", None)
                    or entry_record.item_id != getattr(source, "item_id", None)
                    or entry_record.item_revision_id != getattr(source, "item_revision_id", None)
                    or entry_record.educational_document_id != getattr(source, "document_id", None)
                    or entry_record.educational_document_revision_id
                    != getattr(source, "document_revision_id", None)
                    or entry_record.source_artifact_id != getattr(member, "artifact_id", None)
                    or entry_record.source_artifact_revision_id
                    != getattr(member, "artifact_revision_id", None)
                    or entry_record.source_member_path != getattr(member, "member_path", None)
                    or entry_record.source_sha256 != getattr(member, "sha256", None)
                    or entry_record.source_bytes != getattr(member, "bytes", None)
                    or entry_record.source_schema_ref != getattr(member, "schema_ref", None)
                    or entry_record.source_media_type != getattr(member, "media_type", None)
                    or entry_record.source_logical_name != getattr(member, "logical_name", None)
                    or tuple(entry_record.graph_node_ids) != manifest_entry.graph_node_ids
                    or tuple(entry_record.anchor_ids) != manifest_entry.anchor_ids
                    or entry_record.relevance_milli != manifest_entry.relevance_milli
                    or entry_record.answer_bearing != manifest_entry.answer_bearing
                ):
                    rows_match_manifest = False
                    break
            evidence_node_ids = tuple(
                sorted({node_id for entry in entries for node_id in entry.graph_node_ids})
            )
            if (
                revision.manifest_sha256 != evidence_manifest.manifest_sha256
                or evidence_manifest.evidence_bundle_id != binding.evidence_bundle_id
                or evidence_manifest.evidence_bundle_revision_id
                != binding.evidence_bundle_revision_id
                or evidence_manifest.retrieval_request_id != binding.retrieval_request_id
                or evidence_manifest.retrieval_request_sha256 != binding.retrieval_request_sha256
                or evidence_manifest.graph_snapshot.graph_snapshot_revision_id
                != binding.prior_graph_snapshot_revision_id
                or evidence_manifest.access_policy_revision_id
                != request_model.access_policy_revision_id
                or evidence_manifest.access_policy_sha256 != request_model.access_policy_sha256
                or evidence_manifest.requester_permissions_sha256
                != request_model.requester_permissions_sha256
                or evidence_manifest.revision_number != revision.revision_number
                or evidence_manifest.budget.document_count != revision.document_count
                or evidence_manifest.budget.item_revision_count != revision.item_revision_count
                or evidence_manifest.budget.graph_node_count != revision.graph_node_count
                or evidence_manifest.budget.claim_count != revision.claim_count
                or evidence_manifest.budget.estimated_context_tokens
                != revision.estimated_context_tokens
                or not rows_match_manifest
                or {entry.evidence_id for entry in evidence_manifest.entries}
                != {entry.evidence_id for entry in entries}
                or binding.evidence_node_ids != evidence_node_ids
            ):
                raise KnowledgeGraphPublicationError(
                    "KNOWLEDGE_GRAPH_AUTOMATIC_ALIGNMENT_EVIDENCE_INVALID",
                    "automatic alignment Evidence Bundle differs from its records",
                )
            try:
                expected_units = derive_automatic_item_curriculum_unit_ids(
                    session,
                    graph_snapshot_revision_id=binding.prior_graph_snapshot_revision_id,
                    evidence_node_ids=evidence_node_ids,
                    alignment_policy_version=binding.alignment_policy_version,
                )
            except AutomaticCurriculumAlignmentError as exc:
                raise KnowledgeGraphPublicationError(exc.code, str(exc)) from exc
            if binding.curriculum_unit_ids != expected_units:
                raise KnowledgeGraphPublicationError(
                    "KNOWLEDGE_GRAPH_AUTOMATIC_ALIGNMENT_TARGET_INVALID",
                    "automatic curriculum units differ from the pinned policy result",
                )

    @staticmethod
    def _resolve_item_element(
        content: AssessmentItemContent, element_kind: str, element_id: str
    ) -> bool | None:
        if element_kind in {"paragraph", "table", "image", "equation", "statement_set"}:
            for block in content.body:
                if block.type == element_kind and block.block_id == element_id:
                    return element_kind == "statement_set"
            return None
        if element_kind == "statement":
            for block in content.body:
                statements = getattr(block, "statements", ())
                if any(item.statement_id == element_id for item in statements):
                    return True
            return None
        if element_kind == "choice":
            choices = getattr(content.interaction, "choices", ())
            if any(item.choice_id == element_id for item in choices):
                return element_id in content.solution.correct_choice_ids
        return None

    def _commit_projection(
        self,
        command: KnowledgeGraphPublicationCommand,
        files: EducationGraphProjectionFiles,
    ) -> CatalogArtifact:
        document_projection = any(
            metadata.get("schema_ref")
            in {
                "eom://schemas/knowledge/knowledge-graph-projection/2.0",
                "eom://schemas/knowledge/knowledge-graph-projection/3.0",
            }
            for metadata in files.metadata.values()
        )
        try:
            with tempfile.TemporaryDirectory(
                prefix="knowledge-graph-projection.", dir=self.settings.staging_root
            ) as raw_directory:
                root = Path(raw_directory)
                sources: dict[str, Path] = {}
                for member_path, payload in files.members.items():
                    source = root / Path(member_path).name
                    source.write_bytes(payload)
                    source.chmod(0o640)
                    sources[member_path] = source
                return self.artifacts.commit_file_set(
                    files=sources,
                    primary_file="projections/nodes.jsonl",
                    artifact_type="knowledge-graph-projection",
                    idempotency_key=f"knowledge-graph-projection:{command.request_sha256}",
                    request={
                        "request_sha256": command.request_sha256,
                        "accepted_analysis_run_ids": list(command.accepted_analysis_run_ids),
                    },
                    result={
                        "snapshot_sha256": files.snapshot_sha256,
                        "member_count": len(files.members),
                    },
                    file_metadata=files.metadata,
                    manifest_version="knowledge-graph-projection-file-set/1.0",
                    protocol_version=(
                        KNOWLEDGE_GRAPH_AUTOMATIC_ITEM_CATALOG_PROTOCOL
                        if isinstance(command, PublishKnowledgeGraphSnapshotCommandV4)
                        else (
                            KNOWLEDGE_GRAPH_APPROVED_ITEM_CATALOG_PROTOCOL
                            if isinstance(command, PublishKnowledgeGraphSnapshotCommandV3)
                            else (
                                KNOWLEDGE_GRAPH_REVIEWED_CURRICULUM_CATALOG_PROTOCOL
                                if isinstance(command, PublishKnowledgeGraphSnapshotCommandV2)
                                else (
                                    KNOWLEDGE_GRAPH_DOCUMENT_CATALOG_PROTOCOL
                                    if document_projection
                                    else KNOWLEDGE_GRAPH_CATALOG_PROTOCOL
                                )
                            )
                        )
                    ),
                    protocol_schema_hash=(
                        KNOWLEDGE_GRAPH_AUTOMATIC_ITEM_CATALOG_SCHEMA_HASH
                        if isinstance(command, PublishKnowledgeGraphSnapshotCommandV4)
                        else (
                            KNOWLEDGE_GRAPH_APPROVED_ITEM_CATALOG_SCHEMA_HASH
                            if isinstance(command, PublishKnowledgeGraphSnapshotCommandV3)
                            else (
                                KNOWLEDGE_GRAPH_REVIEWED_CURRICULUM_CATALOG_SCHEMA_HASH
                                if isinstance(command, PublishKnowledgeGraphSnapshotCommandV2)
                                else (
                                    KNOWLEDGE_GRAPH_DOCUMENT_CATALOG_SCHEMA_HASH
                                    if document_projection
                                    else KNOWLEDGE_GRAPH_CATALOG_SCHEMA_HASH
                                )
                            )
                        )
                    ),
                )
        except (OSError, RuntimeError, ValueError) as exc:
            raise KnowledgeGraphPublicationError(
                "KNOWLEDGE_GRAPH_ARTIFACT_COMMIT_FAILED",
                "knowledge graph projection Artifact commit failed",
            ) from exc

    @staticmethod
    def _projection_pointers(artifact: CatalogArtifact) -> KnowledgeGraphProjections:
        files = artifact.manifest.get("files")
        entries = (
            {
                value.get("file_name"): value
                for value in files
                if isinstance(value, dict) and isinstance(value.get("file_name"), str)
            }
            if isinstance(files, list)
            else {}
        )

        def pointer(path: str, logical_name: str) -> KnowledgeArtifactMemberPointer:
            entry = entries.get(path)
            if not isinstance(entry, dict):
                raise KnowledgeGraphPublicationError(
                    "KNOWLEDGE_GRAPH_ARTIFACT_COMMIT_FAILED",
                    "projection Artifact member is absent",
                )
            return KnowledgeArtifactMemberPointer(
                artifact_id=artifact.artifact_id,
                artifact_revision_id=artifact.revision_id,
                sha256=cast(str, entry["sha256"]),
                schema_ref=cast(str, entry["schema_ref"]),
                media_type=cast(str, entry["media_type"]),
                logical_name=logical_name,
                member_path=path,
            )

        return KnowledgeGraphProjections(
            nodes=pointer("projections/nodes.jsonl", "nodes.jsonl"),
            edges=pointer("projections/edges.jsonl", "edges.jsonl"),
            curriculum_closure=(
                pointer("projections/curriculum-closure.jsonl", "curriculum-closure.jsonl")
                if "projections/curriculum-closure.jsonl" in entries
                else None
            ),
            markdown=pointer("projections/graph.md", "graph.md"),
            lexical_index=pointer("projections/lexical-index.json", "lexical-index.json"),
        )

    def _commit_manifest(
        self,
        command: KnowledgeGraphPublicationCommand,
        manifest: KnowledgeGraphSnapshotContract,
    ) -> CatalogArtifact:
        try:
            with tempfile.TemporaryDirectory(
                prefix="knowledge-graph-manifest.", dir=self.settings.staging_root
            ) as raw_directory:
                source = Path(raw_directory) / "manifest.json"
                source.write_bytes(canonical_json_bytes(manifest))
                source.chmod(0o640)
                if isinstance(manifest, KnowledgeGraphSnapshotManifestV7):
                    schema_ref = "eom://schemas/knowledge/knowledge-graph-snapshot-manifest/7.0"
                    protocol_version = KNOWLEDGE_GRAPH_AUTOMATIC_ITEM_CATALOG_PROTOCOL
                    protocol_schema_hash = KNOWLEDGE_GRAPH_AUTOMATIC_ITEM_CATALOG_SCHEMA_HASH
                elif isinstance(manifest, KnowledgeGraphSnapshotManifestV6):
                    schema_ref = "eom://schemas/knowledge/knowledge-graph-snapshot-manifest/6.0"
                    protocol_version = KNOWLEDGE_GRAPH_APPROVED_ITEM_CATALOG_PROTOCOL
                    protocol_schema_hash = KNOWLEDGE_GRAPH_APPROVED_ITEM_CATALOG_SCHEMA_HASH
                elif isinstance(manifest, KnowledgeGraphSnapshotManifestV5):
                    schema_ref = "eom://schemas/knowledge/knowledge-graph-snapshot-manifest/5.0"
                    protocol_version = KNOWLEDGE_GRAPH_REVIEWED_CURRICULUM_CATALOG_PROTOCOL
                    protocol_schema_hash = KNOWLEDGE_GRAPH_REVIEWED_CURRICULUM_CATALOG_SCHEMA_HASH
                elif isinstance(manifest, KnowledgeGraphSnapshotManifestV4):
                    schema_ref = "eom://schemas/knowledge/knowledge-graph-snapshot-manifest/4.0"
                    protocol_version = KNOWLEDGE_GRAPH_MULTIMODAL_DOCUMENT_CATALOG_PROTOCOL
                    protocol_schema_hash = KNOWLEDGE_GRAPH_MULTIMODAL_DOCUMENT_CATALOG_SCHEMA_HASH
                elif isinstance(manifest, KnowledgeGraphSnapshotManifestV3):
                    schema_ref = "eom://schemas/knowledge/knowledge-graph-snapshot-manifest/3.0"
                    protocol_version = KNOWLEDGE_GRAPH_DOCUMENT_CATALOG_PROTOCOL
                    protocol_schema_hash = KNOWLEDGE_GRAPH_DOCUMENT_CATALOG_SCHEMA_HASH
                else:
                    schema_ref = "eom://schemas/knowledge/knowledge-graph-snapshot-manifest/2.0"
                    protocol_version = KNOWLEDGE_GRAPH_CATALOG_PROTOCOL
                    protocol_schema_hash = KNOWLEDGE_GRAPH_CATALOG_SCHEMA_HASH
                return self.artifacts.commit_file_set(
                    files={"projections/manifest.json": source},
                    primary_file="projections/manifest.json",
                    artifact_type="knowledge-graph-snapshot-manifest",
                    idempotency_key=f"knowledge-graph-manifest:{command.request_sha256}",
                    request={"request_sha256": command.request_sha256},
                    result={
                        "graph_id": manifest.graph_id,
                        "graph_snapshot_revision_id": manifest.graph_snapshot_revision_id,
                        "snapshot_sha256": manifest.snapshot_sha256,
                    },
                    file_metadata={
                        "projections/manifest.json": {
                            "schema_ref": schema_ref,
                            "media_type": "application/json",
                        }
                    },
                    manifest_version="knowledge-graph-snapshot-manifest-file-set/1.0",
                    protocol_version=protocol_version,
                    protocol_schema_hash=protocol_schema_hash,
                )
        except (OSError, RuntimeError, ValueError) as exc:
            raise KnowledgeGraphPublicationError(
                "KNOWLEDGE_GRAPH_ARTIFACT_COMMIT_FAILED",
                "knowledge graph manifest Artifact commit failed",
            ) from exc

    def _commit_database_snapshot(
        self,
        *,
        command: KnowledgeGraphPublicationCommand,
        ids: dict[str, str],
        expected_revision_number: int,
        previous_corpus_revision_id: str | None,
        projection: EducationGraphProjection,
        projection_artifact: CatalogArtifact,
        manifest: KnowledgeGraphSnapshotContract,
        manifest_artifact: CatalogArtifact,
    ) -> KnowledgeGraphPublicationResult:
        with transaction(self.sessions) as session:
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:corpus_key, 0))"),
                {"corpus_key": command.corpus_key},
            )
            existing = session.scalar(
                select(KnowledgeGraphPublicationRecord).where(
                    KnowledgeGraphPublicationRecord.idempotency_key == command.idempotency_key
                )
            )
            if existing is not None:
                if existing.request_sha256 != command.request_sha256:
                    raise KnowledgeGraphPublicationError(
                        "KNOWLEDGE_GRAPH_IDEMPOTENCY_CONFLICT",
                        "graph publication idempotency key has different input",
                    )
                return self._result(session, existing)
            publisher = session.get(OperatorRecord, command.published_by_operator_id)
            if publisher is None or publisher.status != "ACTIVE":
                raise KnowledgeGraphPublicationError(
                    "KNOWLEDGE_GRAPH_PUBLISHER_INVALID",
                    "graph publisher is absent or inactive",
                )
            corpus = session.scalar(
                select(KnowledgeCorpusRecord)
                .where(KnowledgeCorpusRecord.corpus_key == command.corpus_key)
                .with_for_update()
            )
            if corpus is None:
                if command.expected_current_snapshot_revision_id is not None:
                    raise KnowledgeGraphPublicationError(
                        "KNOWLEDGE_GRAPH_STALE_CURRENT",
                        "new corpus cannot have an expected current snapshot",
                    )
                corpus = KnowledgeCorpusRecord(
                    corpus_id=ids["corpus_id"],
                    corpus_key=command.corpus_key,
                    display_name=command.display_name,
                    graph_id=ids["graph_id"],
                    current_corpus_revision_id=None,
                    current_graph_snapshot_revision_id=None,
                    lifecycle_state="ACTIVE",
                    lock_version=1,
                    created_by_operator_id=command.published_by_operator_id,
                    created_at=command.requested_at,
                    updated_at=command.requested_at,
                )
                session.add(corpus)
                actual_revision_number = 1
                actual_previous_corpus_revision_id = None
            else:
                current_snapshot = session.get(
                    KnowledgeGraphSnapshotRecord, corpus.current_graph_snapshot_revision_id
                )
                if (
                    corpus.lifecycle_state != "ACTIVE"
                    or corpus.display_name != command.display_name
                    or corpus.graph_id != ids["graph_id"]
                    or corpus.current_graph_snapshot_revision_id
                    != command.expected_current_snapshot_revision_id
                    or current_snapshot is None
                    or corpus.current_corpus_revision_id is None
                ):
                    raise KnowledgeGraphPublicationError(
                        "KNOWLEDGE_GRAPH_STALE_CURRENT",
                        "knowledge corpus changed before publication",
                    )
                actual_revision_number = current_snapshot.revision_number + 1
                actual_previous_corpus_revision_id = corpus.current_corpus_revision_id
            if (
                actual_revision_number != expected_revision_number
                or actual_previous_corpus_revision_id != previous_corpus_revision_id
            ):
                raise KnowledgeGraphPublicationError(
                    "KNOWLEDGE_GRAPH_STALE_CURRENT",
                    "knowledge corpus changed during Artifact publication",
                )

            source_set_sha256 = content_sha256(
                [
                    {
                        "analysis_run_id": item.analysis_run_id,
                        "source": item.source.model_dump(mode="json"),
                        "accepted_result": item.accepted_result.model_dump(mode="json"),
                    }
                    for item in projection.analyses
                ]
            )
            corpus_revision = KnowledgeCorpusRevisionRecord(
                corpus_revision_id=ids["corpus_revision_id"],
                corpus_id=corpus.corpus_id,
                revision_number=expected_revision_number,
                previous_corpus_revision_id=previous_corpus_revision_id,
                source_set_sha256=source_set_sha256,
                state="PUBLISHED",
                created_by_operator_id=command.published_by_operator_id,
                created_at=command.requested_at,
            )
            snapshot = KnowledgeGraphSnapshotRecord(
                graph_snapshot_revision_id=ids["graph_snapshot_revision_id"],
                graph_id=corpus.graph_id,
                corpus_revision_id=corpus_revision.corpus_revision_id,
                revision_number=expected_revision_number,
                previous_graph_snapshot_revision_id=manifest.previous_graph_snapshot_revision_id,
                state="PUBLISHED",
                ontology_version=manifest.ontology_version,
                publisher_version=manifest.publisher_version,
                manifest_artifact_id=manifest_artifact.artifact_id,
                manifest_artifact_revision_id=manifest_artifact.revision_id,
                projection_artifact_id=projection_artifact.artifact_id,
                projection_artifact_revision_id=projection_artifact.revision_id,
                manifest_sha256=manifest_artifact.content_hash,
                snapshot_sha256=manifest.snapshot_sha256,
                source_count=manifest.counts.source_revisions,
                node_count=manifest.counts.nodes,
                edge_count=manifest.counts.edges,
                anchor_count=manifest.counts.anchors,
                created_by_operator_id=command.published_by_operator_id,
                created_at=command.requested_at,
            )
            session.add_all([corpus_revision, snapshot])
            session.flush()
            for analysis in projection.analyses:
                source_member = analysis.source.artifact_member
                session.add(
                    KnowledgeSnapshotAnalysisRecord(
                        graph_snapshot_revision_id=snapshot.graph_snapshot_revision_id,
                        analysis_run_id=analysis.analysis_run_id,
                        source_kind=analysis.source.source_kind,
                        source_revision_id=_source_revision_id(analysis.source),
                        source_artifact_id=source_member.artifact_id,
                        source_artifact_revision_id=source_member.artifact_revision_id,
                        source_sha256=source_member.sha256,
                        accepted_result_artifact_id=analysis.accepted_result.artifact_id,
                        accepted_result_artifact_revision_id=(
                            analysis.accepted_result.artifact_revision_id
                        ),
                        accepted_result_sha256=analysis.accepted_result.sha256,
                    )
                )
            for node in projection.nodes:
                session.add(
                    KnowledgeNodeRecord(
                        graph_snapshot_revision_id=snapshot.graph_snapshot_revision_id,
                        node_id=node.node_id,
                        node_type=node.node_type,
                        stable_key=node.stable_key,
                        label=node.label,
                        answer_bearing=node.answer_bearing,
                    )
                )
            # These immutable graph records use composite foreign keys without ORM
            # relationships.  Establish each parent tier explicitly; SQLAlchemy's mapper
            # ordering alone does not guarantee that nodes precede edges or that edges
            # precede their source pointers in one flush.
            session.flush()
            for node in projection.nodes:
                terms = {
                    term
                    for label in (node.label, *node.aliases)
                    for term in knowledge_node_terms(node.stable_key, label)
                }
                for term in sorted(terms):
                    session.add(
                        KnowledgeNodeTermRecord(
                            graph_snapshot_revision_id=snapshot.graph_snapshot_revision_id,
                            term=term,
                            node_id=node.node_id,
                        )
                    )
                for pointer in node.source_pointers:
                    session.add(
                        KnowledgeNodeSourcePointerRecord(
                            graph_snapshot_revision_id=snapshot.graph_snapshot_revision_id,
                            node_id=node.node_id,
                            analysis_run_id=pointer.analysis_run_id,
                            source_revision_id=pointer.source_revision_id,
                            source_class=pointer.source_class,
                            source_artifact_id=pointer.source_artifact_id,
                            artifact_revision_id=pointer.source_artifact_revision_id,
                            source_sha256=pointer.source_sha256,
                            member_path=pointer.member_path,
                            anchor_id=pointer.anchor_id,
                            excerpt_sha256=pointer.excerpt_sha256,
                        )
                    )
            for edge in projection.edges:
                session.add(
                    KnowledgeEdgeRecord(
                        graph_snapshot_revision_id=snapshot.graph_snapshot_revision_id,
                        edge_id=edge.edge_id,
                        edge_type=edge.edge_type,
                        from_node_id=edge.from_node_id,
                        to_node_id=edge.to_node_id,
                        confidence_milli=edge.confidence_milli,
                        answer_bearing=edge.answer_bearing,
                    )
                )
            node_by_stable_key = {item.stable_key: item.node_id for item in projection.nodes}
            # The parent FK is immediate, not deferred.  Flush one topological layer at
            # a time because SQLAlchemy may reorder rows inside one executemany batch.
            # The adjacency index keeps traversal O(units + hierarchy edges), apart
            # from deterministic sibling sorting.
            for unit_layer in _curriculum_unit_layers(projection.curriculum_units):
                for unit in unit_layer:
                    session.add(
                        CurriculumUnitRecord(
                            graph_snapshot_revision_id=snapshot.graph_snapshot_revision_id,
                            curriculum_unit_id=unit.curriculum_unit_id,
                            node_id=node_by_stable_key[unit.node_stable_key],
                            framework_revision_id=unit.framework_revision_id,
                            parent_unit_id=unit.parent_unit_id,
                            unit_level=unit.unit_level,
                            ordinal=unit.ordinal,
                        )
                    )
                session.flush()
            for edge in projection.edges:
                for pointer in edge.source_pointers:
                    session.add(
                        KnowledgeEdgeSourcePointerRecord(
                            graph_snapshot_revision_id=snapshot.graph_snapshot_revision_id,
                            edge_id=edge.edge_id,
                            analysis_run_id=pointer.analysis_run_id,
                            source_revision_id=pointer.source_revision_id,
                            source_class=pointer.source_class,
                            source_artifact_id=pointer.source_artifact_id,
                            artifact_revision_id=pointer.source_artifact_revision_id,
                            source_sha256=pointer.source_sha256,
                            member_path=pointer.member_path,
                            anchor_id=pointer.anchor_id,
                            excerpt_sha256=pointer.excerpt_sha256,
                        )
                    )
            for closure in projection.curriculum_closure:
                session.add(
                    CurriculumUnitClosureRecord(
                        graph_snapshot_revision_id=snapshot.graph_snapshot_revision_id,
                        framework_revision_id=closure.framework_revision_id,
                        ancestor_unit_id=closure.ancestor_unit_id,
                        descendant_unit_id=closure.descendant_unit_id,
                        depth=closure.depth,
                    )
                )
            for element in projection.item_elements:
                session.add(
                    ItemElementReferenceRecord(
                        graph_snapshot_revision_id=snapshot.graph_snapshot_revision_id,
                        item_revision_id=element.item_revision_id,
                        element_kind=element.element_kind,
                        element_id=element.element_id,
                        node_id=node_by_stable_key[element.node_stable_key],
                        item_id=element.item_id,
                        item_content_artifact_id=element.item_content_artifact_id,
                        item_content_artifact_revision_id=(
                            element.item_content_artifact_revision_id
                        ),
                        item_content_sha256=element.item_content_sha256,
                        schema_ref=element.schema_ref,
                        answer_bearing=element.answer_bearing,
                    )
                )
            publication = KnowledgeGraphPublicationRecord(
                publication_id=ids["publication_id"],
                corpus_id=corpus.corpus_id,
                graph_snapshot_revision_id=snapshot.graph_snapshot_revision_id,
                idempotency_key=command.idempotency_key,
                request_sha256=command.request_sha256,
                published_by_operator_id=command.published_by_operator_id,
                requested_at=command.requested_at,
                published_at=command.requested_at,
            )
            session.add(publication)
            corpus.current_corpus_revision_id = corpus_revision.corpus_revision_id
            corpus.current_graph_snapshot_revision_id = snapshot.graph_snapshot_revision_id
            corpus.lock_version += 1
            corpus.updated_at = command.requested_at
            session.flush()
            return self._result(session, publication)

    @staticmethod
    def _result(
        session: Session, publication: KnowledgeGraphPublicationRecord
    ) -> KnowledgeGraphPublicationResult:
        corpus = session.get(KnowledgeCorpusRecord, publication.corpus_id)
        snapshot = session.get(KnowledgeGraphSnapshotRecord, publication.graph_snapshot_revision_id)
        manifest_revision = (
            session.get(ArtifactRevisionRecord, snapshot.manifest_artifact_revision_id)
            if snapshot is not None
            else None
        )
        if (
            corpus is None
            or snapshot is None
            or manifest_revision is None
            or not manifest_revision.approved
            or manifest_revision.logical_artifact_id != snapshot.manifest_artifact_id
            or manifest_revision.content_hash != snapshot.manifest_sha256
        ):
            raise KnowledgeGraphPublicationError(
                "KNOWLEDGE_GRAPH_CURRENT_INVALID", "publication result pointers do not resolve"
            )
        manifest_schema_ref = _manifest_member_schema_ref(manifest_revision)
        value: dict[str, Any] = {
            "schema_version": "knowledge-graph-publication-result/1.0",
            "publication_id": publication.publication_id,
            "corpus_id": corpus.corpus_id,
            "corpus_key": corpus.corpus_key,
            "corpus_revision_id": snapshot.corpus_revision_id,
            "graph_snapshot": KnowledgeGraphSnapshotPointer(
                graph_id=corpus.graph_id,
                graph_snapshot_revision_id=snapshot.graph_snapshot_revision_id,
                manifest_artifact=KnowledgeArtifactMemberPointer(
                    artifact_id=snapshot.manifest_artifact_id,
                    artifact_revision_id=snapshot.manifest_artifact_revision_id,
                    sha256=snapshot.manifest_sha256,
                    schema_ref=manifest_schema_ref,
                    media_type="application/json",
                    logical_name="manifest.json",
                    member_path="projections/manifest.json",
                ),
                manifest_sha256=snapshot.manifest_sha256,
            ).model_dump(mode="json"),
            "revision_number": snapshot.revision_number,
            "state": snapshot.state,
            "counts": {
                "source_revisions": snapshot.source_count,
                "nodes": snapshot.node_count,
                "edges": snapshot.edge_count,
                "anchors": snapshot.anchor_count,
            },
            "request_sha256": publication.request_sha256,
            "published_at": publication.published_at.astimezone(UTC)
            .isoformat()
            .replace("+00:00", "Z"),
            "result_sha256": "sha256:" + "0" * 64,
        }
        value["result_sha256"] = content_sha256(
            {key: item for key, item in value.items() if key != "result_sha256"}
        )
        validate_contract("knowledge-graph-publication-result", value)
        return KnowledgeGraphPublicationResult.model_validate(value)
