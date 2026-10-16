"""Pointer-only selection from the same official Evidence, never read/launch authority."""

from typing import ClassVar, Literal

from eom_identifiers import content_sha256
from pydantic import ConfigDict, Field, model_validator

from eom_catalog_contracts.embedding_reference_query import similarity_contract_document
from eom_catalog_contracts.knowledge import EvidenceBundlePublicationResultV5
from eom_catalog_contracts.models import FrozenModel, Sha256

MAX_AUTHORING_REFERENCE_REQUEST_BYTES = 8192
MAX_AUTHORING_REFERENCE_REPLY_BYTES = 2048
AUTHORING_REFERENCE_OPERATION = "SELECT_ITEM_AUTHORING_REFERENCE"
type AuthoringReferenceErrorCode = Literal[
    "REFERENCE_NOT_OFFERED",
    "SOURCE_ACCESS_DENIED",
    "SOURCE_REVOKED",
    "SOURCE_POINTER_INVALID",
    "SOURCE_HASH_MISMATCH",
    "AUTHORITY_UNAVAILABLE",
    "AUTHORING_REFERENCE_REQUEST_INVALID",
    "AUTHORING_REFERENCE_UNAVAILABLE",
]


class _ReferenceValue(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always")
    maximum_bytes: ClassVar[int] = MAX_AUTHORING_REFERENCE_REPLY_BYTES - 1

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        return similarity_contract_document(
            value, "system-rag-authoring-reference", cls.maximum_bytes
        )


class AuthoringReferenceSelection(_ReferenceValue):
    evidence_id: str = Field(pattern=r"^evidenceitem_[0-9a-f]{32}$")
    source_item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    source_sha256: Sha256
    solution_pointer_sha256: Sha256


class AuthoringReferenceRequest(_ReferenceValue):
    maximum_bytes = MAX_AUTHORING_REFERENCE_REQUEST_BYTES - 1
    schema_version: Literal["system-rag-authoring-reference-request/1.0"]
    operation: Literal["SELECT_ITEM_AUTHORING_REFERENCE"]
    actor_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    evidence: EvidenceBundlePublicationResultV5


class AuthoringReferenceReply(_ReferenceValue):
    schema_version: Literal["system-rag-authoring-reference-reply/1.0"]
    operation: Literal["SELECT_ITEM_AUTHORING_REFERENCE"]
    status: Literal["SELECTED", "UNAVAILABLE", "FAILED"]
    actor_id: str | None = Field(pattern=r"^operator_[0-9a-f]{32}$")
    request_sha256: Sha256 | None
    selection: AuthoringReferenceSelection | None
    error_code: AuthoringReferenceErrorCode | None


def validate_authoring_reference_reply(
    request: AuthoringReferenceRequest, reply: AuthoringReferenceReply
) -> None:
    request = AuthoringReferenceRequest.model_validate(request)
    reply = AuthoringReferenceReply.model_validate(reply)
    if reply.actor_id != request.actor_id or reply.request_sha256 != content_sha256(request):
        raise ValueError("AUTHORING_REFERENCE_REPLY_BINDING_INVALID")
