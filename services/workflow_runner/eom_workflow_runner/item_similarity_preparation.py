"""Current source/action authority → canonical reference context → checked plan value."""

from __future__ import annotations

import re
from dataclasses import dataclass

from eom_catalog_contracts import EvidenceBundlePublicationResultV5, validate_contract
from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.knowledge import EducationalRetrievalRequirementV2
from eom_catalog_contracts.similarity_context import (
    MAX_SIMILARITY_CONTEXT_BYTES,
    SimilarityContext,
    SimilarityContextRequest,
    parse_similarity_context,
)
from eom_catalog_contracts.similarity_delivery import (
    validate_deliverable_similarity_context,
    validate_similarity_context_delivery,
)
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryCaller,
    validate_embedding_registry_actor,
)
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_identity_service import OperatorAuthorizationFenceError
from eom_identity_service.repository import effective_permissions
from eom_image_contracts import SVG_LABEL_LAYOUT_PACK_BUNDLES
from eom_operator_identity import PermissionKey
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.execution_resolver import validate_educational_retrieval_policy
from eom_orchestrator.file_set_control_artifacts import (
    CONTROL_FILE_SET_PROTOCOL,
    ControlFileSetPublisher,
)
from eom_orchestrator.similarity_context_artifact import (
    SIMILARITY_CONTEXT_ARTIFACT_TYPE,
    PublishedSimilarityContext,
    publish_similarity_context,
)
from eom_workflow.control_plane import ExecutionPresetRevisionV2
from eom_workflow.control_schemas import validate_control_contract
from eom_workflow.models import ExpectedWorkflowResolution, WorkflowId, WorkflowRequest
from eom_workflow.similarity_control import PreparedSimilarityPlan
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import TypeAdapter
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from eom_workflow_runner.reference_query_consumer_read import CatalogCompletedReferenceQueryRead
from eom_workflow_runner.similarity_context_session_reader import (
    CatalogSimilaritySessionContextReader,
)


@dataclass(frozen=True, slots=True)
class PreparedItemSimilarity:
    """Bounded local handoff metadata, not current authority or a new persistent receipt."""

    plan: PreparedSimilarityPlan
    publication: PublishedSimilarityContext
    workflow_request_sha256: str
    evidence_result_sha256: str
    preset_content_sha256: str
    resolution: ExpectedWorkflowResolution


def _current_context(
    value: SimilarityContext, expected_request: SimilarityContextRequest
) -> SimilarityContext:
    checked = parse_similarity_context(value)
    if checked.status == "FAILED":
        raise ControlPlaneError(
            "CONTROL_SIMILARITY_AUTHORITY_DENIED"
            if checked.error_code in {"SOURCE_ACCESS_DENIED", "SOURCE_REVOKED"}
            else "CONTROL_SIMILARITY_AUTHORITY_UNAVAILABLE"
            if checked.error_code == "AUTHORITY_UNAVAILABLE"
            else "CONTROL_SIMILARITY_PREPARATION_INVALID",
            "current reference context unavailable",
        )
    return validate_deliverable_similarity_context(checked, expected_request=expected_request)


