"""Authenticated read-only exam observations, never production or approval commands."""

from __future__ import annotations

from typing import Protocol

from eom_catalog_contracts.exam_similarity_observation import (
    ExamSimilarityObservation,
    parse_exam_similarity_observation,
)
from eom_catalog_contracts.exam_similarity_read import ExamObservationReadSelection
from eom_identity_service.tokens import AccessAuthentication
from eom_operator_identity import PermissionKey
from jsonschema.exceptions import ValidationError as SchemaError

from eom_api.errors import ApiError
from eom_api.services.exam_similarity_client import ExamSimilarityClientError
from eom_api.services.operator_read_authorization import authorize_current_operator_read


class ExamSimilarityReadPort(Protocol):
    def read(
        self, actor_id: str, selection: ExamObservationReadSelection
    ) -> ExamSimilarityObservation: ...


_STATUS = {
    "SOURCE_ACCESS_DENIED": 403,
    "SOURCE_REVOKED": 409,
    "SOURCE_POINTER_INVALID": 409,
    "SOURCE_HASH_MISMATCH": 409,
    "INDEX_POINTER_INVALID": 409,
    "INDEX_HASH_MISMATCH": 409,
    "AUTHORITY_UNAVAILABLE": 503,
    "EXAM_OBSERVATION_REQUEST_INVALID": 422,
    "EXAM_OBSERVATION_UNAVAILABLE": 503,
    "EXAM_OBSERVATION_BUDGET_EXCEEDED": 422,
    "ASSEMBLY_REVISION_NOT_FOUND": 404,
    "ASSEMBLY_OBSERVATION_PIN_MISMATCH": 409,
}


def _error(code: str) -> ApiError:
    safe = code if code in _STATUS else "EXAM_OBSERVATION_UNAVAILABLE"
    return ApiError(
        _STATUS[safe], safe, "Exam observation unavailable", "The exact authorized read failed."
    )


class ExamSimilarityReadApplicationService:
    def __init__(self, reader: ExamSimilarityReadPort, *, enabled: bool = False) -> None:
        self.reader, self.enabled = reader, enabled

    def read(
        self, authentication: AccessAuthentication, selection: ExamObservationReadSelection
    ) -> ExamSimilarityObservation:
        try:
            selection = ExamObservationReadSelection.model_validate(selection)
        except (ValueError, SchemaError):
            raise _error("EXAM_OBSERVATION_REQUEST_INVALID") from None
        required = {
            PermissionKey.DELIVERABLE_READ,
            PermissionKey.ITEM_READ,
            PermissionKey.KNOWLEDGE_ANALYSIS_READ,
            PermissionKey.KNOWLEDGE_GRAPH_RETRIEVE,
        }
        if "PAST_EXAM" in selection.observation_request.source_classes:
            required.add(PermissionKey.CONTENT_INTAKE_READ)
        authorize_current_operator_read(authentication, required)
        if not self.enabled:
            raise _error("EXAM_OBSERVATION_UNAVAILABLE")
        try:
            result = parse_exam_similarity_observation(
                self.reader.read(authentication.operator.operator_id, selection)
            )
            if result.request != selection.observation_request:
                raise ValueError("observation differs from pinned selection")
        except ExamSimilarityClientError as error:
            raise _error(error.code) from None
        except (ValueError, SchemaError):
            raise _error("EXAM_OBSERVATION_UNAVAILABLE") from None
        return result
