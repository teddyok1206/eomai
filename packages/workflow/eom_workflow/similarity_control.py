"""Grounded variation plan with a separate similarity pin, not a new workflow or source grant."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypeAlias

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.inference_transfer_experiment import PopulationSource
from eom_catalog_contracts.knowledge import (
    EducationalRetrievalRequirement,
    EducationalRetrievalRequirementV2,
)
from eom_catalog_contracts.models import FrozenModel
from eom_catalog_contracts.similarity_context import (
    ApprovedReferenceItemAnchor,
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
from jsonschema.exceptions import ValidationError as SchemaValidationError
from pydantic import ConfigDict, TypeAdapter, model_validator

from eom_workflow.control_plane import ResolvedExecutionPlanV19
from eom_workflow.control_schemas import validate_control_contract

MAX_SIMILARITY_EXECUTION_PLAN_BYTES = 1024 * 1024
SIMILARITY_EXECUTION_PLAN_SCHEMAS = frozenset(
    {"resolved-execution-plan/23.0", "resolved-execution-plan/24.0"}
)
POST_REGISTRATION_GROUNDED_PLAN_SCHEMAS = SIMILARITY_EXECUTION_PLAN_SCHEMAS | {
    "resolved-execution-plan/19.0"
}


@dataclass(frozen=True, slots=True)
class PreparedSimilarityPlan:
    """Checked immutable values only; actual publication/source/Pack authority stays with owner."""

    delivery: SimilarityContextDelivery
    context: SimilarityContext

    def __post_init__(self) -> None:
        if not isinstance(self.delivery, SimilarityContextDelivery) or not isinstance(
            self.context, FrozenModel
        ):
            raise ValueError("SIMILARITY_PLAN_PREPARATION_INVALID")
        context = parse_similarity_context(self.context)
        validate_similarity_context_delivery(
            self.delivery, context, expected_request=context.request
        )


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
        return _similarity_plan_document(value, "resolved-execution-plan-v23")

    @model_validator(mode="after")
    def exact_variation_and_authoring(self) -> ResolvedExecutionPlanV23:
        _validate_reference_roles(self)
        return self


class ResolvedExecutionPlanV24(ResolvedExecutionPlanV19):
    """Ordinary authoring/review share one exact reference, not a draft-vector verdict."""

    model_config = ConfigDict(revalidate_instances="always")

    schema_version: Literal["resolved-execution-plan/24.0"] = "resolved-execution-plan/24.0"  # type: ignore[assignment]
    resolver_version: Literal["24.0.0"] = "24.0.0"  # type: ignore[assignment]
    retrieval_requirement: EducationalRetrievalRequirement
    similarity_delivery: SimilarityContextDelivery
    similarity_reference: ApprovedReferenceItemAnchor

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        return _similarity_plan_document(value, "resolved-execution-plan-v24")

    @model_validator(mode="after")
    def exact_ordinary_reference(self) -> ResolvedExecutionPlanV24:
        _validate_reference_roles(self)
        return self


# Runtime dispatch uses isinstance; a PEP695 TypeAliasType cannot be its argument.
SupportedSimilarityExecutionPlan: TypeAlias = (  # noqa: UP040
    ResolvedExecutionPlanV23 | ResolvedExecutionPlanV24
)


def _similarity_plan_document(value: object, schema_name: str) -> dict[str, object]:
    document = raw_similarity_contract_value(value)
    if not isinstance(document, dict):
        raise ValueError("SIMILARITY_PLAN_INVALID")
    if len(canonical_json_bytes(document)) > MAX_SIMILARITY_EXECUTION_PLAN_BYTES:
        raise ValueError("SIMILARITY_PLAN_TOO_LARGE")
    validate_control_contract(schema_name, document)
    return document


def _validate_reference_roles(plan: ResolvedExecutionPlanV19) -> None:
    authoring = tuple(step for step in plan.steps if step.role == "authoring")
    if len(authoring) != 1 or authoring[0].step_key != "authoring":
        raise ValueError("SIMILARITY_PLAN_AUTHORING_INVALID")
    if any(
        step.role in {"authoring", "review"} and step.evidence_access != "EVIDENCE_CONTEXT"
        for step in plan.steps
    ):
        raise ValueError("SIMILARITY_PLAN_REFERENCE_ACCESS_INVALID")
    if plan.graph_snapshot.manifest_artifact.sha256 != plan.graph_snapshot.manifest_sha256:
        raise ValueError("SIMILARITY_PLAN_GRAPH_INVALID")


def parse_similarity_execution_plan(value: object) -> ResolvedExecutionPlanV23:
    return ResolvedExecutionPlanV23.model_validate(value)


def parse_authoring_similarity_execution_plan(value: object) -> ResolvedExecutionPlanV24:
    return ResolvedExecutionPlanV24.model_validate(value)


def parse_supported_similarity_execution_plan(value: object) -> SupportedSimilarityExecutionPlan:
    document = raw_similarity_contract_value(value)
    if isinstance(document, dict):
        if document.get("schema_version") == "resolved-execution-plan/23.0":
            return parse_similarity_execution_plan(document)
        if document.get("schema_version") == "resolved-execution-plan/24.0":
            return parse_authoring_similarity_execution_plan(document)
    raise ValueError("SIMILARITY_PLAN_UNSUPPORTED")


def parse_post_registration_grounded_plan(
    document: dict[str, object],
) -> ResolvedExecutionPlanV19 | SupportedSimilarityExecutionPlan:
    """One explicit family choice for existing consumers, without rewriting old plan values."""
    schema = document.get("schema_version")
    if schema in SIMILARITY_EXECUTION_PLAN_SCHEMAS:
        try:
            return parse_supported_similarity_execution_plan(document)
        except SchemaValidationError:
            raise ValueError("POST_REGISTRATION_GROUNDED_PLAN_INVALID") from None
    if schema == "resolved-execution-plan/19.0":
        return ResolvedExecutionPlanV19.model_validate(document)
    raise ValueError("POST_REGISTRATION_GROUNDED_PLAN_UNSUPPORTED")


def validate_similarity_plan_context(
    plan: SupportedSimilarityExecutionPlan, context: SimilarityContext
) -> SimilarityContext:
    """Pure exact value closure; current source/operator/producer authorization is separate."""
    checked = parse_supported_similarity_execution_plan(plan)
    context = parse_similarity_context(context)
    context = validate_similarity_context_delivery(
        checked.similarity_delivery, context, expected_request=context.request
    )
    validate_similarity_plan_request(checked, context.request)
    return context


def validate_similarity_plan_request(
    plan: SupportedSimilarityExecutionPlan, request: SimilarityContextRequest
) -> None:
    """Expected current request must bind the same original source/Graph/policy before IO."""
    checked = parse_supported_similarity_execution_plan(plan)
    request = parse_similarity_context_request(request)
    if (
        request.request_sha256 != checked.similarity_delivery.request_sha256
        or request.anchor.source.source_class != "PAST_EXAM"
        or request.graph_snapshot != checked.graph_snapshot
        or request.policy_revision_id != checked.access_policy_revision_id
        or request.policy_sha256 != checked.access_policy_sha256
    ):
        raise ValueError("SIMILARITY_PLAN_CONTEXT_MISMATCH")
    if isinstance(checked, ResolvedExecutionPlanV23):
        if request.consumer_purpose != "PAST_EXAM_VARIATION" or (
            request.anchor.source.item_revision_id
            != checked.retrieval_requirement.past_exam_variation.source_item_revision_id
        ):
            raise ValueError("SIMILARITY_PLAN_CONTEXT_MISMATCH")
    elif request.consumer_purpose != "ITEM_AUTHORING" or (
        request.anchor != checked.similarity_reference
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


def bind_authoring_similarity_execution_plan(
    unpersisted_base: ResolvedExecutionPlanV19,
    delivery: SimilarityContextDelivery,
    context: SimilarityContext,
) -> ResolvedExecutionPlanV24:
    """Fresh ordinary plan only; same immutable reference is retained across review attempts."""
    original = raw_similarity_contract_value(unpersisted_base)
    validate_control_contract("resolved-execution-plan-v19", original)
    base = ResolvedExecutionPlanV19.model_validate(original)
    if type(base.retrieval_requirement) is not EducationalRetrievalRequirement:
        raise ValueError("SIMILARITY_PLAN_ORDINARY_REQUIREMENT_MISMATCH")
    context = parse_similarity_context(context)
    pin = parse_similarity_context_delivery(delivery)
    document = base.model_dump(mode="json") | {
        "schema_version": "resolved-execution-plan/24.0",
        "resolver_version": "24.0.0",
        "similarity_delivery": pin.model_dump(mode="json"),
        "similarity_reference": context.request.anchor.model_dump(mode="json"),
    }
    document["plan_sha256"] = content_sha256(
        {key: value for key, value in document.items() if key != "plan_sha256"}
    )
    result = parse_authoring_similarity_execution_plan(document)
    validate_similarity_plan_context(result, context)
    return result


def validate_similarity_original_source(
    plan: SupportedSimilarityExecutionPlan,
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
    _require_same_reference_source(anchor, expected)


def _require_same_reference_source(anchor: PopulationSource, expected: PopulationSource) -> None:
    """Immutable semantic member identity, not its workspace alias or extra current lineage."""
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


def select_similarity_evidence_source(
    plan: SupportedSimilarityExecutionPlan, sources: tuple[PopulationSource, ...]
) -> PopulationSource:
    """Exact one-pass Evidence membership, never source selection by a worker or score."""
    checked = parse_supported_similarity_execution_plan(plan)
    anchor_revision = (
        checked.retrieval_requirement.past_exam_variation.source_item_revision_id
        if isinstance(checked, ResolvedExecutionPlanV23)
        else checked.similarity_reference.source.item_revision_id
    )
    matches = tuple(
        source
        for source in sources
        if source.source_class == "PAST_EXAM" and source.item_revision_id == anchor_revision
    )
    if len(matches) != 1:
        raise ValueError("SIMILARITY_ORIGINAL_SOURCE_MISMATCH")
    original: PopulationSource = TypeAdapter(PopulationSource).validate_python(
        raw_similarity_contract_value(matches[0])
    )
    if isinstance(checked, ResolvedExecutionPlanV24):
        _require_same_reference_source(checked.similarity_reference.source, original)
    return original
