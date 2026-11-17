"""Exact optional concept context at the existing claim/materialize/commit boundary."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from eom_workflow.kakao_concept_request import (
    KakaoConceptWork,
    KakaoConceptWorkerRequest,
    validate_kakao_concept_request_bytes,
)
from eom_workflow.models import KakaoConceptRoleResultHeader

from .control_service import ControlPlaneError

if TYPE_CHECKING:
    from eom_kakao_archive_contracts.concepts import ConceptComposeRequest, ConceptPlanRequest


@dataclass(frozen=True, slots=True)
class KakaoConceptExecutionContext:
    work: KakaoConceptWork
    source_authorizer: Callable[[KakaoConceptWork], None]
    request_payload: bytes = field(repr=False)
    request: ConceptPlanRequest | ConceptComposeRequest = field(init=False, repr=False)

    def __post_init__(self) -> None:
        # The optional package and private JSON are loaded only for this exact purpose.
        object.__setattr__(
            self, "request", validate_kakao_concept_request_bytes(self.work, self.request_payload)
        )

    def authorize_work(self, work: KakaoConceptWork) -> None:
        if work != self.work:
            raise ControlPlaneError(
                "CONTROL_KAKAO_CONCEPT_CONTEXT_INVALID", "concept input changed"
            )
        try:
            self.source_authorizer(work)
        except ValueError as error:
            raise ControlPlaneError(
                "CONTROL_KAKAO_CONCEPT_SOURCE_AUTHORIZATION_FAILED",
                "concept source authorization failed",
            ) from error

    def reauthorize(self, request: KakaoConceptWorkerRequest) -> None:
        self.authorize_work(request.work_input)

    def validate_result(
        self, request: KakaoConceptWorkerRequest, result: KakaoConceptRoleResultHeader
    ) -> None:
        from eom_kakao_archive_contracts.concepts import validate_concept_result
        from eom_workflow.kakao_concept_result import KakaoConceptRoleResult

        if request.work_input != self.work or not isinstance(result, KakaoConceptRoleResult):
            raise ValueError("KAKAO_CONCEPT_RESULT_CONTEXT_MISMATCH")
        validate_concept_result(self.request, result.output.model_dump(mode="json"))

    def constrain_schema(self, schema: dict[str, Any]) -> dict[str, Any]:
        """Bind the existing namespaced generation schema; canonical validation still follows."""
        from eom_kakao_archive_contracts.concepts import ConceptComposeRequest

        if not isinstance(self.request, ConceptComposeRequest):
            return schema
        narrowed = deepcopy(schema)
        definitions = narrowed["$defs"]
        keys = [entry.evidence_key for entry in self.request.context.evidence]
        if keys:
            definitions["KakaoConcept_citation"]["properties"]["evidence_key"] = {
                "type": "string",
                "enum": keys,
            }
        else:
            definitions["KakaoConcept_compose"]["properties"]["blocks"]["maxItems"] = 0
        pages = [page.page_key for page in self.request.context.pages]
        if pages:
            definitions["KakaoConcept_capture"]["properties"]["page_key"] = {
                "type": "string",
                "enum": pages,
            }
        else:
            definitions["KakaoConcept_block"]["properties"]["captures"]["maxItems"] = 0
        return narrowed
