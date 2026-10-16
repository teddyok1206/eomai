"""Fixed Catalog socket read; no DB, NAS, model or native execution in API."""

from __future__ import annotations

import grp
import pwd
from pathlib import Path

from eom_catalog_contracts import CATALOG_APPLICATION_SOCKET_PATH
from eom_catalog_contracts.exam_similarity_observation import ExamSimilarityObservation
from eom_catalog_contracts.exam_similarity_read import (
    MAX_EXAM_READ_FRAME_BYTES,
    ExamObservationReadErrorCode,
    ExamObservationReadReply,
    ExamObservationReadRequest,
    ExamObservationReadSelection,
    validate_exam_observation_read_reply,
)
from eom_orchestrator.general_chat_socket import (
    ChatSocketEndpoint,
    ChatTransportError,
    exchange_chat_frame,
)
from jsonschema.exceptions import ValidationError as SchemaError


class ExamSimilarityClientError(ValueError):
    def __init__(self, code: ExamObservationReadErrorCode) -> None:
        self.code = code
        super().__init__(code)


class CatalogExamSimilarityClient:
    def __init__(self, endpoint: ChatSocketEndpoint | None = None) -> None:
        self.endpoint = endpoint

    def read(
        self, actor_id: str, selection: ExamObservationReadSelection
    ) -> ExamSimilarityObservation:
        try:
            request = ExamObservationReadRequest(
                schema_version="system-rag-exam-observation-read-request/1.0",
                operation="READ_EXAM_SIMILARITY_OBSERVATION",
                actor_id=actor_id,
                selection=selection,
            )
        except (ValueError, SchemaError):
            raise ExamSimilarityClientError("EXAM_OBSERVATION_REQUEST_INVALID") from None
        try:
            endpoint = self.endpoint or ChatSocketEndpoint(
                Path(CATALOG_APPLICATION_SOCKET_PATH),
                pwd.getpwnam("eom-catalog-manager").pw_uid,
                grp.getgrnam("eom-api").gr_gid,
            )
            reply = ExamObservationReadReply.model_validate(
                exchange_chat_frame(
                    endpoint,
                    request.model_dump(mode="json"),
                    request_limit=MAX_EXAM_READ_FRAME_BYTES,
                    reply_limit=MAX_EXAM_READ_FRAME_BYTES,
                    timeout=30.0,
                )
            )
            validate_exam_observation_read_reply(request, reply)
        except (ValueError, SchemaError, ChatTransportError, KeyError, OSError):
            raise ExamSimilarityClientError("EXAM_OBSERVATION_UNAVAILABLE") from None
        if reply.result is None:
            raise ExamSimilarityClientError(reply.error_code or "EXAM_OBSERVATION_UNAVAILABLE")
        return reply.result
