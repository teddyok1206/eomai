"""Deterministic bounded retrieval and immutable Evidence Bundle publication."""

from __future__ import annotations

import tempfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from eom_catalog_contracts import (
    ApprovedItemKnowledgeSourceV2,
    ContentIntakeKnowledgeSourceV2,
    CreateEvidenceBundleCommand,
    CreateItemProductionEvidenceCommand,
    CurriculumRetrievalScope,
    EducationalDocumentKnowledgeSourceV3,
    EducationalDocumentKnowledgeSourceV4,
    EducationRetrievalAccessPolicy,
    EducationRetrievalRequestV2,
    EvidenceBundleManifestV2,
    EvidenceBundleManifestV3,
    EvidenceBundleManifestV4,
    EvidenceBundleMaterialsV2,
    EvidenceBundlePublicationResult,
    EvidenceBundlePublicationResultV2,
    EvidenceBundlePublicationResultV3,
    EvidenceBundlePublicationResultV4,
    EvidenceEntryV2,
    EvidenceEntryV3,
    EvidenceEntryV4,
    KnowledgeAnalysisRequestV2,
    KnowledgeAnalysisRequestV3,
    KnowledgeAnalysisRequestV4,
    KnowledgeAnalysisRequestV5,
    KnowledgeAnalysisRequestV6,
    KnowledgeAnalysisRequestV7,
    KnowledgeAnalysisRequestV8,
    KnowledgeAnalysisSourceV3,
    KnowledgeArtifactMemberPointer,
    KnowledgeGraphSnapshotPointer,
    validate_contract,
)
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_identity_service.models import OperatorRecord
from eom_orchestrator.database import build_session_factory, transaction
from eom_orchestrator.knowledge_analysis_models import KnowledgeAnalysisRunRecord
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord
from pydantic import ValidationError
from sqlalchemy import Engine, distinct, func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from eom_catalog_service.artifacts import CatalogArtifact, CatalogArtifactService
from eom_catalog_service.knowledge_analysis_sources import (
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
    KnowledgeEdgeRecord,
    KnowledgeGraphSnapshotRecord,
    KnowledgeNodeRecord,
    KnowledgeNodeSourcePointerRecord,
    KnowledgeNodeTermRecord,
    KnowledgeSnapshotAnalysisRecord,
)
from eom_catalog_service.knowledge_graph_projection import knowledge_node_terms
from eom_catalog_service.settings import CatalogSettings

KNOWLEDGE_RETRIEVAL_CATALOG_PROTOCOL = "catalog-knowledge-retrieval/1.0"
KNOWLEDGE_RETRIEVAL_CATALOG_SCHEMA_HASH = content_sha256(
    {
        "protocol": KNOWLEDGE_RETRIEVAL_CATALOG_PROTOCOL,
        "contracts": [
            "education-retrieval-access-policy/1.0",
            "education-retrieval-request/2.0",
            "evidence-bundle-manifest/2.0",
            "evidence-bundle-publication-result/1.0",
        ],
    }
)
KNOWLEDGE_RETRIEVAL_DOCUMENT_CATALOG_PROTOCOL = "catalog-knowledge-retrieval/1.1"
KNOWLEDGE_RETRIEVAL_DOCUMENT_CATALOG_SCHEMA_HASH = content_sha256(
    {
        "protocol": KNOWLEDGE_RETRIEVAL_DOCUMENT_CATALOG_PROTOCOL,
        "contracts": [
            "education-retrieval-access-policy/1.0",
            "education-retrieval-request/2.0",
            "evidence-bundle-manifest/3.0",
            "evidence-bundle-publication-result/3.0",
        ],
    }
)
KNOWLEDGE_RETRIEVAL_MULTIMODAL_CATALOG_PROTOCOL = "catalog-knowledge-retrieval/1.2"
KNOWLEDGE_RETRIEVAL_MULTIMODAL_CATALOG_SCHEMA_HASH = content_sha256(
    {
        "protocol": KNOWLEDGE_RETRIEVAL_MULTIMODAL_CATALOG_PROTOCOL,
        "contracts": [
            "education-retrieval-access-policy/1.0",
            "education-retrieval-request/2.0",
            "evidence-bundle-manifest/4.0",
            "evidence-bundle-publication-result/4.0",
        ],
    }
)
type EvidenceEntryContract = EvidenceEntryV2 | EvidenceEntryV3 | EvidenceEntryV4
type EvidenceManifestContract = (
    EvidenceBundleManifestV2 | EvidenceBundleManifestV3 | EvidenceBundleManifestV4
)
type EvidencePublicationContract = (
    EvidenceBundlePublicationResult
    | EvidenceBundlePublicationResultV3
    | EvidenceBundlePublicationResultV4
)
type ItemProductionEvidencePublicationContract = (
    EvidenceBundlePublicationResultV2
    | EvidenceBundlePublicationResultV3
    | EvidenceBundlePublicationResultV4
)
MAX_RETRIEVAL_CANDIDATES = 256
MAX_POINTER_ROWS_PER_NODE = 32
MAX_CONTEXT_BYTES = 64 * 1024


class KnowledgeRetrievalServiceError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class _Candidate:
    analysis_run_id: str
    source: KnowledgeAnalysisSourceV3 | EducationalDocumentKnowledgeSourceV4
    node_ids: tuple[str, ...]
    anchor_ids: tuple[str, ...]
    node_labels: tuple[str, ...]
    node_types: tuple[str, ...]
    relevance_milli: int
    answer_bearing: bool


def _typed_id(prefix: str, value: dict[str, object]) -> str:
    return prefix + content_sha256(value).removeprefix("sha256:")[:32]


