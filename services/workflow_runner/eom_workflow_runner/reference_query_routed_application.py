"""Current authenticated preparation/observation; finite drive stays with the existing handle."""

from __future__ import annotations

from eom_catalog_contracts.reference_query_prepare import (
    ReferenceQueryPrepareReplyV3,
    ReferenceQueryPrepareRequestV3,
    SupportedReferenceQueryPrepareReply,
    SupportedReferenceQueryPrepareRequest,
    parse_supported_reference_query_prepare_request,
    routed_reference_query_error_reply,
    validate_supported_reference_query_prepare_reply,
)

from eom_workflow_runner.reference_query_preparation import ReferenceQueryPreparationUnavailable
from eom_workflow_runner.reference_query_prepare_driver import ReferenceQueryPrepareDriver
from eom_workflow_runner.reference_query_routed_execution import observe_routed_reference_queries
from eom_workflow_runner.reference_query_routed_runtime import RoutedReferenceQuerySession


class RoutedNativeReferenceQueryPreparation:
    def __init__(self, session: RoutedReferenceQuerySession) -> None:
        if type(session) is not RoutedReferenceQuerySession:
            raise ValueError("REFERENCE_QUERY_PREPARE_COMPOSITION_INVALID")
        driver = session.cpu.driver
        if not isinstance(driver, ReferenceQueryPrepareDriver):
            raise ValueError("REFERENCE_QUERY_PREPARE_COMPOSITION_INVALID")
        self.session = session
        self.driver = driver

    def prepare(
        self, request: SupportedReferenceQueryPrepareRequest
    ) -> SupportedReferenceQueryPrepareReply:
        request = parse_supported_reference_query_prepare_request(request)
        if not isinstance(request, ReferenceQueryPrepareRequestV3):
            original = self.session.cpu.observe_existing(request)
            if original is not None:
                validate_supported_reference_query_prepare_reply(request, original)
                return original
        requests = (
            request.requests if isinstance(request, ReferenceQueryPrepareRequestV3) else (request,)
        )
        try:
            prepared = self.session.selection.prepare(
                requests, idempotency_key=request.idempotency_key
            )
        except ReferenceQueryPreparationUnavailable as absent:
            return routed_reference_query_error_reply(
                request, status="UNAVAILABLE", error_code=absent.code
            )
        observed = observe_routed_reference_queries(self.session, prepared)
        children = [
            dict(
                ordinal=child.ordinal,
                source_item_revision_id=requests[child.ordinal].source_item_revision_id,
                workflow_id=child.workflow_id,
                state=child.state,
                selection=None
                if child.selection is None
                else child.selection.model_dump(mode="json"),
            )
            for child in observed.children
        ]
        reply = ReferenceQueryPrepareReplyV3.model_validate(
            dict(
                schema_version="system-rag-reference-query-prepare-reply/3.0",
                operation="PREPARE_REFERENCE_QUERY",
                operation_id=request.operation_id,
                request_sha256=request.request_sha256,
                request_schema_version=request.schema_version,
                status=observed.state,
                preparation=prepared.manifest.model_dump(mode="json"),
                parent_request_sha256=observed.parent_request_sha256,
                device=observed.device,
                children=children,
                workflow_id=children[0]["workflow_id"] if len(children) == 1 else None,
                selection=children[0]["selection"]
                if len(children) == 1 and observed.state == "READY"
                else None,
                error_code="REFERENCE_QUERY_EXECUTION_FAILED"
                if observed.state == "FAILED"
                else None,
            )
        )
        validate_supported_reference_query_prepare_reply(request, reply)
        if reply.status == "PENDING":
            self.driver.offer_routed_reference_batch(self.session, prepared)
        return reply
