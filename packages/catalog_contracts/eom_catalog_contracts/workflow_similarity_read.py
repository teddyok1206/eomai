"""Exact stored role selection; Catalog alone derives and authorizes its operator."""

from __future__ import annotations

from typing import ClassVar, Literal

from eom_identifiers import content_sha256
from pydantic import ConfigDict, Field, model_validator

from eom_catalog_contracts.embedding_reference_query import similarity_contract_document
from eom_catalog_contracts.models import FrozenModel, Sha256
from eom_catalog_contracts.similarity_context import SimilarityContext, SimilarityFailureCode
from eom_catalog_contracts.similarity_materials import (
    SimilarityReferenceMaterials,
    validate_similarity_materials,
)
from eom_catalog_contracts.similarity_read import CompletedSimilarityQuerySelection

MAX_WORKFLOW_SIMILARITY_REQUEST_BYTES = 2048
MAX_WORKFLOW_SIMILARITY_REPLY_BYTES = 5 * 1024 * 1024
WORKFLOW_SIMILARITY_READ_OPERATION = "READ_WORKFLOW_SIMILARITY_MATERIALS"
type WorkflowSimilarityReadErrorCode = (
    SimilarityFailureCode
    | Literal[
        "WORKFLOW_SIMILARITY_REQUEST_INVALID",
        "WORKFLOW_SIMILARITY_BINDING_INVALID",
        "WORKFLOW_SIMILARITY_UNAVAILABLE",
        "WORKFLOW_SIMILARITY_BUDGET_EXCEEDED",
    ]
)


class _ReadValue(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always")
    maximum_bytes: ClassVar[int] = MAX_WORKFLOW_SIMILARITY_REPLY_BYTES - 1

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        return similarity_contract_document(
            value, "system-rag-workflow-similarity-read", cls.maximum_bytes
        )


class WorkflowSimilarityRoleSelection(_ReadValue):
    maximum_bytes = MAX_WORKFLOW_SIMILARITY_REQUEST_BYTES - 1
    workflow_id: str = Field(pattern=r"^workflow_[0-9a-f]{32}$")
    step_run_id: str = Field(pattern=r"^steprun_[0-9a-f]{32}$")
    plan_id: str = Field(pattern=r"^execplan_[0-9a-f]{32}$")
    plan_sha256: Sha256
    query: CompletedSimilarityQuerySelection


class WorkflowSimilarityReadRequest(_ReadValue):
    maximum_bytes = MAX_WORKFLOW_SIMILARITY_REQUEST_BYTES - 1
    schema_version: Literal["system-rag-workflow-similarity-read-request/1.0"]
    operation: Literal["READ_WORKFLOW_SIMILARITY_MATERIALS"]
    selection: WorkflowSimilarityRoleSelection


class WorkflowSimilarityReadReply(_ReadValue):
    schema_version: Literal["system-rag-workflow-similarity-read-reply/1.0"]
    operation: Literal["READ_WORKFLOW_SIMILARITY_MATERIALS"]
    status: Literal["SUCCESS", "FAILED"]
    request_sha256: Sha256 | None
    operator_id: str | None = Field(pattern=r"^operator_[0-9a-f]{32}$")
    context: SimilarityContext | None
    materials: SimilarityReferenceMaterials | None
    error_code: WorkflowSimilarityReadErrorCode | None

    @model_validator(mode="after")
    def exact_materials(self) -> WorkflowSimilarityReadReply:
        if self.context is not None and self.materials is not None:
            validate_similarity_materials(self.materials, self.context)
        return self


def validate_workflow_similarity_read_reply(
    request: WorkflowSimilarityReadRequest,
    reply: WorkflowSimilarityReadReply,
    *,
    expected_operator_id: str,
) -> None:
    request = WorkflowSimilarityReadRequest.model_validate(request)
    reply = WorkflowSimilarityReadReply.model_validate(reply)
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
