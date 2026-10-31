"""API-only completed QUERY publication metadata, not native launch or item acceptance."""

from __future__ import annotations

from typing import ClassVar, Literal

from eom_identifiers import content_sha256
from pydantic import ConfigDict, Field, model_validator

from eom_catalog_contracts.embedding_reference_query import (
    raw_similarity_contract_value,
    similarity_contract_document,
)
from eom_catalog_contracts.models import FrozenModel, Sha256
from eom_catalog_contracts.public_solution_delivery import PublicSolutionSimilarityDelivery
from eom_catalog_contracts.similarity_context import SimilarityFailureCode
from eom_catalog_contracts.similarity_delivery import SimilarityContextDelivery
from eom_catalog_contracts.similarity_read import CompletedSimilarityQuerySelection

MAX_ITEM_SIMILARITY_PUBLICATION_REQUEST_BYTES = 2048
MAX_ITEM_SIMILARITY_PUBLICATION_REPLY_BYTES = 4096
ITEM_SIMILARITY_PUBLICATION_OPERATION = "PUBLISH_ITEM_SIMILARITY_CONTEXT"
type ItemSimilarityPublicationErrorCode = (
    SimilarityFailureCode
    | Literal[
        "ITEM_SIMILARITY_PUBLICATION_REQUEST_INVALID",
        "ITEM_SIMILARITY_PUBLICATION_UNAVAILABLE",
        "ITEM_SIMILARITY_PUBLICATION_BUDGET_EXCEEDED",
    ]
)


class _PublicationValue(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always")
    maximum_bytes: ClassVar[int] = MAX_ITEM_SIMILARITY_PUBLICATION_REPLY_BYTES - 1
    schema_name: ClassVar[str] = "system-rag-item-similarity-publication"

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        return similarity_contract_document(value, cls.schema_name, cls.maximum_bytes)


class ItemSimilarityPublication(_PublicationValue):
    owner_job_id: str = Field(pattern=r"^job_[0-9a-f]{32}$")
    delivery: SimilarityContextDelivery
    manifest_sha256: Sha256


class ItemSimilarityPublicationRequest(_PublicationValue):
    maximum_bytes = MAX_ITEM_SIMILARITY_PUBLICATION_REQUEST_BYTES - 1
    schema_version: Literal["system-rag-item-similarity-publication-request/1.0"]
    operation: Literal["PUBLISH_ITEM_SIMILARITY_CONTEXT"]
    actor_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    selection: CompletedSimilarityQuerySelection


class ItemSimilarityPublicationReply(_PublicationValue):
    schema_version: Literal["system-rag-item-similarity-publication-reply/1.0"]
    operation: Literal["PUBLISH_ITEM_SIMILARITY_CONTEXT"]
    status: Literal["SUCCESS", "FAILED"]
    actor_id: str | None = Field(pattern=r"^operator_[0-9a-f]{32}$")
    request_sha256: Sha256 | None
    publication: ItemSimilarityPublication | None
    error_code: ItemSimilarityPublicationErrorCode | None


def validate_item_similarity_publication_reply(
    request: ItemSimilarityPublicationRequest, reply: ItemSimilarityPublicationReply
) -> None:
    request = ItemSimilarityPublicationRequest.model_validate(request)
    reply = ItemSimilarityPublicationReply.model_validate(reply)
    _validate_reply_binding(
        expected_actor=request.actor_id,
        expected_request_sha256=content_sha256(request.model_dump(mode="json")),
        expected_context_request_sha256=request.selection.context_request_sha256,
        reply_actor=reply.actor_id,
        reply_request_sha256=reply.request_sha256,
        delivered_request_sha256=(
            None if reply.publication is None else reply.publication.delivery.request_sha256
        ),
    )


def _validate_reply_binding(
    *,
    expected_actor: str,
    expected_request_sha256: str,
    expected_context_request_sha256: str,
    reply_actor: str | None,
    reply_request_sha256: str | None,
    delivered_request_sha256: str | None,
) -> None:
    """One association rule after each closed family has independently validated its values."""
    if (
        reply_actor != expected_actor
        or reply_request_sha256 != expected_request_sha256
        or (
            delivered_request_sha256 is not None
            and delivered_request_sha256 != expected_context_request_sha256
        )
    ):
        raise ValueError("ITEM_SIMILARITY_PUBLICATION_REPLY_BINDING_INVALID")


class _PublicPublicationValue(_PublicationValue):
    schema_name = "system-rag-item-similarity-publication-v2"


class ItemSimilarityPublicationV2(_PublicPublicationValue):
    owner_job_id: str = Field(pattern=r"^job_[0-9a-f]{32}$")
    delivery: PublicSolutionSimilarityDelivery
    manifest_sha256: Sha256


class ItemSimilarityPublicationRequestV2(_PublicPublicationValue):
    maximum_bytes = MAX_ITEM_SIMILARITY_PUBLICATION_REQUEST_BYTES - 1
    schema_version: Literal["system-rag-item-similarity-publication-request/2.0"]
    operation: Literal["PUBLISH_ITEM_SIMILARITY_CONTEXT"]
    actor_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    selection: CompletedSimilarityQuerySelection


class ItemSimilarityPublicationReplyV2(_PublicPublicationValue):
    schema_version: Literal["system-rag-item-similarity-publication-reply/2.0"]
    operation: Literal["PUBLISH_ITEM_SIMILARITY_CONTEXT"]
    status: Literal["SUCCESS", "FAILED"]
    actor_id: str | None = Field(pattern=r"^operator_[0-9a-f]{32}$")
    request_sha256: Sha256 | None
    publication: ItemSimilarityPublicationV2 | None
    error_code: ItemSimilarityPublicationErrorCode | None


type SupportedItemSimilarityPublicationRequest = (
    ItemSimilarityPublicationRequest | ItemSimilarityPublicationRequestV2
)
type SupportedItemSimilarityPublicationReply = (
    ItemSimilarityPublicationReply | ItemSimilarityPublicationReplyV2
)


def parse_supported_item_similarity_publication_request(
    value: object,
) -> SupportedItemSimilarityPublicationRequest:
    document = raw_similarity_contract_value(value)
    if isinstance(document, dict):
        if document.get("schema_version") == "system-rag-item-similarity-publication-request/1.0":
            return ItemSimilarityPublicationRequest.model_validate(document)
        if document.get("schema_version") == "system-rag-item-similarity-publication-request/2.0":
            return ItemSimilarityPublicationRequestV2.model_validate(document)
    raise ValueError("ITEM_SIMILARITY_PUBLICATION_REQUEST_INVALID")


def validate_public_item_similarity_publication_reply(
    request: ItemSimilarityPublicationRequestV2, reply: ItemSimilarityPublicationReplyV2
) -> None:
    request = ItemSimilarityPublicationRequestV2.model_validate(request)
    reply = ItemSimilarityPublicationReplyV2.model_validate(reply)
    _validate_reply_binding(
        expected_actor=request.actor_id,
        expected_request_sha256=content_sha256(request.model_dump(mode="json")),
        expected_context_request_sha256=request.selection.context_request_sha256,
        reply_actor=reply.actor_id,
        reply_request_sha256=reply.request_sha256,
        delivered_request_sha256=(
            None if reply.publication is None else reply.publication.delivery.request_sha256
        ),
    )