class CatalogItemSimilarityPreparation:
    """Owner-only composition. Never construct this privileged graph inside the isolated API."""

    def __init__(
        self,
        query: CatalogCompletedReferenceQueryRead,
        publisher: ControlFileSetPublisher,
        *,
        source_commit: str,
    ) -> None:
        if (
            not isinstance(query, CatalogCompletedReferenceQueryRead)
            or not isinstance(publisher, ControlFileSetPublisher)
            or type(source_commit) is not str
            or re.fullmatch(r"[0-9a-f]{40}", source_commit) is None
        ):
            raise ValueError("ITEM_SIMILARITY_PREPARATION_CONFIGURATION_INVALID")
        self.query = query
        self.publisher = publisher
        self.source_commit = source_commit

    def _require_start_permission(self, session: Session, caller: EmbeddingRegistryCaller) -> None:
        self.query.owner.identity.fence_current_operator(session, caller.operator_id)
        try:
            with session.no_autoflush:
                permissions = effective_permissions(session, caller.operator_id)
        except (SQLAlchemyError, ValueError):
            raise OperatorAuthorizationFenceError(
                "OPERATOR_AUTHORIZATION_FENCE_UNAVAILABLE"
            ) from None
        if PermissionKey.WORKFLOW_START not in permissions:
            raise OperatorAuthorizationFenceError("OPERATOR_AUTHORIZATION_FENCE_FORBIDDEN")

    def prepare(
        self,
        caller: EmbeddingRegistryCaller,
        *,
        workflow_request: WorkflowRequest,
        expected_resolution: ExpectedWorkflowResolution,
        evidence: EvidenceBundlePublicationResultV5,
        preset: ExecutionPresetRevisionV2,
    ) -> PreparedItemSimilarity:
        """May commit an Artifact; a late error never means it was absent/unprocessed."""
        try:
            validate_embedding_registry_actor(caller)
            query_workflow_id = TypeAdapter(WorkflowId).validate_python(
                self.query.workflow_id, strict=True
            )
            if type(caller) is not EmbeddingRegistryCaller or (
                caller.operator_id != self.query.request.operator_audit.operator_id
            ):
                raise ValueError("ITEM_SIMILARITY_PREPARATION_CALLER_INVALID")
            raw_evidence = raw_similarity_contract_value(evidence)
            raw_preset = raw_similarity_contract_value(preset)
            validate_contract("evidence-bundle-publication-result-v5", raw_evidence)
            validate_control_contract("execution-preset-revision-v2", raw_preset)
            evidence = EvidenceBundlePublicationResultV5.model_validate(raw_evidence)
            preset = ExecutionPresetRevisionV2.model_validate(raw_preset)
            workflow_request = WorkflowRequest.model_validate(
                raw_similarity_contract_value(workflow_request)
            )
            expected = ExpectedWorkflowResolution.model_validate(
                raw_similarity_contract_value(expected_resolution)
            )
            requirement = workflow_request.educational_retrieval
            context_request = self.query.request.context_request
            policy = preset.retrieval_policy
            if (
                not isinstance(requirement, EducationalRetrievalRequirementV2)
                or (
                    workflow_request.expected_resolution is not None
                    and workflow_request.expected_resolution != expected
                )
                or expected.workflow_definition_key != "generic-item-development"
                or expected.workflow_definition_version != "1.16.0"
                or expected.content_pack_key != "generated-knowledge-item"
                or expected.content_pack_version != "1.20.17"
                or expected.content_pack_bundle_sha256 != SVG_LABEL_LAYOUT_PACK_BUNDLES["1.20.17"]
                or expected.execution_preset_id != preset.preset_id
                or expected.execution_preset_revision_id != preset.preset_revision_id
                or expected.execution_preset_content_sha256 != preset.content_sha256
                or expected.execution_preset_key != workflow_request.execution_preset_key
                or "workflow-role/1.24.0" not in preset.compatible_workflow_protocols
                or preset.state != "RELEASED"
                or policy is None
                or workflow_request.content_pack is None
                or workflow_request.content_pack.pack_key != expected.content_pack_key
                or context_request.consumer_purpose != "PAST_EXAM_VARIATION"
                or requirement.past_exam_variation.source_item_revision_id
                != context_request.anchor.source.item_revision_id
                or evidence.graph_snapshot != context_request.graph_snapshot
                or evidence.access_policy_revision_id != context_request.policy_revision_id
                or evidence.access_policy_sha256 != context_request.policy_sha256
                or policy.access_policy_revision_id != evidence.access_policy_revision_id
                or policy.access_policy_sha256 != evidence.access_policy_sha256
                or not set(context_request.source_classes).issubset(policy.allowed_source_classes)
            ):
                raise ValueError("ITEM_SIMILARITY_PREPARATION_SCOPE_MISMATCH")
            validate_educational_retrieval_policy(preset, requirement)
        except (ValueError, TypeError, SchemaError):
            raise ControlPlaneError(
                "CONTROL_SIMILARITY_PREPARATION_INVALID", "item preparation inputs differ"
            ) from None
        key = "item-similarity:" + content_sha256(
            {
                "operator_id": caller.operator_id,
                "query_workflow_id": query_workflow_id,
                "context_request_sha256": context_request.request_sha256,
            }
        ).removeprefix("sha256:")
        common = CatalogSimilaritySessionContextReader(self.query)
        with self.query.sessions.begin() as session:
            try:
                self._require_start_permission(session, caller)
                context = _current_context(
                    common.compose_in_session(session, caller, context_request), context_request
                )
                # Validation is pure; the current owner/root above is the source authority.
                publication = publish_similarity_context(
                    self.publisher,
                    context=context,
                    expected_request=context_request,
                    idempotency_key=key,
                    source_commit=self.source_commit,
                )
                pin = publication.delivery.context_member
                reader = PinnedArtifactReadContext(session, self.query.owner.settings)
                reader.prefetch(((pin.artifact_id, pin.artifact_revision_id),))
                reader.require_file_set(
                    pin.artifact_id,
                    pin.artifact_revision_id,
                    ("context.json",),
                    manifest_version=CONTROL_FILE_SET_PROTOCOL,
                    manifest_sha256=publication.manifest_sha256,
                )
                read_arguments = pin.model_dump(mode="python") | {
                    "expected_artifact_types": (SIMILARITY_CONTEXT_ARTIFACT_TYPE,),
                    "expected_primary_file": "context.json",
                    "max_bytes": MAX_SIMILARITY_CONTEXT_BYTES,
                }
                member = reader.read_pinned(**read_arguments)
                if (
                    member.producer_job_id != publication.owner_job_id
                    or member.payload != canonical_json_bytes(context.model_dump(mode="json"))
                ):
                    raise ValueError("ITEM_SIMILARITY_PREPARATION_BYTES_MISMATCH")
                late = _current_context(
                    common.compose_in_session(session, caller, context_request), context_request
                )
                if late != context:
                    raise ValueError("ITEM_SIMILARITY_PREPARATION_SOURCE_CHANGED")
                validate_similarity_context_delivery(
                    publication.delivery, late, expected_request=context_request
                )
                reader.revalidate_provenance()
                if reader.read_pinned(**read_arguments).payload != member.payload:
                    raise ValueError("ITEM_SIMILARITY_PREPARATION_MEMBER_CHANGED")
                self._require_start_permission(session, caller)
                return PreparedItemSimilarity(
                    PreparedSimilarityPlan(publication.delivery, context),
                    publication,
                    content_sha256(workflow_request.model_dump(mode="json")),
                    evidence.result_sha256,
                    preset.content_sha256,
                    expected,
                )
            except OperatorAuthorizationFenceError as error:
                raise ControlPlaneError(
                    "CONTROL_SIMILARITY_AUTHORITY_DENIED"
                    if error.code == "OPERATOR_AUTHORIZATION_FENCE_FORBIDDEN"
                    else "CONTROL_SIMILARITY_AUTHORITY_UNAVAILABLE",
                    "current owner unavailable",
                ) from None
            except (ValueError, TypeError, SchemaError):
                raise ControlPlaneError(
                    "CONTROL_SIMILARITY_PREPARATION_INVALID", "context preparation did not close"
                ) from None
