"""Explicit public-reference plan successors; no source authority or historical upgrades."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Self, TypeAlias

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.inference_transfer_experiment import PopulationSource
from eom_catalog_contracts.knowledge import (
    EducationalRetrievalRequirement,
    EducationalRetrievalRequirementV2,
)
from eom_catalog_contracts.public_solution_delivery import (
    PublicSolutionSimilarityDelivery,
    parse_public_solution_similarity_delivery,
    validate_public_solution_similarity_delivery,
)
from eom_catalog_contracts.public_solution_reference import PublicSolutionSourceReference
from eom_catalog_contracts.registered_public_solution_similarity import (
    SupportedPublicSolutionSimilarityContext,
    SupportedPublicSolutionSimilarityRequest,
    parse_supported_public_solution_similarity_context,
    parse_supported_public_solution_similarity_request,
)
from eom_catalog_contracts.similarity_materials import MAX_SIMILARITY_MATERIAL_CANDIDATES
from eom_identifiers import content_sha256
from pydantic import ConfigDict, TypeAdapter, model_validator

from eom_workflow.control_plane import ResolvedExecutionPlanV19
from eom_workflow.control_schemas import validate_control_contract
from eom_workflow.similarity_control import (
    _require_same_reference_source,
    _similarity_plan_document,
    _validate_reference_roles,
)

PUBLIC_SIMILARITY_PLAN_SCHEMAS = frozenset(
    {"resolved-execution-plan/30.0", "resolved-execution-plan/31.0"}
)
PUBLIC_SIMILARITY_PACK_VERSION = "1.20.18"


@dataclass(frozen=True, slots=True)
class PreparedPublicSimilarityPlan:
    """Pure checked values; Catalog and Orchestrator retain actual publication authority."""

    delivery: PublicSolutionSimilarityDelivery
    context: SupportedPublicSolutionSimilarityContext

    def __post_init__(self) -> None:
        context = parse_supported_public_solution_similarity_context(self.context)
        if len(context.candidates) > MAX_SIMILARITY_MATERIAL_CANDIDATES:
            raise ValueError("PUBLIC_SIMILARITY_ROLE_REFERENCE_BUDGET_EXCEEDED")
        validate_public_solution_similarity_delivery(
            self.delivery, context, expected_request=context.request
        )


class ResolvedExecutionPlanV30(ResolvedExecutionPlanV19):
    """Existing variation topology and Evidence, with public delivery2 instead of profile1."""

    model_config = ConfigDict(revalidate_instances="always", hide_input_in_errors=True)

    schema_version: Literal["resolved-execution-plan/30.0"] = "resolved-execution-plan/30.0"  # type: ignore[assignment]
    resolver_version: Literal["30.0.0"] = "30.0.0"  # type: ignore[assignment]
    retrieval_requirement: EducationalRetrievalRequirementV2  # type: ignore[assignment]
    similarity_delivery: PublicSolutionSimilarityDelivery

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        return _similarity_plan_document(value, "resolved-execution-plan-v30")

    @model_validator(mode="after")
    def exact_reference_roles(self) -> Self:
        _validate_reference_roles(self)
        return self


class ResolvedExecutionPlanV31(ResolvedExecutionPlanV19):
    """Existing ordinary topology; reference is not a private draft vector comparison."""

    model_config = ConfigDict(revalidate_instances="always", hide_input_in_errors=True)

    schema_version: Literal["resolved-execution-plan/31.0"] = "resolved-execution-plan/31.0"  # type: ignore[assignment]
    resolver_version: Literal["31.0.0"] = "31.0.0"  # type: ignore[assignment]
    retrieval_requirement: EducationalRetrievalRequirement
    similarity_delivery: PublicSolutionSimilarityDelivery
    similarity_reference: PublicSolutionSourceReference

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        return _similarity_plan_document(value, "resolved-execution-plan-v31")

    @model_validator(mode="after")
    def exact_reference_roles(self) -> Self:
        _validate_reference_roles(self)
        if self.similarity_reference.source.source_class != "PAST_EXAM":
            raise ValueError("PUBLIC_SIMILARITY_PLAN_REFERENCE_INVALID")
        return self


SupportedPublicSimilarityExecutionPlan: TypeAlias = (  # noqa: UP040
    ResolvedExecutionPlanV30 | ResolvedExecutionPlanV31
)


def parse_public_similarity_execution_plan(value: object) -> SupportedPublicSimilarityExecutionPlan:
    document = raw_similarity_contract_value(value)
    if isinstance(document, dict):
        match document.get("schema_version"):
            case "resolved-execution-plan/30.0":
                return ResolvedExecutionPlanV30.model_validate(document)
            case "resolved-execution-plan/31.0":
                return ResolvedExecutionPlanV31.model_validate(document)
    raise ValueError("PUBLIC_SIMILARITY_PLAN_UNSUPPORTED")


def validate_public_similarity_plan_request(
    plan: SupportedPublicSimilarityExecutionPlan,
    request: SupportedPublicSolutionSimilarityRequest,
) -> None:
    checked = parse_public_similarity_execution_plan(plan)
    request = parse_supported_public_solution_similarity_request(request)
    if (
        request.request_sha256 != checked.similarity_delivery.request_sha256
        or not isinstance(request.anchor, PublicSolutionSourceReference)
        or request.anchor.source.source_class != "PAST_EXAM"
        or request.graph_snapshot != checked.graph_snapshot
        or request.policy_revision_id != checked.access_policy_revision_id
        or request.policy_sha256 != checked.access_policy_sha256
    ):
        raise ValueError("PUBLIC_SIMILARITY_PLAN_CONTEXT_MISMATCH")
    if isinstance(checked, ResolvedExecutionPlanV30):
        if request.consumer_purpose != "PAST_EXAM_VARIATION" or (
            request.anchor.source.item_revision_id
            != checked.retrieval_requirement.past_exam_variation.source_item_revision_id
        ):
            raise ValueError("PUBLIC_SIMILARITY_PLAN_CONTEXT_MISMATCH")
    elif request.consumer_purpose != "ITEM_AUTHORING" or (
        request.anchor != checked.similarity_reference
    ):
        raise ValueError("PUBLIC_SIMILARITY_PLAN_CONTEXT_MISMATCH")


def validate_public_similarity_plan_context(
    plan: SupportedPublicSimilarityExecutionPlan,
    context: SupportedPublicSolutionSimilarityContext,
) -> SupportedPublicSolutionSimilarityContext:
    checked = parse_public_similarity_execution_plan(plan)
    context = parse_supported_public_solution_similarity_context(context)
    validate_public_solution_similarity_delivery(
        checked.similarity_delivery, context, expected_request=context.request
    )
    validate_public_similarity_plan_request(checked, context.request)
    return context


def bind_public_similarity_execution_plan(
    unpersisted_base: ResolvedExecutionPlanV19,
    delivery: PublicSolutionSimilarityDelivery,
    context: SupportedPublicSolutionSimilarityContext,
) -> SupportedPublicSimilarityExecutionPlan:
    """One fresh candidate only; the application owns uniqueness, replay and current grants."""
    original = raw_similarity_contract_value(unpersisted_base)
    validate_control_contract("resolved-execution-plan-v19", original)
    base = ResolvedExecutionPlanV19.model_validate(original)
    context = parse_supported_public_solution_similarity_context(context)
    pin = parse_public_solution_similarity_delivery(delivery)
    if isinstance(base.retrieval_requirement, EducationalRetrievalRequirementV2):
        version = 30
    elif type(base.retrieval_requirement) is EducationalRetrievalRequirement:
        version = 31
    else:
        raise ValueError("PUBLIC_SIMILARITY_PLAN_REQUIREMENT_INVALID")
    document = base.model_dump(mode="json") | {
        "schema_version": f"resolved-execution-plan/{version}.0",
        "resolver_version": f"{version}.0.0",
        "similarity_delivery": pin.model_dump(mode="json"),
    }
    if version == 31:
        document["similarity_reference"] = context.request.anchor.model_dump(mode="json")
    result = parse_public_similarity_execution_plan(
        document
        | {
            "plan_sha256": content_sha256(
                {key: value for key, value in document.items() if key != "plan_sha256"}
            )
        }
    )
    validate_public_similarity_plan_context(result, context)
    return result


def validate_public_similarity_original_source(
    plan: SupportedPublicSimilarityExecutionPlan,
    context: SupportedPublicSolutionSimilarityContext,
    original: PopulationSource,
) -> None:
    checked = validate_public_similarity_plan_context(plan, context)
    expected: PopulationSource = TypeAdapter(PopulationSource).validate_python(
        raw_similarity_contract_value(original)
    )
    _require_same_reference_source(checked.request.anchor.source, expected)


def select_public_similarity_evidence_source(
    plan: SupportedPublicSimilarityExecutionPlan, sources: tuple[PopulationSource, ...]
) -> PopulationSource:
    checked = parse_public_similarity_execution_plan(plan)
    revision = (
        checked.retrieval_requirement.past_exam_variation.source_item_revision_id
        if isinstance(checked, ResolvedExecutionPlanV30)
        else checked.similarity_reference.source.item_revision_id
    )
    matches = tuple(
        source
        for source in sources
        if source.source_class == "PAST_EXAM" and source.item_revision_id == revision
    )
    if len(matches) != 1:
        raise ValueError("SIMILARITY_ORIGINAL_SOURCE_MISMATCH")
    original: PopulationSource = TypeAdapter(PopulationSource).validate_python(
        raw_similarity_contract_value(matches[0])
    )
    if isinstance(checked, ResolvedExecutionPlanV31):
        _require_same_reference_source(checked.similarity_reference.source, original)
    return original
