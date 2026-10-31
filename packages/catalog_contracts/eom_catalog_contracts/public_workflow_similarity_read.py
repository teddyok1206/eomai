"""Closed runner read successor; no caller-supplied source or operator authority."""

from __future__ import annotations

from typing import ClassVar, Literal, Self

from eom_identifiers import content_sha256
from pydantic import ConfigDict, Field, model_validator

from eom_catalog_contracts.embedding_reference_query import similarity_contract_document
from eom_catalog_contracts.models import FrozenModel, Sha256
from eom_catalog_contracts.public_similarity_materials import (
    PublicSolutionSimilarityMaterials,
    validate_public_similarity_materials,
)
from eom_catalog_contracts.registered_public_solution_similarity import (
    SupportedPublicSolutionSimilarityContext,
)
from eom_catalog_contracts.workflow_similarity_read import (
    MAX_WORKFLOW_SIMILARITY_REPLY_BYTES,
    MAX_WORKFLOW_SIMILARITY_REQUEST_BYTES,
    WorkflowSimilarityReadErrorCode,
    WorkflowSimilarityRoleSelection,
)


class _ReadValue(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always", hide_input_in_errors=True)
    maximum_bytes: ClassVar[int] = MAX_WORKFLOW_SIMILARITY_REPLY_BYTES - 1

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        return similarity_contract_document(
            value, "system-rag-workflow-similarity-read-v2", cls.maximum_bytes
        )


class PublicWorkflowSimilarityReadRequest(_ReadValue):
    maximum_bytes = MAX_WORKFLOW_SIMILARITY_REQUEST_BYTES - 1
    schema_version: Literal["system-rag-workflow-similarity-read-request/2.0"]
    operation: Literal["READ_WORKFLOW_SIMILARITY_MATERIALS"]
    selection: WorkflowSimilarityRoleSelection


class PublicWorkflowSimilarityReadReply(_ReadValue):
    schema_version: Literal["system-rag-workflow-similarity-read-reply/2.0"]
    operation: Literal["READ_WORKFLOW_SIMILARITY_MATERIALS"]
    status: Literal["SUCCESS", "FAILED"]
    request_sha256: Sha256 | None
    operator_id: str | None = Field(pattern=r"^operator_[0-9a-f]{32}$")
    context: SupportedPublicSolutionSimilarityContext | None
    materials: PublicSolutionSimilarityMaterials | None
    error_code: WorkflowSimilarityReadErrorCode | None

    @model_validator(mode="after")
    def exact_materials(self) -> Self:
        if self.context is not None and self.materials is not None:
            validate_public_similarity_materials(self.materials, self.context)
        return self


def validate_public_workflow_similarity_reply(
    request: PublicWorkflowSimilarityReadRequest,
    reply: PublicWorkflowSimilarityReadReply,
    *,
    expected_operator_id: str,
) -> None:
    request = PublicWorkflowSimilarityReadRequest.model_validate(request)
    reply = PublicWorkflowSimilarityReadReply.model_validate(reply)
    if reply.request_sha256 != content_sha256(request.model_dump(mode="json")) or (
        reply.status == "SUCCESS"
        and (
            reply.operator_id != expected_operator_id
            or reply.context is None
            or reply.context.request.request_sha256
            != request.selection.query.context_request_sha256
        )
    ):
        raise ValueError("WORKFLOW_SIMILARITY_REPLY_BINDING_INVALID")