def _utc_json(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _context_tokens(value: str) -> int:
    return max(1, (len(value.encode("utf-8")) + 1) // 2)


def _artifact_member_schema_ref(
    revision: ArtifactRevisionRecord,
    *,
    member_path: str,
    allowed: frozenset[str],
) -> str:
    files = revision.manifest.get("files")
    if not isinstance(files, list):
        raise KnowledgeRetrievalServiceError(
            "KNOWLEDGE_RETRIEVAL_PUBLICATION_INVALID",
            "published Artifact manifest has no member inventory",
        )
    matches = [
        item for item in files if isinstance(item, dict) and item.get("file_name") == member_path
    ]
    if len(matches) != 1 or matches[0].get("schema_ref") not in allowed:
        raise KnowledgeRetrievalServiceError(
            "KNOWLEDGE_RETRIEVAL_PUBLICATION_INVALID",
            "published Artifact member schema is incompatible",
        )
    return str(matches[0]["schema_ref"])


class KnowledgeRetrievalApplicationService:
    """Own one closed retrieval query and publish only immutable pointer-oriented output."""

    def __init__(self, engine: Engine, settings: CatalogSettings | None = None) -> None:
        self.settings = settings or CatalogSettings.from_environment()
        self.sessions = build_session_factory(engine)
        self.artifacts = CatalogArtifactService(engine, self.settings)

    def create_item_production(
        self, command: CreateItemProductionEvidenceCommand
    ) -> ItemProductionEvidencePublicationContract:
        """Resolve a stable educational intent without accepting a raw snapshot control."""

        internal_key = "item-evidence:" + content_sha256(
            {"idempotency_key": command.idempotency_key}
        ).removeprefix("sha256:")
        with self.sessions() as session:
            existing = session.scalar(
                select(EducationRetrievalRequestRecord).where(
                    EducationRetrievalRequestRecord.idempotency_key == internal_key
                )
            )
            if existing is not None:
                self._validate_item_production_replay(session, command, existing)
                revision = session.scalar(
                    select(EvidenceBundleRevisionRecord).where(
                        EvidenceBundleRevisionRecord.retrieval_request_id
                        == existing.retrieval_request_id
                    )
                )
                if revision is None:
                    raise KnowledgeRetrievalServiceError(
                        "KNOWLEDGE_RETRIEVAL_PUBLICATION_INCOMPLETE",
                        "item production retrieval has no published Evidence Bundle",
                    )
                return self._result_v2(session, existing, revision)
            corpus = session.scalar(
                select(KnowledgeCorpusRecord).where(
                    KnowledgeCorpusRecord.corpus_key == command.requirement.corpus_key
                )
            )
            snapshot = (
                session.get(KnowledgeGraphSnapshotRecord, corpus.current_graph_snapshot_revision_id)
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
                raise KnowledgeRetrievalServiceError(
                    "KNOWLEDGE_RETRIEVAL_CORPUS_UNAVAILABLE",
                    "requested knowledge corpus has no published current snapshot",
                )
            policy_row = session.get(
                EducationRetrievalAccessPolicyRevisionRecord,
                command.access_policy_revision_id,
            )
            if (
                policy_row is None
                or policy_row.state != "RELEASED"
                or policy_row.content_sha256 != command.access_policy_sha256
            ):
                raise KnowledgeRetrievalServiceError(
                    "KNOWLEDGE_RETRIEVAL_POLICY_INVALID",
                    "preset-selected retrieval policy pointer is stale",
                )
            curriculum_scope: CurriculumRetrievalScope | None = None
            if command.requirement.curriculum_root_key is not None:
                root_node = session.scalar(
                    select(KnowledgeNodeRecord).where(
                        KnowledgeNodeRecord.graph_snapshot_revision_id
                        == snapshot.graph_snapshot_revision_id,
                        KnowledgeNodeRecord.stable_key == command.requirement.curriculum_root_key,
                    )
                )
                root_unit = (
                    session.scalar(
                        select(CurriculumUnitRecord).where(
                            CurriculumUnitRecord.graph_snapshot_revision_id
                            == snapshot.graph_snapshot_revision_id,
                            CurriculumUnitRecord.node_id == root_node.node_id,
                        )
                    )
                    if root_node is not None
                    else None
                )
                if root_unit is None:
                    raise KnowledgeRetrievalServiceError(
                        "KNOWLEDGE_RETRIEVAL_CURRICULUM_SCOPE_INVALID",
                        "curriculum root key is absent from the pinned snapshot",
                    )
                curriculum_scope = CurriculumRetrievalScope(
                    framework_revision_id=root_unit.framework_revision_id,
                    root_unit_id=root_unit.curriculum_unit_id,
                    include_descendants=True,
                )
            graph_snapshot_revision_id = snapshot.graph_snapshot_revision_id

        inner_value: dict[str, Any] = {
            "operation": "CREATE_EVIDENCE_BUNDLE",
            "graph_snapshot_revision_id": graph_snapshot_revision_id,
            "query_kind": command.requirement.query_kind,
            "curriculum_scope": (
                curriculum_scope.model_dump(mode="json") if curriculum_scope is not None else None
            ),
            "topic_keys": list(command.requirement.topic_keys),
            "target_item_revision_id": None,
            "required_item_elements": list(command.requirement.required_item_elements),
            "source_classes": list(command.requirement.source_classes),
            "evidence_budget": command.evidence_budget.model_dump(mode="json"),
            "access_policy_revision_id": command.access_policy_revision_id,
            "requester_role": command.requester_role,
            "requester_permission_keys": list(command.requester_permission_keys),
            "requested_by": command.requested_by,
            "idempotency_key": internal_key,
            "submission_sha256": "sha256:" + "0" * 64,
        }
        inner_value["submission_sha256"] = content_sha256(
            {
                key: value
                for key, value in inner_value.items()
                if key not in {"idempotency_key", "submission_sha256"}
            }
        )
        published = self.create(CreateEvidenceBundleCommand.model_validate(inner_value))
        with self.sessions() as session:
            request = session.get(EducationRetrievalRequestRecord, published.retrieval_request_id)
            revision = session.get(
                EvidenceBundleRevisionRecord, published.evidence_bundle_revision_id
            )
            if request is None or revision is None:
                raise KnowledgeRetrievalServiceError(
                    "KNOWLEDGE_RETRIEVAL_PUBLICATION_INCOMPLETE",
                    "published item production Evidence Bundle cannot be reloaded",
                )
            return self._result_v2(session, request, revision)

    @staticmethod
    def _validate_item_production_replay(
        session: Session,
        command: CreateItemProductionEvidenceCommand,
        record: EducationRetrievalRequestRecord,
    ) -> None:
        """Reject same-key replay unless it resolves to the original educational intent."""

        try:
            request = EducationRetrievalRequestV2.model_validate(record.canonical_request)
        except (ValueError, ValidationError) as exc:
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_RESULT_INVALID",
                "persisted item production retrieval request is invalid",
            ) from exc
        corpus = session.scalar(
            select(KnowledgeCorpusRecord).where(
                KnowledgeCorpusRecord.corpus_key == command.requirement.corpus_key
            )
        )
        curriculum_key: str | None = None
        if request.curriculum_scope is not None:
            curriculum_key = session.scalar(
                select(KnowledgeNodeRecord.stable_key)
                .join(
                    CurriculumUnitRecord,
                    CurriculumUnitRecord.node_id == KnowledgeNodeRecord.node_id,
                )
                .where(
                    KnowledgeNodeRecord.graph_snapshot_revision_id
                    == request.graph_snapshot.graph_snapshot_revision_id,
                    CurriculumUnitRecord.graph_snapshot_revision_id
                    == request.graph_snapshot.graph_snapshot_revision_id,
                    CurriculumUnitRecord.framework_revision_id
                    == request.curriculum_scope.framework_revision_id,
                    CurriculumUnitRecord.curriculum_unit_id
                    == request.curriculum_scope.root_unit_id,
                )
            )
        if (
            corpus is None
            or corpus.graph_id != request.graph_snapshot.graph_id
            or curriculum_key != command.requirement.curriculum_root_key
            or request.query_kind != command.requirement.query_kind
            or request.topic_keys != command.requirement.topic_keys
            or request.required_item_elements != command.requirement.required_item_elements
            or request.source_classes != command.requirement.source_classes
            or request.evidence_budget != command.evidence_budget
            or request.access_policy_revision_id != command.access_policy_revision_id
            or request.access_policy_sha256 != command.access_policy_sha256
            or request.requester_role != command.requester_role
            or request.requester_operator_id != command.requested_by
            or request.requester_permission_keys != command.requester_permission_keys
        ):
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_IDEMPOTENCY_CONFLICT",
                "item production evidence key has different immutable input",
            )

    def create(self, command: CreateEvidenceBundleCommand) -> EvidencePublicationContract:
        existing = self._existing(command)
        if existing is not None:
            return existing
        created_at = datetime.now(UTC)
        retrieval_request_id = _typed_id(
            "retrieval_",
            {
                "submission_sha256": command.submission_sha256,
                "idempotency_key": command.idempotency_key,
            },
        )
        evidence_bundle_id = _typed_id("evidence_", {"retrieval_request_id": retrieval_request_id})
        evidence_bundle_revision_id = _typed_id(
            "evidencerev_", {"retrieval_request_id": retrieval_request_id, "revision_number": 1}
        )
        with self.sessions() as session:
            snapshot_pointer = self._snapshot_pointer(session, command.graph_snapshot_revision_id)
            policy = self._policy(session, command.access_policy_revision_id)
            self._authorize(session, command, policy)
            request = self._request(
                command,
                snapshot_pointer=snapshot_pointer,
                policy=policy,
                retrieval_request_id=retrieval_request_id,
                created_at=created_at,
            )
            candidates = self._candidates(session, command, policy)
            entries, context_markdown = self._rank_and_render(
                request=request,
                candidates=candidates,
            )

        context_artifact = self._commit_context(request, context_markdown, entries=entries)
        context_pointer = KnowledgeArtifactMemberPointer(
            artifact_id=context_artifact.artifact_id,
            artifact_revision_id=context_artifact.revision_id,
            sha256=context_artifact.content_hash,
            schema_ref="eom://schemas/knowledge/evidence-bundle-context/1.0",
            media_type="text/markdown",
            logical_name="context.md",
            member_path="evidence/context.md",
        )
        node_ids = {node_id for entry in entries for node_id in entry.graph_node_ids}
        document_sources = {
            (
                entry.source.document_revision_id
                if isinstance(
                    entry.source,
                    EducationalDocumentKnowledgeSourceV3 | EducationalDocumentKnowledgeSourceV4,
                )
                else entry.source.source_file_id
            )
            for entry in entries
            if not isinstance(entry.source, ApprovedItemKnowledgeSourceV2)
        }
        budget = {
            "document_count": len(document_sources),
            "item_revision_count": len(
                {
                    entry.source.item_revision_id
                    for entry in entries
                    if isinstance(entry.source, ApprovedItemKnowledgeSourceV2)
                }
            ),
            "graph_node_count": len(node_ids),
            "claim_count": sum(entry.evidence_kind == "CLAIM" for entry in entries),
            "estimated_context_tokens": _context_tokens(context_markdown),
        }
        manifest_value: dict[str, Any] = {
            "schema_version": self._manifest_schema_version(entries),
            "evidence_bundle_id": evidence_bundle_id,
            "evidence_bundle_revision_id": evidence_bundle_revision_id,
            "revision_number": 1,
            "retrieval_request_id": request.retrieval_request_id,
            "retrieval_request_sha256": request.request_sha256,
            "graph_snapshot": request.graph_snapshot.model_dump(mode="json"),
            "access_policy_revision_id": policy.access_policy_revision_id,
            "access_policy_sha256": policy.content_sha256,
            "requester_permissions_sha256": request.requester_permissions_sha256,
            "materials": EvidenceBundleMaterialsV2(context_markdown=context_pointer).model_dump(
                mode="json"
            ),
            "entries": [entry.model_dump(mode="json") for entry in entries],
            "budget": budget,
            "manifest_sha256": "sha256:" + "0" * 64,
            "created_at": _utc_json(created_at),
        }
        manifest_value["manifest_sha256"] = content_sha256(
            {key: value for key, value in manifest_value.items() if key != "manifest_sha256"}
        )
        manifest: EvidenceManifestContract
        try:
            if manifest_value["schema_version"] == "evidence-bundle-manifest/4.0":
                validate_contract("evidence-bundle-manifest-v4", manifest_value)
                manifest = EvidenceBundleManifestV4.model_validate(manifest_value)
            elif manifest_value["schema_version"] == "evidence-bundle-manifest/3.0":
                validate_contract("evidence-bundle-manifest-v3", manifest_value)
                manifest = EvidenceBundleManifestV3.model_validate(manifest_value)
            else:
                validate_contract("evidence-bundle-manifest-v2", manifest_value)
                manifest = EvidenceBundleManifestV2.model_validate(manifest_value)
        except (ValueError, ValidationError) as exc:
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_RESULT_INVALID",
                "Evidence Bundle manifest is invalid",
            ) from exc
        manifest_artifact = self._commit_manifest(request, manifest)
        try:
            return self._commit_database(
                command=command,
                request=request,
                manifest=manifest,
                context_artifact=context_artifact,
                manifest_artifact=manifest_artifact,
            )
        except IntegrityError as exc:
            replay = self._existing(command)
            if replay is not None:
                return replay
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_CONCURRENCY_CONFLICT",
                "Evidence Bundle publication conflicted with another transaction",
            ) from exc

    @staticmethod
    def _manifest_schema_version(entries: tuple[EvidenceEntryContract, ...]) -> str:
        if any(isinstance(entry.source, EducationalDocumentKnowledgeSourceV4) for entry in entries):
            return "evidence-bundle-manifest/4.0"
        if any(isinstance(entry.source, EducationalDocumentKnowledgeSourceV3) for entry in entries):
            return "evidence-bundle-manifest/3.0"
        return "evidence-bundle-manifest/2.0"

    def _existing(self, command: CreateEvidenceBundleCommand) -> EvidencePublicationContract | None:
        with self.sessions() as session:
            record = session.scalar(
                select(EducationRetrievalRequestRecord).where(
                    EducationRetrievalRequestRecord.idempotency_key == command.idempotency_key
                )
            )
            if record is None:
                return None
            if record.submission_sha256 != command.submission_sha256:
                raise KnowledgeRetrievalServiceError(
                    "KNOWLEDGE_RETRIEVAL_IDEMPOTENCY_CONFLICT",
                    "retrieval idempotency key has different input",
                )
            revision = session.scalar(
                select(EvidenceBundleRevisionRecord).where(
                    EvidenceBundleRevisionRecord.retrieval_request_id == record.retrieval_request_id
                )
            )
            if revision is None:
                raise KnowledgeRetrievalServiceError(
                    "KNOWLEDGE_RETRIEVAL_PUBLICATION_INCOMPLETE",
                    "retrieval request has no published Evidence Bundle",
                )
            return self._result(session, record, revision)

    def _snapshot_pointer(
        self, session: Session, graph_snapshot_revision_id: str
    ) -> KnowledgeGraphSnapshotPointer:
        snapshot = session.get(KnowledgeGraphSnapshotRecord, graph_snapshot_revision_id)
        if snapshot is None or snapshot.state != "PUBLISHED":
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_SNAPSHOT_INVALID",
                "requested graph snapshot is absent or unpublished",
            )
        logical = session.get(ArtifactRecord, snapshot.manifest_artifact_id)
        revision = session.get(ArtifactRevisionRecord, snapshot.manifest_artifact_revision_id)
        if (
            logical is None
            or revision is None
            or not logical.approved
            or not revision.approved
            or revision.logical_artifact_id != snapshot.manifest_artifact_id
            or revision.content_hash != snapshot.manifest_sha256
        ):
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_SNAPSHOT_STALE",
                "graph snapshot manifest pointer is stale",
            )
        manifest_schema_ref = _artifact_member_schema_ref(
            revision,
            member_path="projections/manifest.json",
            allowed=frozenset(
                {
                    "eom://schemas/knowledge/knowledge-graph-snapshot-manifest/2.0",
                    "eom://schemas/knowledge/knowledge-graph-snapshot-manifest/3.0",
                    "eom://schemas/knowledge/knowledge-graph-snapshot-manifest/4.0",
                    "eom://schemas/knowledge/knowledge-graph-snapshot-manifest/5.0",
                }
            ),
        )
        return KnowledgeGraphSnapshotPointer(
            graph_id=snapshot.graph_id,
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
        )

    @staticmethod
    def _policy(session: Session, access_policy_revision_id: str) -> EducationRetrievalAccessPolicy:
        record = session.get(
            EducationRetrievalAccessPolicyRevisionRecord, access_policy_revision_id
        )
        if record is None or record.state != "RELEASED":
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_POLICY_INVALID",
                "retrieval access policy is absent or unreleased",
            )
        try:
            validate_contract("education-retrieval-access-policy", record.canonical_document)
            policy = EducationRetrievalAccessPolicy.model_validate(record.canonical_document)
        except (ValueError, ValidationError) as exc:
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_POLICY_INVALID",
                "retrieval access policy document is invalid",
            ) from exc
        if (
            policy.access_policy_revision_id != record.access_policy_revision_id
            or policy.content_sha256 != record.content_sha256
        ):
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_POLICY_STALE",
                "retrieval access policy identity or hash differs",
            )
        return policy

    @staticmethod
    def _authorize(
        session: Session,
        command: CreateEvidenceBundleCommand,
        policy: EducationRetrievalAccessPolicy,
    ) -> None:
        operator = session.get(OperatorRecord, command.requested_by)
        if operator is None or operator.status != "ACTIVE":
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_REQUESTER_INVALID",
                "retrieval requester is absent or inactive",
            )
        permission_keys = set(command.requester_permission_keys)
        if "knowledge_graph:retrieve" not in permission_keys:
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_UNAUTHORIZED",
                "retrieval permission is absent",
            )
        if (
            command.query_kind not in policy.allowed_query_kinds
            or command.requester_role not in policy.allowed_requester_roles
            or not set(command.source_classes).issubset(policy.allowed_source_classes)
        ):
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_UNAUTHORIZED",
                "retrieval query, role, or source class is outside policy",
            )
        requested = command.evidence_budget
        maximum = policy.maximum_budget
        if any(
            left > right
            for left, right in (
                (requested.max_documents, maximum.max_documents),
                (requested.max_item_revisions, maximum.max_item_revisions),
                (requested.max_graph_nodes, maximum.max_graph_nodes),
                (requested.max_claims, maximum.max_claims),
                (requested.max_context_tokens, maximum.max_context_tokens),
            )
        ):
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_BUDGET_INVALID",
                "retrieval budget exceeds policy",
            )

    @staticmethod
    def _request(
        command: CreateEvidenceBundleCommand,
        *,
        snapshot_pointer: KnowledgeGraphSnapshotPointer,
        policy: EducationRetrievalAccessPolicy,
        retrieval_request_id: str,
        created_at: datetime,
    ) -> EducationRetrievalRequestV2:
        permissions = tuple(command.requester_permission_keys)
        value: dict[str, Any] = {
            "schema_version": "education-retrieval-request/2.0",
            "retrieval_request_id": retrieval_request_id,
            "graph_snapshot": snapshot_pointer.model_dump(mode="json"),
            "query_kind": command.query_kind,
            "curriculum_scope": (
                command.curriculum_scope.model_dump(mode="json")
                if command.curriculum_scope is not None
                else None
            ),
            "topic_keys": list(command.topic_keys),
            "target_item_revision_id": command.target_item_revision_id,
            "required_item_elements": list(command.required_item_elements),
            "source_classes": list(command.source_classes),
            "retrieval_mode": "HYBRID_LOCAL_MULTIHOP",
            "evidence_budget": command.evidence_budget.model_dump(mode="json"),
            "access_policy_revision_id": policy.access_policy_revision_id,
            "access_policy_sha256": policy.content_sha256,
            "requester_role": command.requester_role,
            "requester_operator_id": command.requested_by,
            "requester_permission_keys": list(permissions),
            "requester_permissions_sha256": content_sha256({"permission_keys": list(permissions)}),
            "requested_at": _utc_json(created_at),
            "request_sha256": "sha256:" + "0" * 64,
        }
        value["request_sha256"] = content_sha256(
            {key: item for key, item in value.items() if key != "request_sha256"}
        )
        try:
            validate_contract("education-retrieval-request-v2", value)
            return EducationRetrievalRequestV2.model_validate(value)
        except (ValueError, ValidationError) as exc:
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_REQUEST_INVALID",
                "resolved retrieval request is invalid",
            ) from exc

    def _candidates(
        self,
        session: Session,
        command: CreateEvidenceBundleCommand,
        policy: EducationRetrievalAccessPolicy,
    ) -> tuple[_Candidate, ...]:
        snapshot_id = command.graph_snapshot_revision_id
        max_nodes = min(command.evidence_budget.max_graph_nodes, MAX_RETRIEVAL_CANDIDATES)
        seed_scores: dict[str, int] = {}

        if command.curriculum_scope is not None:
            scope = command.curriculum_scope
            root = session.scalar(
                select(CurriculumUnitRecord).where(
                    CurriculumUnitRecord.graph_snapshot_revision_id == snapshot_id,
                    CurriculumUnitRecord.framework_revision_id == scope.framework_revision_id,
                    CurriculumUnitRecord.curriculum_unit_id == scope.root_unit_id,
                )
            )
            if root is None:
                raise KnowledgeRetrievalServiceError(
                    "KNOWLEDGE_RETRIEVAL_CURRICULUM_SCOPE_INVALID",
                    "pinned curriculum scope does not resolve in the snapshot",
                )
            unit_ids = [scope.root_unit_id]
            if scope.include_descendants:
                unit_ids = list(
                    session.scalars(
                        select(CurriculumUnitClosureRecord.descendant_unit_id)
                        .where(
                            CurriculumUnitClosureRecord.graph_snapshot_revision_id == snapshot_id,
                            CurriculumUnitClosureRecord.framework_revision_id
                            == scope.framework_revision_id,
                            CurriculumUnitClosureRecord.ancestor_unit_id == scope.root_unit_id,
                        )
                        .order_by(
                            CurriculumUnitClosureRecord.depth,
                            CurriculumUnitClosureRecord.descendant_unit_id,
                        )
                        .limit(max_nodes)
                    )
                )
            unit_nodes = session.execute(
                select(CurriculumUnitRecord.node_id, CurriculumUnitRecord.curriculum_unit_id).where(
                    CurriculumUnitRecord.graph_snapshot_revision_id == snapshot_id,
                    CurriculumUnitRecord.curriculum_unit_id.in_(unit_ids),
                )
            )
            for node_id, unit_id in unit_nodes:
                seed_scores[node_id] = max(
                    seed_scores.get(node_id, 0), 1000 if unit_id == scope.root_unit_id else 950
                )

        terms = sorted(
            {
                term
                for topic_key in command.topic_keys
                for term in knowledge_node_terms(topic_key, "")
            }
        )
        if terms:
            for node_id in session.scalars(
                select(KnowledgeNodeTermRecord.node_id)
                .where(
                    KnowledgeNodeTermRecord.graph_snapshot_revision_id == snapshot_id,
                    KnowledgeNodeTermRecord.term.in_(terms),
                )
                .order_by(KnowledgeNodeTermRecord.node_id)
                .limit(max_nodes)
            ):
                seed_scores[node_id] = max(seed_scores.get(node_id, 0), 1000)

        if command.required_item_elements:
            element_filter = [str(value) for value in command.required_item_elements]
            item_query = (
                select(ItemElementReferenceRecord.item_revision_id)
                .where(
                    ItemElementReferenceRecord.graph_snapshot_revision_id == snapshot_id,
                    ItemElementReferenceRecord.element_kind.in_(element_filter),
                )
                .group_by(ItemElementReferenceRecord.item_revision_id)
                .having(
                    func.count(distinct(ItemElementReferenceRecord.element_kind))
                    == len(element_filter)
                )
                .order_by(ItemElementReferenceRecord.item_revision_id)
                .limit(max(command.evidence_budget.max_item_revisions, 1) * 4)
            )
            if command.target_item_revision_id is not None:
                item_query = item_query.where(
                    ItemElementReferenceRecord.item_revision_id == command.target_item_revision_id
                )
            item_revisions = tuple(session.scalars(item_query))
            if command.target_item_revision_id is not None and not item_revisions:
                raise KnowledgeRetrievalServiceError(
                    "KNOWLEDGE_RETRIEVAL_ITEM_STRUCTURE_MISSING",
                    "target Item Revision lacks the required graph elements",
                )
            if item_revisions:
                for node_id in session.scalars(
                    select(ItemElementReferenceRecord.node_id)
                    .where(
                        ItemElementReferenceRecord.graph_snapshot_revision_id == snapshot_id,
                        ItemElementReferenceRecord.item_revision_id.in_(item_revisions),
                        ItemElementReferenceRecord.element_kind.in_(element_filter),
                    )
                    .order_by(ItemElementReferenceRecord.node_id)
                    .limit(max_nodes)
                ):
                    seed_scores[node_id] = max(seed_scores.get(node_id, 0), 975)

        if not seed_scores:
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_INSUFFICIENT_EVIDENCE",
                "retrieval query matched no graph seed",
            )
        scores = dict(sorted(seed_scores.items())[:max_nodes])
        frontier = set(scores)
        visited = set(frontier)
        for _hop, hop_score in ((1, 850), (2, 700)):
            if not frontier or len(visited) >= max_nodes:
                break
            rows = session.execute(
                select(KnowledgeEdgeRecord.from_node_id, KnowledgeEdgeRecord.to_node_id)
                .where(
                    KnowledgeEdgeRecord.graph_snapshot_revision_id == snapshot_id,
                    or_(
                        KnowledgeEdgeRecord.from_node_id.in_(frontier),
                        KnowledgeEdgeRecord.to_node_id.in_(frontier),
                    ),
                )
                .order_by(KnowledgeEdgeRecord.edge_id)
                .limit(max_nodes * 8)
            )
            next_frontier: set[str] = set()
            for from_node_id, to_node_id in rows:
                for node_id in (from_node_id, to_node_id):
                    if node_id not in visited:
                        next_frontier.add(node_id)
            for node_id in sorted(next_frontier)[: max_nodes - len(visited)]:
                scores[node_id] = hop_score
                visited.add(node_id)
            frontier = next_frontier.intersection(visited)

        node_rows = tuple(
            session.scalars(
                select(KnowledgeNodeRecord)
                .where(
                    KnowledgeNodeRecord.graph_snapshot_revision_id == snapshot_id,
                    KnowledgeNodeRecord.node_id.in_(visited),
                )
                .order_by(KnowledgeNodeRecord.node_id)
            )
        )
        nodes = {row.node_id: row for row in node_rows}
        pointer_rows = tuple(
            session.scalars(
                select(KnowledgeNodeSourcePointerRecord)
                .where(
                    KnowledgeNodeSourcePointerRecord.graph_snapshot_revision_id == snapshot_id,
                    KnowledgeNodeSourcePointerRecord.node_id.in_(nodes),
                    KnowledgeNodeSourcePointerRecord.source_class.in_(command.source_classes),
                )
                .order_by(
                    KnowledgeNodeSourcePointerRecord.artifact_revision_id,
                    KnowledgeNodeSourcePointerRecord.member_path,
                    KnowledgeNodeSourcePointerRecord.node_id,
                    KnowledgeNodeSourcePointerRecord.anchor_id,
                )
                .limit(max_nodes * MAX_POINTER_ROWS_PER_NODE)
            )
        )
        grouped: dict[tuple[str, str, str], list[KnowledgeNodeSourcePointerRecord]] = defaultdict(
            list
        )
        for pointer in pointer_rows:
            node = nodes.get(pointer.node_id)
            if node is None:
                continue
            if node.answer_bearing and command.requester_role not in policy.answer_bearing_roles:
                continue
            grouped[
                (pointer.analysis_run_id, pointer.artifact_revision_id, pointer.member_path)
            ].append(pointer)

        source_cache: dict[
            tuple[str, str, str], KnowledgeAnalysisSourceV3 | EducationalDocumentKnowledgeSourceV4
        ] = {}
        values: list[_Candidate] = []
        for key, pointers in sorted(grouped.items()):
            nodes_for_source = {
                pointer.node_id: nodes[pointer.node_id]
                for pointer in pointers
                if pointer.node_id in nodes
            }
            ordered_nodes = tuple(sorted(nodes_for_source))[:16]
            anchors = tuple(sorted({pointer.anchor_id for pointer in pointers}))[:32]
            if not ordered_nodes or not anchors:
                continue
            source = source_cache.get(key)
            if source is None:
                source = self._resolve_snapshot_source(session, snapshot_id, pointers[0])
                source_cache[key] = source
            if source.source_class not in command.source_classes:
                continue
            values.append(
                _Candidate(
                    analysis_run_id=pointers[0].analysis_run_id,
                    source=source,
                    node_ids=ordered_nodes,
                    anchor_ids=anchors,
                    node_labels=tuple(nodes_for_source[node_id].label for node_id in ordered_nodes),
                    node_types=tuple(
                        nodes_for_source[node_id].node_type for node_id in ordered_nodes
                    ),
                    relevance_milli=max(scores[node_id] for node_id in ordered_nodes),
                    answer_bearing=any(
                        nodes_for_source[node_id].answer_bearing for node_id in ordered_nodes
                    ),
                )
            )
        if not values:
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_INSUFFICIENT_EVIDENCE",
                "retrieval graph matched no authorized immutable source",
            )
        return tuple(
            sorted(
                values,
                key=lambda item: (
                    -item.relevance_milli,
                    item.source.artifact_member.artifact_revision_id,
                    item.source.artifact_member.member_path,
                    item.analysis_run_id,
                ),
            )[:MAX_RETRIEVAL_CANDIDATES]
        )

    def _resolve_snapshot_source(
        self,
        session: Session,
        snapshot_id: str,
        pointer: KnowledgeNodeSourcePointerRecord,
    ) -> KnowledgeAnalysisSourceV3 | EducationalDocumentKnowledgeSourceV4:
        association = session.scalar(
            select(KnowledgeSnapshotAnalysisRecord).where(
                KnowledgeSnapshotAnalysisRecord.graph_snapshot_revision_id == snapshot_id,
                KnowledgeSnapshotAnalysisRecord.analysis_run_id == pointer.analysis_run_id,
                KnowledgeSnapshotAnalysisRecord.source_revision_id == pointer.source_revision_id,
                KnowledgeSnapshotAnalysisRecord.source_artifact_revision_id
                == pointer.artifact_revision_id,
            )
        )
        if association is None:
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_SOURCE_POINTER_INVALID",
                "graph source pointer has no pinned accepted analysis",
            )
        run = session.get(KnowledgeAnalysisRunRecord, association.analysis_run_id)
        if run is None or run.state != "ACCEPTED":
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_SOURCE_STALE",
                "pinned graph analysis is absent or unaccepted",
            )
        try:
            schema_version = run.canonical_request.get("schema_version")
            document_source: (
                EducationalDocumentKnowledgeSourceV3 | EducationalDocumentKnowledgeSourceV4 | None
            )
            if schema_version == "knowledge-analysis-request/8.0":
                document_source = KnowledgeAnalysisRequestV8.model_validate(
                    run.canonical_request
                ).source
            elif schema_version == "knowledge-analysis-request/7.0":
                document_source = KnowledgeAnalysisRequestV7.model_validate(
                    run.canonical_request
                ).source
            elif schema_version == "knowledge-analysis-request/6.0":
                document_source = KnowledgeAnalysisRequestV6.model_validate(
                    run.canonical_request
                ).source
            elif schema_version == "knowledge-analysis-request/5.0":
                document_source = KnowledgeAnalysisRequestV5.model_validate(
                    run.canonical_request
                ).source
            elif schema_version == "knowledge-analysis-request/4.0":
                document_source = KnowledgeAnalysisRequestV4.model_validate(
                    run.canonical_request
                ).source
            elif schema_version == "knowledge-analysis-request/3.0":
                document_source = KnowledgeAnalysisRequestV3.model_validate(
                    run.canonical_request
                ).source
            else:
                document_source = None
            if document_source is not None:
                source: KnowledgeAnalysisSourceV3 | EducationalDocumentKnowledgeSourceV4 = (
                    document_source
                )
                actual: KnowledgeAnalysisSourceV3 | EducationalDocumentKnowledgeSourceV4 = (
                    resolve_educational_document_source(
                        session,
                        self.artifacts,
                        document_revision_id=document_source.document_revision_id,
                        source_class=document_source.source_class,
                        first_physical_page=document_source.first_physical_page,
                        last_physical_page=document_source.last_physical_page,
                        curriculum_unit_keys=document_source.curriculum_unit_keys,
                    )
                )
            else:
                legacy_source = KnowledgeAnalysisRequestV2.model_validate(
                    run.canonical_request
                ).source
                source = legacy_source
                actual = (
                    resolve_content_intake_source(
                        session,
                        intake_batch_id=legacy_source.intake_batch_id,
                        source_file_id=legacy_source.source_file_id,
                        source_class=legacy_source.source_class,
                    )
                    if isinstance(legacy_source, ContentIntakeKnowledgeSourceV2)
                    else resolve_approved_item_source(
                        session,
                        item_revision_id=legacy_source.item_revision_id,
                        source_class=legacy_source.source_class,
                    )
                )
        except (KnowledgeAnalysisSourceError, ValidationError, ValueError) as exc:
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_SOURCE_STALE",
                "pinned source can no longer be resolved exactly",
            ) from exc
        if (
            actual != source
            or actual.artifact_member.artifact_id != pointer.source_artifact_id
            or actual.artifact_member.artifact_revision_id != pointer.artifact_revision_id
            or actual.artifact_member.sha256 != pointer.source_sha256
            or actual.artifact_member.member_path != pointer.member_path
        ):
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_SOURCE_HASH_MISMATCH",
                "graph source pointer differs from the canonical source revision",
            )
        return actual

    @staticmethod
    def _rank_and_render(
        *,
        request: EducationRetrievalRequestV2,
        candidates: tuple[_Candidate, ...],
    ) -> tuple[tuple[EvidenceEntryContract, ...], str]:
        selected: list[EvidenceEntryContract] = []
        selected_immutable_sources: set[tuple[str, str, str]] = set()
        documents: set[str] = set()
        items: set[str] = set()
        nodes: set[str] = set()
        claim_count = 0
        lines = [
            "# EOM Evidence Bundle",
            "",
            f"- Retrieval request: `{request.retrieval_request_id}`",
            f"- Graph snapshot: `{request.graph_snapshot.graph_snapshot_revision_id}`",
            "",
            "## Ranked evidence",
            "",
        ]
        for candidate in candidates:
            source = candidate.source
            source_document = isinstance(
                source,
                ContentIntakeKnowledgeSourceV2
                | EducationalDocumentKnowledgeSourceV3
                | EducationalDocumentKnowledgeSourceV4,
            )
            if isinstance(source, ContentIntakeKnowledgeSourceV2):
                source_identity = source.source_file_id
            elif isinstance(
                source,
                EducationalDocumentKnowledgeSourceV3 | EducationalDocumentKnowledgeSourceV4,
            ):
                source_identity = source.document_revision_id
            else:
                source_identity = source.item_revision_id
            new_documents = documents | ({source_identity} if source_document else set())
            new_items = items | ({source_identity} if not source_document else set())
            new_nodes = nodes | set(candidate.node_ids)
            kind = KnowledgeRetrievalApplicationService._evidence_kind(candidate)
            new_claim_count = claim_count + (kind == "CLAIM")
            if (
                len(new_documents) > request.evidence_budget.max_documents
                or len(new_items) > request.evidence_budget.max_item_revisions
                or len(new_nodes) > request.evidence_budget.max_graph_nodes
                or new_claim_count > request.evidence_budget.max_claims
            ):
                continue
            use: Literal["GROUNDING", "REFERENCE_PATTERN", "AVOID_COPY"] = (
                "AVOID_COPY"
                if candidate.answer_bearing
                else ("GROUNDING" if source_document else "REFERENCE_PATTERN")
            )
            immutable_source = (
                source.artifact_member.artifact_revision_id,
                source.artifact_member.member_path,
                use,
            )
            if immutable_source in selected_immutable_sources:
                continue
            evidence_id = _typed_id(
                "evidenceitem_",
                {
                    "retrieval_request_id": request.retrieval_request_id,
                    "source_kind": source.source_kind,
                    "source_identity": source_identity,
                    "artifact_revision_id": source.artifact_member.artifact_revision_id,
                    "member_path": source.artifact_member.member_path,
                    "use": use,
                },
            )
            entry: EvidenceEntryContract
            if isinstance(source, EducationalDocumentKnowledgeSourceV4):
                entry = EvidenceEntryV4(
                    evidence_id=evidence_id,
                    evidence_kind=kind,
                    use=use,
                    source=source,
                    graph_node_ids=candidate.node_ids,
                    anchor_ids=candidate.anchor_ids,
                    relevance_milli=candidate.relevance_milli,
                    answer_bearing=candidate.answer_bearing,
                )
            elif isinstance(source, EducationalDocumentKnowledgeSourceV3):
                entry = EvidenceEntryV3(
                    evidence_id=evidence_id,
                    evidence_kind=kind,
                    use=use,
                    source=source,
                    graph_node_ids=candidate.node_ids,
                    anchor_ids=candidate.anchor_ids,
                    relevance_milli=candidate.relevance_milli,
                    answer_bearing=candidate.answer_bearing,
                )
            else:
                entry = EvidenceEntryV2(
                    evidence_id=evidence_id,
                    evidence_kind=kind,
                    use=use,
                    source=source,
                    graph_node_ids=candidate.node_ids,
                    anchor_ids=candidate.anchor_ids,
                    relevance_milli=candidate.relevance_milli,
                    answer_bearing=candidate.answer_bearing,
                )
            label = "; ".join(candidate.node_labels)
            line = (
                f"- `{entry.evidence_id}` score={entry.relevance_milli} use={entry.use} "
                f"source=`{source_identity}` nodes={','.join(entry.graph_node_ids)}: {label}"
            )
            proposed = "\n".join([*lines, line, ""])
            if (
                _context_tokens(proposed) > request.evidence_budget.max_context_tokens
                or len(proposed.encode("utf-8")) > MAX_CONTEXT_BYTES
            ):
                continue
            selected.append(entry)
            selected_immutable_sources.add(immutable_source)
            lines.append(line)
            documents = new_documents
            items = new_items
            nodes = new_nodes
            claim_count = int(new_claim_count)
            if len(selected) >= 128:
                break
        if not selected:
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_BUDGET_EXHAUSTED",
                "no authorized evidence fits the requested budget",
            )
        context = "\n".join([*lines, ""])
        return tuple(selected), context

    @staticmethod
    def _evidence_kind(
        candidate: _Candidate,
    ) -> Literal["DOCUMENT", "ITEM_REVISION", "CLAIM", "TABLE", "FIGURE", "EQUATION"]:
        types = set(candidate.node_types)
        if "CLAIM" in types:
            return "CLAIM"
        if "TABLE" in types:
            return "TABLE"
        if "FIGURE" in types:
            return "FIGURE"
        if "EQUATION" in types or "FORMULA" in types:
            return "EQUATION"
        if isinstance(candidate.source, ApprovedItemKnowledgeSourceV2):
            return "ITEM_REVISION"
        return "DOCUMENT"

    def _commit_context(
        self,
        request: EducationRetrievalRequestV2,
        markdown: str,
        *,
        entries: tuple[EvidenceEntryContract, ...],
    ) -> CatalogArtifact:
        try:
            with tempfile.TemporaryDirectory(
                prefix="evidence-context.", dir=self.settings.staging_root
            ) as raw_directory:
                source = Path(raw_directory) / "context.md"
                source.write_text(markdown, encoding="utf-8")
                source.chmod(0o640)
                multimodal_graph = any(
                    isinstance(entry.source, EducationalDocumentKnowledgeSourceV4)
                    for entry in entries
                )
                document_graph = multimodal_graph or any(
                    isinstance(entry.source, EducationalDocumentKnowledgeSourceV3)
                    for entry in entries
                )
                return self.artifacts.commit_file_set(
                    files={"evidence/context.md": source},
                    primary_file="evidence/context.md",
                    artifact_type="evidence-bundle-context",
                    idempotency_key=f"evidence-context:{request.retrieval_request_id}",
                    request={
                        "retrieval_request_id": request.retrieval_request_id,
                        "request_sha256": request.request_sha256,
                    },
                    result={"estimated_context_tokens": _context_tokens(markdown)},
                    file_metadata={
                        "evidence/context.md": {
                            "schema_ref": "eom://schemas/knowledge/evidence-bundle-context/1.0",
                            "media_type": "text/markdown",
                        }
                    },
                    manifest_version="evidence-bundle-context-file-set/1.0",
                    protocol_version=(
                        KNOWLEDGE_RETRIEVAL_MULTIMODAL_CATALOG_PROTOCOL
                        if multimodal_graph
                        else (
                            KNOWLEDGE_RETRIEVAL_DOCUMENT_CATALOG_PROTOCOL
                            if document_graph
                            else KNOWLEDGE_RETRIEVAL_CATALOG_PROTOCOL
                        )
                    ),
                    protocol_schema_hash=(
                        KNOWLEDGE_RETRIEVAL_MULTIMODAL_CATALOG_SCHEMA_HASH
                        if multimodal_graph
                        else (
                            KNOWLEDGE_RETRIEVAL_DOCUMENT_CATALOG_SCHEMA_HASH
                            if document_graph
                            else KNOWLEDGE_RETRIEVAL_CATALOG_SCHEMA_HASH
                        )
                    ),
                )
        except (OSError, RuntimeError, ValueError) as exc:
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_ARTIFACT_COMMIT_FAILED",
                "Evidence Bundle context Artifact commit failed",
            ) from exc

    def _commit_manifest(
        self, request: EducationRetrievalRequestV2, manifest: EvidenceManifestContract
    ) -> CatalogArtifact:
        try:
            with tempfile.TemporaryDirectory(
                prefix="evidence-manifest.", dir=self.settings.staging_root
            ) as raw_directory:
                source = Path(raw_directory) / "manifest.json"
                source.write_bytes(canonical_json_bytes(manifest))
                source.chmod(0o640)
                return self.artifacts.commit_file_set(
                    files={"evidence/manifest.json": source},
                    primary_file="evidence/manifest.json",
                    artifact_type="evidence-bundle-manifest",
                    idempotency_key=f"evidence-manifest:{request.retrieval_request_id}",
                    request={
                        "retrieval_request_id": request.retrieval_request_id,
                        "request_sha256": request.request_sha256,
                    },
                    result={
                        "evidence_bundle_revision_id": manifest.evidence_bundle_revision_id,
                        "manifest_sha256": manifest.manifest_sha256,
                    },
                    file_metadata={
                        "evidence/manifest.json": {
                            "schema_ref": (
                                "eom://schemas/knowledge/evidence-bundle-manifest/4.0"
                                if isinstance(manifest, EvidenceBundleManifestV4)
                                else (
                                    "eom://schemas/knowledge/evidence-bundle-manifest/3.0"
                                    if isinstance(manifest, EvidenceBundleManifestV3)
                                    else "eom://schemas/knowledge/evidence-bundle-manifest/2.0"
                                )
                            ),
                            "media_type": "application/json",
                        }
                    },
                    manifest_version="evidence-bundle-manifest-file-set/1.0",
                    protocol_version=(
                        KNOWLEDGE_RETRIEVAL_MULTIMODAL_CATALOG_PROTOCOL
                        if isinstance(manifest, EvidenceBundleManifestV4)
                        else (
                            KNOWLEDGE_RETRIEVAL_DOCUMENT_CATALOG_PROTOCOL
                            if isinstance(manifest, EvidenceBundleManifestV3)
                            else KNOWLEDGE_RETRIEVAL_CATALOG_PROTOCOL
                        )
                    ),
                    protocol_schema_hash=(
                        KNOWLEDGE_RETRIEVAL_MULTIMODAL_CATALOG_SCHEMA_HASH
                        if isinstance(manifest, EvidenceBundleManifestV4)
                        else (
                            KNOWLEDGE_RETRIEVAL_DOCUMENT_CATALOG_SCHEMA_HASH
                            if isinstance(manifest, EvidenceBundleManifestV3)
                            else KNOWLEDGE_RETRIEVAL_CATALOG_SCHEMA_HASH
                        )
                    ),
                )
        except (OSError, RuntimeError, ValueError) as exc:
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_ARTIFACT_COMMIT_FAILED",
                "Evidence Bundle manifest Artifact commit failed",
            ) from exc

    def _commit_database(
        self,
        *,
        command: CreateEvidenceBundleCommand,
        request: EducationRetrievalRequestV2,
        manifest: EvidenceManifestContract,
        context_artifact: CatalogArtifact,
        manifest_artifact: CatalogArtifact,
    ) -> EvidencePublicationContract:
        with transaction(self.sessions) as session:
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": command.idempotency_key},
            )
            existing = session.scalar(
                select(EducationRetrievalRequestRecord).where(
                    EducationRetrievalRequestRecord.idempotency_key == command.idempotency_key
                )
            )
            if existing is not None:
                if existing.submission_sha256 != command.submission_sha256:
                    raise KnowledgeRetrievalServiceError(
                        "KNOWLEDGE_RETRIEVAL_IDEMPOTENCY_CONFLICT",
                        "retrieval idempotency key has different input",
                    )
                revision = session.scalar(
                    select(EvidenceBundleRevisionRecord).where(
                        EvidenceBundleRevisionRecord.retrieval_request_id
                        == existing.retrieval_request_id
                    )
                )
                if revision is None:
                    raise KnowledgeRetrievalServiceError(
                        "KNOWLEDGE_RETRIEVAL_PUBLICATION_INCOMPLETE",
                        "retrieval request has no published Evidence Bundle",
                    )
                return self._result(session, existing, revision)
            self._snapshot_pointer(session, request.graph_snapshot.graph_snapshot_revision_id)
            self._policy(session, request.access_policy_revision_id)
            request_record = EducationRetrievalRequestRecord(
                retrieval_request_id=request.retrieval_request_id,
                idempotency_key=command.idempotency_key,
                submission_sha256=command.submission_sha256,
                request_sha256=request.request_sha256,
                canonical_request=request.model_dump(mode="json"),
                graph_snapshot_revision_id=request.graph_snapshot.graph_snapshot_revision_id,
                access_policy_revision_id=request.access_policy_revision_id,
                query_kind=request.query_kind,
                requester_role=request.requester_role,
                requester_operator_id=request.requester_operator_id,
                requester_permissions_sha256=request.requester_permissions_sha256,
                state="PUBLISHED",
                requested_at=request.requested_at,
            )
            bundle = EvidenceBundleRecord(
                evidence_bundle_id=manifest.evidence_bundle_id,
                retrieval_request_id=request.retrieval_request_id,
                current_revision_id=None,
                created_by_operator_id=request.requester_operator_id,
                created_at=manifest.created_at,
            )
            session.add_all([request_record, bundle])
            session.flush()
            revision = EvidenceBundleRevisionRecord(
                evidence_bundle_revision_id=manifest.evidence_bundle_revision_id,
                evidence_bundle_id=manifest.evidence_bundle_id,
                revision_number=manifest.revision_number,
                retrieval_request_id=request.retrieval_request_id,
                graph_snapshot_revision_id=request.graph_snapshot.graph_snapshot_revision_id,
                access_policy_revision_id=request.access_policy_revision_id,
                requester_permissions_sha256=request.requester_permissions_sha256,
                state="PUBLISHED",
                context_artifact_id=context_artifact.artifact_id,
                context_artifact_revision_id=context_artifact.revision_id,
                context_sha256=context_artifact.content_hash,
                manifest_artifact_id=manifest_artifact.artifact_id,
                manifest_artifact_revision_id=manifest_artifact.revision_id,
                manifest_sha256=manifest.manifest_sha256,
                document_count=manifest.budget.document_count,
                item_revision_count=manifest.budget.item_revision_count,
                graph_node_count=manifest.budget.graph_node_count,
                claim_count=manifest.budget.claim_count,
                estimated_context_tokens=manifest.budget.estimated_context_tokens,
                created_by_operator_id=request.requester_operator_id,
                created_at=manifest.created_at,
            )
            session.add(revision)
            session.flush()
            for entry in manifest.entries:
                source = entry.source
                member = source.artifact_member
                session.add(
                    EvidenceBundleEntryRecord(
                        evidence_bundle_revision_id=manifest.evidence_bundle_revision_id,
                        evidence_id=entry.evidence_id,
                        evidence_kind=entry.evidence_kind,
                        evidence_use=entry.use,
                        source_kind=source.source_kind,
                        source_class=source.source_class,
                        intake_batch_id=getattr(source, "intake_batch_id", None),
                        source_file_id=getattr(source, "source_file_id", None),
                        item_id=getattr(source, "item_id", None),
                        item_revision_id=getattr(source, "item_revision_id", None),
                        educational_document_id=getattr(source, "document_id", None),
                        educational_document_revision_id=getattr(
                            source, "document_revision_id", None
                        ),
                        source_artifact_id=member.artifact_id,
                        source_artifact_revision_id=member.artifact_revision_id,
                        source_member_path=member.member_path,
                        source_sha256=member.sha256,
                        source_bytes=member.bytes,
                        source_schema_ref=member.schema_ref,
                        source_media_type=member.media_type,
                        source_logical_name=member.logical_name,
                        graph_node_ids=list(entry.graph_node_ids),
                        anchor_ids=list(entry.anchor_ids),
                        relevance_milli=entry.relevance_milli,
                        answer_bearing=entry.answer_bearing,
                    )
                )
            bundle.current_revision_id = revision.evidence_bundle_revision_id
            session.flush()
            return self._result(session, request_record, revision)

    @staticmethod
    def _result(
        session: Session,
        request: EducationRetrievalRequestRecord,
        revision: EvidenceBundleRevisionRecord,
    ) -> EvidencePublicationContract:
        request_model = EducationRetrievalRequestV2.model_validate(request.canonical_request)
        policy = session.get(
            EducationRetrievalAccessPolicyRevisionRecord, revision.access_policy_revision_id
        )
        artifact_revision = session.get(
            ArtifactRevisionRecord, revision.manifest_artifact_revision_id
        )
        context_revision = session.get(
            ArtifactRevisionRecord, revision.context_artifact_revision_id
        )
        if (
            policy is None
            or artifact_revision is None
            or context_revision is None
            or policy.content_sha256 != request_model.access_policy_sha256
            or not artifact_revision.approved
            or artifact_revision.logical_artifact_id != revision.manifest_artifact_id
            or not context_revision.approved
            or context_revision.logical_artifact_id != revision.context_artifact_id
            or context_revision.content_hash != revision.context_sha256
        ):
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_PUBLICATION_INVALID",
                "published Evidence Bundle pointers do not resolve",
            )
        manifest_schema_ref = _artifact_member_schema_ref(
            artifact_revision,
            member_path="evidence/manifest.json",
            allowed=frozenset(
                {
                    "eom://schemas/knowledge/evidence-bundle-manifest/2.0",
                    "eom://schemas/knowledge/evidence-bundle-manifest/3.0",
                    "eom://schemas/knowledge/evidence-bundle-manifest/4.0",
                }
            ),
        )
        value: dict[str, Any] = {
            "schema_version": "evidence-bundle-publication-result/1.0",
            "evidence_bundle_id": revision.evidence_bundle_id,
            "evidence_bundle_revision_id": revision.evidence_bundle_revision_id,
            "revision_number": revision.revision_number,
            "state": revision.state,
            "retrieval_request_id": request.retrieval_request_id,
            "retrieval_request_sha256": request.request_sha256,
            "graph_snapshot": request_model.graph_snapshot.model_dump(mode="json"),
            "access_policy_revision_id": revision.access_policy_revision_id,
            "access_policy_sha256": policy.content_sha256,
            "manifest_artifact": KnowledgeArtifactMemberPointer(
                artifact_id=revision.manifest_artifact_id,
                artifact_revision_id=revision.manifest_artifact_revision_id,
                sha256=artifact_revision.content_hash,
                schema_ref=manifest_schema_ref,
                media_type="application/json",
                logical_name="manifest.json",
                member_path="evidence/manifest.json",
            ).model_dump(mode="json"),
            "manifest_sha256": revision.manifest_sha256,
            "budget": {
                "document_count": revision.document_count,
                "item_revision_count": revision.item_revision_count,
                "graph_node_count": revision.graph_node_count,
                "claim_count": revision.claim_count,
                "estimated_context_tokens": revision.estimated_context_tokens,
            },
            "published_at": _utc_json(revision.created_at),
            "result_sha256": "sha256:" + "0" * 64,
        }
        if manifest_schema_ref.endswith(("/3.0", "/4.0")):
            value.update(
                {
                    "schema_version": (
                        "evidence-bundle-publication-result/4.0"
                        if manifest_schema_ref.endswith("/4.0")
                        else "evidence-bundle-publication-result/3.0"
                    ),
                    "requester_permissions_sha256": revision.requester_permissions_sha256,
                    "context_artifact": KnowledgeArtifactMemberPointer(
                        artifact_id=revision.context_artifact_id,
                        artifact_revision_id=revision.context_artifact_revision_id,
                        sha256=revision.context_sha256,
                        schema_ref="eom://schemas/knowledge/evidence-bundle-context/1.0",
                        media_type="text/markdown",
                        logical_name="context.md",
                        member_path="evidence/context.md",
                    ).model_dump(mode="json"),
                }
            )
        value["result_sha256"] = content_sha256(
            {key: item for key, item in value.items() if key != "result_sha256"}
        )
        if manifest_schema_ref.endswith("/4.0"):
            validate_contract("evidence-bundle-publication-result-v4", value)
            return EvidenceBundlePublicationResultV4.model_validate(value)
        if manifest_schema_ref.endswith("/3.0"):
            validate_contract("evidence-bundle-publication-result-v3", value)
            return EvidenceBundlePublicationResultV3.model_validate(value)
        validate_contract("evidence-bundle-publication-result", value)
        return EvidenceBundlePublicationResult.model_validate(value)

    def _result_v2(
        self,
        session: Session,
        request: EducationRetrievalRequestRecord,
        revision: EvidenceBundleRevisionRecord,
    ) -> ItemProductionEvidencePublicationContract:
        base = self._result(session, request, revision)
        if isinstance(base, EvidenceBundlePublicationResultV3 | EvidenceBundlePublicationResultV4):
            return base
        context_revision = session.get(
            ArtifactRevisionRecord, revision.context_artifact_revision_id
        )
        if (
            context_revision is None
            or not context_revision.approved
            or context_revision.logical_artifact_id != revision.context_artifact_id
            or context_revision.content_hash != revision.context_sha256
        ):
            raise KnowledgeRetrievalServiceError(
                "KNOWLEDGE_RETRIEVAL_PUBLICATION_INVALID",
                "Evidence Bundle context pointer does not resolve",
            )
        value: dict[str, Any] = {
            **base.model_dump(mode="json", exclude={"schema_version", "result_sha256"}),
            "schema_version": "evidence-bundle-publication-result/2.0",
            "requester_permissions_sha256": revision.requester_permissions_sha256,
            "context_artifact": KnowledgeArtifactMemberPointer(
                artifact_id=revision.context_artifact_id,
                artifact_revision_id=revision.context_artifact_revision_id,
                sha256=revision.context_sha256,
                schema_ref="eom://schemas/knowledge/evidence-bundle-context/1.0",
                media_type="text/markdown",
                logical_name="context.md",
                member_path="evidence/context.md",
            ).model_dump(mode="json"),
            "result_sha256": "sha256:" + "0" * 64,
        }
        value["result_sha256"] = content_sha256(
            {key: item for key, item in value.items() if key != "result_sha256"}
        )
        validate_contract("evidence-bundle-publication-result-v2", value)
        return EvidenceBundlePublicationResultV2.model_validate(value)
