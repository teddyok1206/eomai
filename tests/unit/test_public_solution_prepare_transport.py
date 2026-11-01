"""Public request4 crosses real HTTP/Unix/capture framing; owner data is synthetic."""

import pytest
from eom_catalog_contracts.reference_query_prepare import (
    ReferenceQueryPrepareReplyV4,
    ReferenceQueryPrepareReplyV5,
    routed_reference_query_error_reply,
)

from tests.unit.test_installed_identity_provider_observation import observation as observation
from tests.unit.test_public_solution_query_preparation_contracts import public_prepare_request
from tests.unit.test_reference_query_prepare_transport import exchange


@pytest.mark.parametrize("http", (False, True))
@pytest.mark.parametrize("count", (1, 5, 32))
def test_public_request4_retains_actual_http_capture_and_no_legacy_fallback(
    observation, monkeypatch, http, count
):
    source, reply, calls = exchange(
        observation,
        monkeypatch,
        through_http=http,
        request_value=public_prepare_request(count),
        reply_factory=lambda request: routed_reference_query_error_reply(
            request,
            status="UNAVAILABLE",
            error_code="INDEX_NOT_PREPARED",
        ),
    )
    assert isinstance(reply, ReferenceQueryPrepareReplyV4)
    assert reply.status == "UNAVAILABLE" and reply.children == ()
    assert calls == [source.operator.operator_id]
    assert source.raw_token not in repr(reply)


@pytest.mark.parametrize("fault", ("application", "wrong_reply", "capture_hash"))
def test_public_prepare_failure_cannot_reauthenticate_retry_or_downgrade(
    observation, monkeypatch, fault
):
    source, reply, calls = exchange(
        observation,
        monkeypatch,
        fault=fault,
        request_value=public_prepare_request(),
        reply_factory=lambda request: routed_reference_query_error_reply(
            request,
            status="UNAVAILABLE",
            error_code="INDEX_NOT_PREPARED",
        ),
    )
    assert calls == ([] if fault == "capture_hash" else [source.operator.operator_id])
    assert reply is None or isinstance(reply, ReferenceQueryPrepareReplyV4)


def registered_pending(request):
    return ReferenceQueryPrepareReplyV5.model_validate(
        dict(
            schema_version="system-rag-reference-query-prepare-reply/5.0",
            operation="PREPARE_REFERENCE_QUERY",
            operation_id=request.operation_id,
            request_sha256=request.request_sha256,
            request_schema_version=request.schema_version,
            status="PENDING",
            preparation=dict(
                artifact_id="artifact_" + "1" * 32,
                artifact_revision_id="rev_" + "2" * 32,
                member_path="preparation.json",
                sha256="sha256:" + "3" * 64,
                schema_ref="eom://schemas/workflow/reference-query-routed-preparation/3.0",
                media_type="application/json",
            ),
            parent_request_sha256="sha256:" + "4" * 64,
            device=None,
            children=[
                dict(
                    ordinal=i,
                    source_item_revision_id=source,
                    workflow_id=None,
                    state="PENDING",
                    selection=None,
                )
                for i, source in enumerate(request.source_item_revision_ids)
            ],
            workflow_id=None,
            selection=None,
            error_code=None,
        )
    )


@pytest.mark.parametrize("http", (False, True))
@pytest.mark.parametrize("count", (1, 5, 32))
def test_registered_reply5_crosses_existing_request4_http_and_actual_socket_capture(
    observation, monkeypatch, http, count
):
    source, reply, calls = exchange(
        observation,
        monkeypatch,
        through_http=http,
        request_value=public_prepare_request(count),
        reply_factory=registered_pending,
    )
    assert isinstance(reply, ReferenceQueryPrepareReplyV5) and reply.status == "PENDING"
    assert reply.preparation.schema_ref.endswith("/3.0")
    assert calls == [source.operator.operator_id]
