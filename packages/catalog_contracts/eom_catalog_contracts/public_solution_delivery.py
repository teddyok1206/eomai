"""Pure closed context3/4 delivery association; never publication or source authority."""

from __future__ import annotations

from types import MappingProxyType
from typing import Literal

from eom_identifiers import content_sha256
from eom_protocol.artifact_members import ArtifactMemberPointer
from pydantic import ConfigDict, model_validator

from eom_catalog_contracts.embedding_reference_query import similarity_contract_document
from eom_catalog_contracts.models import FrozenModel, Sha256
from eom_catalog_contracts.public_solution_similarity import PUBLIC_SOLUTION_SIMILARITY_REF
from eom_catalog_contracts.registered_public_solution_similarity import (
    REGISTERED_PUBLIC_SIMILARITY_REF,
    SupportedPublicSolutionSimilarityContext,
    SupportedPublicSolutionSimilarityRequest,
    parse_supported_public_solution_similarity_context,
    parse_supported_public_solution_similarity_request,
)
from eom_catalog_contracts.similarity_delivery import MAX_SIMILARITY_DELIVERY_BYTES

PUBLIC_SOLUTION_DELIVERY_SCHEMA = "system-rag-similarity-delivery-v2"
PUBLIC_SOLUTION_DELIVERY_REF = "eom://schemas/knowledge/system-rag-similarity-delivery/2.0"
_CONTEXT_REFS = MappingProxyType(
    {
        "system-rag-similarity-context/3.0": PUBLIC_SOLUTION_SIMILARITY_REF,
        "system-rag-similarity-context/4.0": REGISTERED_PUBLIC_SIMILARITY_REF,
    }
)


class PublicSolutionSimilarityDelivery(FrozenModel):
    """Exact immutable auxiliary member; permission and lifecycle are checked by its owner."""

    model_config = ConfigDict(revalidate_instances="always", hide_input_in_errors=True)

    schema_version: Literal["system-rag-similarity-delivery/2.0"] = (
        "system-rag-similarity-delivery/2.0"
    )
    context_member: ArtifactMemberPointer
    request_sha256: Sha256
    context_sha256: Sha256

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        return similarity_contract_document(
            value, PUBLIC_SOLUTION_DELIVERY_SCHEMA, MAX_SIMILARITY_DELIVERY_BYTES
        )


def parse_public_solution_similarity_delivery(value: object) -> PublicSolutionSimilarityDelivery:
    return PublicSolutionSimilarityDelivery.model_validate(value)


def public_solution_context_schema_ref(context: SupportedPublicSolutionSimilarityContext) -> str:
    """Family identifier only, for an already parsed context; never resolution or authority."""
    return _CONTEXT_REFS[context.schema_version]


def validate_deliverable_public_solution_context(
    context: SupportedPublicSolutionSimilarityContext,
    *,
    expected_request: SupportedPublicSolutionSimilarityRequest,
) -> SupportedPublicSolutionSimilarityContext:
    """One exact pre-publication rule for all supported public context families."""
    checked = parse_supported_public_solution_similarity_context(context)
    request = parse_supported_public_solution_similarity_request(expected_request)
    if (
        checked.status == "FAILED"
        or checked.request != request
        or checked.query_execution is None
        or checked.population is None
    ):
        raise ValueError("PUBLIC_SOLUTION_SIMILARITY_DELIVERY_INVALID")
    return checked


def validate_public_solution_similarity_delivery(
    delivery: PublicSolutionSimilarityDelivery,
    context: SupportedPublicSolutionSimilarityContext,
    *,
    expected_request: SupportedPublicSolutionSimilarityRequest,
) -> SupportedPublicSolutionSimilarityContext:
    """Preserve partial/empty observations; compare original pins instead of repairing them."""
    pin = parse_public_solution_similarity_delivery(delivery)
    checked = validate_deliverable_public_solution_context(
        context, expected_request=expected_request
    )
    if (
        pin.context_member.schema_ref != public_solution_context_schema_ref(checked)
        or pin.request_sha256 != checked.request.request_sha256
        or pin.context_sha256 != checked.context_sha256
        or pin.context_member.sha256 != content_sha256(checked.model_dump(mode="json"))
    ):
        raise ValueError("PUBLIC_SOLUTION_SIMILARITY_DELIVERY_INVALID")
    return checked
