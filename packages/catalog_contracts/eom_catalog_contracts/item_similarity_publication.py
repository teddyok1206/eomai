"""API-only completed QUERY publication metadata, not native launch or item acceptance."""

from __future__ import annotations

from typing import ClassVar, Literal

from eom_identifiers import content_sha256
from pydantic import ConfigDict, Field, model_validator

from eom_catalog_contracts.embedding_reference_query import similarity_contract_document
from eom_catalog_contracts.models import FrozenModel, Sha256
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

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        return similarity_contract_document(
            value, "system-rag-item-similarity-publication", cls.maximum_bytes
        )


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
    if (
        reply.actor_id != request.actor_id
        or reply.request_sha256 != content_sha256(request.model_dump(mode="json"))
        or (
            reply.publication is not None
            and reply.publication.delivery.request_sha256
            != request.selection.context_request_sha256
        )
    ):
        raise ValueError("ITEM_SIMILARITY_PUBLICATION_REPLY_BINDING_INVALID")
