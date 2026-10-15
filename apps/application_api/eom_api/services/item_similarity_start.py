"""Private checked preparation acceptance in the existing item-start transaction.

No value here authenticates a caller, reads source bytes or admits native execution.
Only trusted application composition supplies an owner-produced preparation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from eom_catalog_contracts import EvidenceBundlePublicationResultV5, validate_contract
from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.models import Sha256
from eom_catalog_contracts.similarity_read import CompletedSimilarityQuerySelection
from eom_identifiers import content_sha256
from eom_operator_identity import ActorContext, ActorType, PermissionKey
from eom_operator_identity.contracts import OperatorId
from eom_orchestrator.similarity_context_artifact import PublishedSimilarityContext
from eom_protocol.models import JobId
from eom_workflow.control_plane import ExecutionPresetRevisionV2
from eom_workflow.control_schemas import validate_control_contract
from eom_workflow.models import ExpectedWorkflowResolution, WorkflowRequest
from eom_workflow.similarity_control import (
    PreparedSimilarityPlan,
    ResolvedExecutionPlanV23,
    validate_similarity_plan_context,
)
from eom_workflow_runner.item_similarity_preparation import PreparedItemSimilarity
from eom_workflow_runner.models import WorkflowDefinitionRecord
from eom_workflow_runner.similarity_role_preparation import SIMILARITY_QUERY_CONTEXT_KEY
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import TypeAdapter

from eom_api.errors import ApiError

SIMILARITY_PREPARATION_ACCEPTANCE_KEY = "similarity_preparation_v1_sha256"


@dataclass(frozen=True, slots=True)
class CheckedSimilarityStart:
    """Pure operation-local binding value, never current authority or a durable grant."""

    preparation: PreparedItemSimilarity
    fingerprint: str


def _invalid() -> ApiError:
    return ApiError(
        409,
        "CONTROL_SIMILARITY_PREPARATION_INVALID",
        "Similarity preparation differs",
        "The private preparation does not match the exact item request and resolution.",
    )


def selected_workflow_resolution(
    *,
    definition: WorkflowDefinitionRecord,
    runtime_context: dict[str, Any],
    preset: ExecutionPresetRevisionV2,
    preset_key: str,
) -> ExpectedWorkflowResolution:
    """One pure mapping for preflight expectations and actual transaction checks."""
    try:
        pack = runtime_context["content_pack"]
        return ExpectedWorkflowResolution(
            workflow_definition_key=definition.definition_key,
            workflow_definition_version=definition.definition_version,
            workflow_definition_sha256=definition.definition_hash,
            content_pack_release_id=pack["release_id"],
            content_pack_key=pack["pack_key"],
            content_pack_version=pack["version"],
            content_pack_bundle_sha256=pack["release_sha256"],
            content_pack_source_tree_sha256=pack["source_tree_sha256"],
            execution_preset_id=preset.preset_id,
            execution_preset_revision_id=preset.preset_revision_id,
            execution_preset_key=preset_key,
            execution_preset_content_sha256=preset.content_sha256,
        )
    except (ValueError, TypeError, AttributeError, KeyError):
        raise _invalid() from None


def check_similarity_start(
    preparation: PreparedItemSimilarity, request: WorkflowRequest, actor: ActorContext
) -> CheckedSimilarityStart:
    try:
        if type(preparation) is not PreparedItemSimilarity or (
            type(preparation.plan) is not PreparedSimilarityPlan
            or type(preparation.publication) is not PublishedSimilarityContext
        ):
            raise ValueError("invalid preparation value")
        preparation.plan.__post_init__()
        selection = CompletedSimilarityQuerySelection.model_validate(preparation.query_selection)
        expected = ExpectedWorkflowResolution.model_validate(
            raw_similarity_contract_value(preparation.resolution)
        )
        TypeAdapter(OperatorId).validate_python(preparation.operator_id, strict=True)
        TypeAdapter(JobId).validate_python(preparation.publication.owner_job_id, strict=True)
        for digest in (
            preparation.workflow_request_sha256,
            preparation.evidence_result_sha256,
            preparation.preset_content_sha256,
            preparation.publication.manifest_sha256,
        ):
            TypeAdapter(Sha256).validate_python(digest, strict=True)
        if (
            preparation.publication.delivery != preparation.plan.delivery
            or selection.context_request_sha256 != preparation.plan.context.request.request_sha256
            or preparation.workflow_request_sha256
            != content_sha256(request.model_dump(mode="json"))
            or preparation.preset_content_sha256 != expected.execution_preset_content_sha256
            or request.execution_preset_key != expected.execution_preset_key
            or (request.expected_resolution is not None and request.expected_resolution != expected)
        ):
            raise ValueError("preparation request differs")
    except (ValueError, TypeError, AttributeError, KeyError, SchemaError):
        raise _invalid() from None
    if (
        actor.actor_type is not ActorType.OPERATOR
        or actor.actor_id != preparation.operator_id
        or PermissionKey.WORKFLOW_START not in actor.permissions
    ):
        raise ApiError(
            403,
            "CONTROL_SIMILARITY_AUTHORITY_DENIED",
            "Similarity caller differs",
            "The authenticated item-start caller differs from the prepared operator.",
        )
    fingerprint = content_sha256(
        {
            "purpose": "ITEM_SIMILARITY_PREPARATION_V1",
            "operator_id": preparation.operator_id,
            "workflow_request_sha256": preparation.workflow_request_sha256,
            "evidence_result_sha256": preparation.evidence_result_sha256,
            "preset_content_sha256": preparation.preset_content_sha256,
            "resolution": expected.model_dump(mode="json"),
            "query_selection": selection.model_dump(mode="json"),
            "delivery": preparation.plan.delivery.model_dump(mode="json"),
            "context_sha256": preparation.plan.context.context_sha256,
            "publication": {
                "owner_job_id": preparation.publication.owner_job_id,
                "manifest_sha256": preparation.publication.manifest_sha256,
            },
        }
    )
    return CheckedSimilarityStart(preparation, fingerprint)


def require_similarity_start_resolution(
    checked: CheckedSimilarityStart,
    *,
    definition: WorkflowDefinitionRecord,
    runtime_context: dict[str, Any] | None,
    preset: ExecutionPresetRevisionV2 | None,
    evidence: object,
) -> None:
    """Compare actual transaction-selected values, never resolve a current/latest pointer."""
    try:
        if runtime_context is None or not isinstance(evidence, EvidenceBundlePublicationResultV5):
            raise ValueError("missing preparation scope")
        raw_preset = raw_similarity_contract_value(preset)
        raw_evidence = raw_similarity_contract_value(evidence)
        validate_control_contract("execution-preset-revision-v2", raw_preset)
        validate_contract("evidence-bundle-publication-result-v5", raw_evidence)
        current_preset = ExecutionPresetRevisionV2.model_validate(raw_preset)
        current_evidence = EvidenceBundlePublicationResultV5.model_validate(raw_evidence)
        expected = checked.preparation.resolution
        current = selected_workflow_resolution(
            definition=definition,
            runtime_context=runtime_context,
            preset=current_preset,
            preset_key=expected.execution_preset_key,
        )
        if (
            current != expected
            or current_preset.state != "RELEASED"
            or current_evidence.result_sha256 != checked.preparation.evidence_result_sha256
            or current_preset.content_sha256 != checked.preparation.preset_content_sha256
        ):
            raise ValueError("transaction preparation pins differ")
    except (ValueError, TypeError, AttributeError, KeyError, SchemaError):
        raise _invalid() from None


def similarity_start_context(
    context: dict[str, Any], checked: CheckedSimilarityStart, plan: object
) -> dict[str, Any]:
    """Small immutable acceptance metadata; caller commits it with plan and START."""
    try:
        if not isinstance(plan, ResolvedExecutionPlanV23):
            raise ValueError("similarity plan not bound before persistence")
        validate_similarity_plan_context(plan, checked.preparation.plan.context)
        if plan.similarity_delivery != checked.preparation.plan.delivery:
            raise ValueError("prepared delivery differs")
        result = dict(context)
        result[SIMILARITY_QUERY_CONTEXT_KEY] = checked.preparation.query_selection.model_dump(
            mode="json"
        )
        result[SIMILARITY_PREPARATION_ACCEPTANCE_KEY] = checked.fingerprint
        return result
    except (ValueError, TypeError, AttributeError, KeyError, SchemaError):
        raise _invalid() from None


def require_similarity_start_replay(
    context: dict[str, Any], checked: CheckedSimilarityStart
) -> None:
    """Metadata-only original acceptance; no current source/activation or bytes read."""
    if (
        context.get(SIMILARITY_QUERY_CONTEXT_KEY)
        != checked.preparation.query_selection.model_dump(mode="json")
        or context.get(SIMILARITY_PREPARATION_ACCEPTANCE_KEY) != checked.fingerprint
    ):
        raise ApiError(
            409,
            "CONTROL_SIMILARITY_PREPARATION_CONFLICT",
            "Similarity preparation conflict",
            "Existing workflow acceptance cannot acquire or replace its prepared context.",
        )
