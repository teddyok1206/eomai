"""Exact Assembly sidecar selection and read transport, not execution authority."""

from __future__ import annotations

from typing import Literal

from eom_identifiers import canonical_json_bytes, content_sha256
from pydantic import ConfigDict, Field, model_validator

from eom_catalog_contracts.embedding_reference_query import similarity_contract_document
from eom_catalog_contracts.exam_similarity_observation import (
    ExamObservationRequest,
    ExamSimilarityObservation,
)
from eom_catalog_contracts.models import FrozenModel, Sha256
from eom_catalog_contracts.similarity_context import SimilarityFailureCode

MAX_EXAM_READ_FRAME_BYTES = 2 * 1024 * 1024
MAX_EXAM_READ_SELECTOR_BYTES = 128 * 1024
type ExamObservationReadErrorCode = (
    SimilarityFailureCode
    | Literal[
        "EXAM_OBSERVATION_REQUEST_INVALID",
        "EXAM_OBSERVATION_UNAVAILABLE",
        "EXAM_OBSERVATION_BUDGET_EXCEEDED",
        "ASSEMBLY_REVISION_NOT_FOUND",
        "ASSEMBLY_OBSERVATION_PIN_MISMATCH",
    ]
)


class _ReadValue(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always")

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        return similarity_contract_document(
            value, "system-rag-exam-observation-read", MAX_EXAM_READ_FRAME_BYTES - 1
        )


class ExamObservationReadSelection(_ReadValue):
    assembly_revision_id: str = Field(pattern=r"^assemblyrev_[0-9a-f]{32}$")
    assembly_manifest_sha256: Sha256
    observation_request: ExamObservationRequest

    @model_validator(mode="after")
    def bounded_selector(self) -> ExamObservationReadSelection:
        if len(canonical_json_bytes(self)) > MAX_EXAM_READ_SELECTOR_BYTES:
            raise ValueError("exam observation selector exceeds its byte budget")
        return self


class ExamObservationReadRequest(_ReadValue):
    schema_version: Literal["system-rag-exam-observation-read-request/1.0"]
    operation: Literal["READ_EXAM_SIMILARITY_OBSERVATION"]
    actor_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    selection: ExamObservationReadSelection


class ExamObservationReadReply(_ReadValue):
    schema_version: Literal["system-rag-exam-observation-read-reply/1.0"]
    operation: Literal["READ_EXAM_SIMILARITY_OBSERVATION"]
    status: Literal["SUCCESS", "FAILED"]
    actor_id: str | None = Field(pattern=r"^operator_[0-9a-f]{32}$")
    request_sha256: Sha256 | None
    result: ExamSimilarityObservation | None
    error_code: ExamObservationReadErrorCode | None


def validate_exam_observation_read_reply(
    request: ExamObservationReadRequest, reply: ExamObservationReadReply
) -> None:
    request = ExamObservationReadRequest.model_validate(request)
    reply = ExamObservationReadReply.model_validate(reply)
    if (
        reply.actor_id != request.actor_id
        or reply.request_sha256 != content_sha256(request.model_dump(mode="json"))
        or (
            reply.result is not None
            and reply.result.request != request.selection.observation_request
        )
    ):
        raise ValueError("exam observation reply differs from exact actor/request/Assembly pins")
