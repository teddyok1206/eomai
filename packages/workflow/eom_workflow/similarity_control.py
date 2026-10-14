"""Grounded variation plan with a separate similarity pin, not a new workflow or source grant."""

from __future__ import annotations

from typing import Literal

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.inference_transfer_experiment import PopulationSource
from eom_catalog_contracts.knowledge import EducationalRetrievalRequirementV2
from eom_catalog_contracts.similarity_context import (
    SimilarityContext,
    SimilarityContextRequest,
    parse_similarity_context,
    parse_similarity_context_request,
)
from eom_catalog_contracts.similarity_delivery import (
    SimilarityContextDelivery,
    parse_similarity_context_delivery,
    validate_similarity_context_delivery,
)
from eom_identifiers import canonical_json_bytes, content_sha256
from pydantic import ConfigDict, TypeAdapter, model_validator

from eom_workflow.control_plane import ResolvedExecutionPlanV19
from eom_workflow.control_schemas import validate_control_contract

MAX_SIMILARITY_EXECUTION_PLAN_BYTES = 1024 * 1024


class ResolvedExecutionPlanV23(ResolvedExecutionPlanV19):
    """Same workflow1.16 topology; auxiliary context is delivered to authoring/review only."""

    model_config = ConfigDict(revalidate_instances="always")

    schema_version: Literal["resolved-execution-plan/23.0"] = "resolved-execution-plan/23.0"  # type: ignore[assignment]
    resolver_version: Literal["23.0.0"] = "23.0.0"  # type: ignore[assignment]
    retrieval_requirement: EducationalRetrievalRequirementV2  # type: ignore[assignment]
    similarity_delivery: SimilarityContextDelivery

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        document = raw_similarity_contract_value(value)
        if not isinstance(document, dict):
            raise ValueError("SIMILARITY_PLAN_INVALID")
        if len(canonical_json_bytes(document)) > MAX_SIMILARITY_EXECUTION_PLAN_BYTES:
            raise ValueError("SIMILARITY_PLAN_TOO_LARGE")
        validate_control_contract("resolved-execution-plan-v23", document)
        return document

    @model_validator(mode="after")
    def exact_variation_and_authoring(self) -> ResolvedExecutionPlanV23:
        authoring = tuple(step for step in self.steps if step.role == "authoring")
        if len(authoring) != 1 or authoring[0].step_key != "authoring":
            raise ValueError("SIMILARITY_PLAN_AUTHORING_INVALID")
        if any(
            step.role in {"authoring", "review"} and step.evidence_access != "EVIDENCE_CONTEXT"
            for step in self.steps
        ):
            raise ValueError("SIMILARITY_PLAN_REFERENCE_ACCESS_INVALID")
        if self.graph_snapshot.manifest_artifact.sha256 != self.graph_snapshot.manifest_sha256:
            raise ValueError("SIMILARITY_PLAN_GRAPH_INVALID")
        return self


def parse_similarity_execution_plan(value: object) -> ResolvedExecutionPlanV23:
    return ResolvedExecutionPlanV23.model_validate(value)


def validate_similarity_plan_context(
    plan: ResolvedExecutionPlanV23, context: SimilarityContext
) -> SimilarityContext:
    """Pure exact value closure; current source/operator/producer authorization is separate."""
    checked = parse_similarity_execution_plan(plan)
    context = parse_similarity_context(context)
    context = validate_similarity_context_delivery(
        checked.similarity_delivery, context, expected_request=context.request
    )
    validate_similarity_plan_request(checked, context.request)
    return context


def validate_similarity_plan_request(
    plan: ResolvedExecutionPlanV23, request: SimilarityContextRequest
) -> None:
    """Expected current request must bind the same original source/Graph/policy before IO."""
    checked = parse_similarity_execution_plan(plan)
    request = parse_similarity_context_request(request)
    if (
        request.request_sha256 != checked.similarity_delivery.request_sha256
        or request.consumer_purpose != "PAST_EXAM_VARIATION"
        or request.anchor.source.source_class != "PAST_EXAM"
        or request.anchor.source.item_revision_id
        != checked.retrieval_requirement.past_exam_variation.source_item_revision_id
        or request.graph_snapshot != checked.graph_snapshot
        or request.policy_revision_id != checked.access_policy_revision_id
        or request.policy_sha256 != checked.access_policy_sha256
    ):
        raise ValueError("SIMILARITY_PLAN_CONTEXT_MISMATCH")


def bind_similarity_execution_plan(
    unpersisted_base: ResolvedExecutionPlanV19,
    delivery: SimilarityContextDelivery,
    context: SimilarityContext,
) -> ResolvedExecutionPlanV23:
    """Build from an unpersisted candidate; never upgrade or overwrite historical plan19.

    Actual owner must preserve its existing-plan replay/unique-workflow boundary and
    validate current source/Pack/instruction compatibility before committing a new plan.
    """
    original = raw_similarity_contract_value(unpersisted_base)
    validate_control_contract("resolved-execution-plan-v19", original)
    base = ResolvedExecutionPlanV19.model_validate(original)
    pin = parse_similarity_context_delivery(delivery)
    document = base.model_dump(mode="json") | {
        "schema_version": "resolved-execution-plan/23.0",
        "resolver_version": "23.0.0",
        "similarity_delivery": pin.model_dump(mode="json"),
    }
    document["plan_sha256"] = content_sha256(
        {key: value for key, value in document.items() if key != "plan_sha256"}
    )
    result = parse_similarity_execution_plan(document)
    validate_similarity_plan_context(result, context)
    return result


def validate_similarity_original_source(
    plan: ResolvedExecutionPlanV23,
    context: SimilarityContext,
    original: PopulationSource,
) -> None:
    """Retain full current lineage while matching the original immutable Item/content member.

    Workspace aliases/logical names are not identity. Extra current page/occurrence
    lineage is retained and authorized by the common owner, not downcast into Evidence.
    """
    checked = validate_similarity_plan_context(plan, context)
    expected: PopulationSource = TypeAdapter(PopulationSource).validate_python(
        raw_similarity_contract_value(original)
    )
    anchor = checked.request.anchor.source
    if (
        expected.source_class != "PAST_EXAM"
        or anchor.item_id != expected.item_id
        or anchor.item_revision_id != expected.item_revision_id
        or any(
            getattr(anchor.artifact_member, field) != getattr(expected.artifact_member, field)
            for field in (
                "artifact_id",
                "artifact_revision_id",
                "member_path",
                "sha256",
                "bytes",
                "schema_ref",
                "media_type",
            )
        )
    ):
        raise ValueError("SIMILARITY_ORIGINAL_SOURCE_MISMATCH")
