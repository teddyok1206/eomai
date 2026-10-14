"""Canonical context delivery values and pure associations, never source authority."""

from __future__ import annotations

from typing import Literal

from eom_identifiers import content_sha256
from eom_protocol.artifact_members import ArtifactMemberPointer
from pydantic import ConfigDict, model_validator

from eom_catalog_contracts.embedding_reference_query import similarity_contract_document
from eom_catalog_contracts.models import FrozenModel, Sha256
from eom_catalog_contracts.similarity_context import (
    SimilarityContext,
    SimilarityContextRequest,
    parse_similarity_context,
    parse_similarity_context_request,
)

SIMILARITY_DELIVERY_SCHEMA = "system-rag-similarity-delivery"
SIMILARITY_DELIVERY_REF = "eom://schemas/knowledge/system-rag-similarity-delivery/1.0"
MAX_SIMILARITY_DELIVERY_BYTES = 8 * 1024


class SimilarityContextDelivery(FrozenModel):
    """Small immutable pin; raw member and semantic hashes have different meanings."""

    model_config = ConfigDict(revalidate_instances="always")

    schema_version: Literal["system-rag-similarity-delivery/1.0"] = (
        "system-rag-similarity-delivery/1.0"
    )
    context_member: ArtifactMemberPointer
    request_sha256: Sha256
    context_sha256: Sha256

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        return similarity_contract_document(
            value, SIMILARITY_DELIVERY_SCHEMA, MAX_SIMILARITY_DELIVERY_BYTES
        )


def parse_similarity_context_delivery(value: object) -> SimilarityContextDelivery:
    return SimilarityContextDelivery.model_validate(value)


def validate_deliverable_similarity_context(
    context: SimilarityContext, *, expected_request: SimilarityContextRequest
) -> SimilarityContext:
    """Validate supplied values only; caller must independently reauthorize current sources."""
    checked = parse_similarity_context(context)
    request = parse_similarity_context_request(expected_request)
    if checked.request != request or checked.status == "FAILED":
        raise ValueError("SIMILARITY_CONTEXT_DELIVERY_INVALID")
    if request.vector_mode == "REQUIRED" and (
        checked.status == "UNAVAILABLE"
        or checked.query_execution is None
        or checked.population is None
        or any(view.status == "UNAVAILABLE" for view in checked.population.views)
    ):
        raise ValueError("SIMILARITY_CONTEXT_REQUIRED_VECTOR_UNAVAILABLE")
    return checked


def validate_similarity_context_delivery(
    delivery: SimilarityContextDelivery,
    context: SimilarityContext,
    *,
    expected_request: SimilarityContextRequest,
) -> SimilarityContext:
    """Pure resolved-value closure, not a filesystem/lifecycle/permission check or read grant."""
    pin = parse_similarity_context_delivery(delivery)
    checked = validate_deliverable_similarity_context(context, expected_request=expected_request)
    if (
        pin.request_sha256 != checked.request.request_sha256
        or pin.context_sha256 != checked.context_sha256
        or pin.context_member.sha256 != content_sha256(checked.model_dump(mode="json"))
    ):
        raise ValueError("SIMILARITY_CONTEXT_DELIVERY_INVALID")
    return checked
