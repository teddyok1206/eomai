"""An uncertain PUT may observe existing work, never replay a consumed upload."""

from datetime import timedelta

import httpx
import pytest
from eom_web_gui.gateways import GatewayError, HttpApplicationGateway

from tests.web_gui.helpers import NOW, PDF_REVIEW_INTENT_ID, FakeGateway
from tests.web_gui.test_document_review_upload_continuation import SET_ID
from tests.web_gui.test_gateway import _session, _single


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def content():
    yield b"%PDF-test!!!"


def gateway_for(handler):
    return HttpApplicationGateway(
        application_api_url="http://127.0.0.1:8765",
        observability_url="http://127.0.0.1:8780",
        timeout=1,
        observability_access_token=None,
        transport=httpx.MockTransport(handler),
    )


def single_data(state="PROCESSING", *, mismatched=False):
    value = FakeGateway._pdf_upload_intent(started=state == "STARTED").model_dump(mode="json")
    value["state"] = state
    if state != "AWAITING_UPLOAD":
        value["upload_sha256"] = "sha256:" + "4" * 64
    if state.startswith("FAILED"):
        value["failure_code"] = "DOCUMENT_REVIEW_PROJECTION_FAILED"
    if mismatched:
        value["upload_intent_id"] = "pdfreviewintent_" + "9" * 32
        value["upload_url"] = (
            "/api/v1/pdf-document-reviews/upload-intents/" + value["upload_intent_id"] + "/content"
        )
    return value


def paired_data(*, question="PROCESSING", solution="AWAITING_UPLOAD", started=False):
    def member(role, state):
        committed = state == "COMMITTED"
        return dict(
            role=role,
            state=state,
            original_filename=f"{role.lower()}.pdf",
            source_format="PDF",
            media_type="application/pdf",
            content_length=12,
            upload_sha256="sha256:" + "4" * 64 if state != "AWAITING_UPLOAD" else None,
            document_id="document_" + "a" * 32 if committed else None,
            document_revision_id="documentrev_" + "b" * 32 if committed else None,
            source_pdf_sha256="sha256:" + "c" * 64 if committed else None,
            page_count=1 if committed else None,
            failure_code=None,
            upload_url=f"/api/v1/pdf-document-reviews/sets/{SET_ID}/documents/{role}/content",
        )

    workflow = "workflow_" + "d" * 32 if started else None
    return dict(
        review_set_id=SET_ID,
        state="STARTED" if started else "AWAITING_UPLOADS",
        documents=[member("QUESTION", question), member("SOLUTION", solution)],
        preset_key="MOCK_EXAM",
        additional_guidance_sha256=None,
        workflow_id=workflow,
        failure_code=None,
        review_url=f"/api/v1/pdf-document-reviews/{workflow}" if workflow else None,
        created_at=NOW.isoformat(),
        updated_at=NOW.isoformat(),
        expires_at=(NOW + timedelta(hours=1)).isoformat(),
        resource_version=2,
    )


@pytest.mark.anyio
@pytest.mark.parametrize("state", ["PROCESSING", "STARTED"])
async def test_single_upload_timeout_returns_only_its_existing_progress(state):
    calls = []

    async def handler(request):
        calls.append((request.method, request.url.path))
        if request.method == "PUT":
            assert await request.aread() == b"%PDF-test!!!"
            raise httpx.ReadTimeout("synthetic lost response", request=request)
        assert request.method == "GET"
        return httpx.Response(200, json=_single(single_data(state)))

    gateway = gateway_for(handler)
    try:
        view = await gateway.upload_pdf_document_review_content(
            _session(),
            PDF_REVIEW_INTENT_ID,
            content_length=12,
            media_type="application/pdf",
            content=content(),
            idempotency_key="studio:review:original-content-key",
        )
    finally:
        await gateway.close()
    assert view.upload_intent_id == PDF_REVIEW_INTENT_ID
    assert view.state == state
    assert calls == [
        ("PUT", f"/api/v1/pdf-document-reviews/upload-intents/{PDF_REVIEW_INTENT_ID}/content"),
        ("GET", f"/api/v1/pdf-document-reviews/upload-intents-v2/{PDF_REVIEW_INTENT_ID}"),
    ]


@pytest.mark.anyio
@pytest.mark.parametrize("case", ["read_unavailable", "awaiting", "failed", "wrong_identity"])
async def test_single_timeout_keeps_original_failure_without_proven_progress(case):
    calls = []

    async def handler(request):
        calls.append(request.method)
        if request.method == "PUT" or case == "read_unavailable":
            raise httpx.ReadTimeout("synthetic unavailable", request=request)
        state = {"awaiting": "AWAITING_UPLOAD", "failed": "FAILED_RETRYABLE"}.get(
            case, "PROCESSING"
        )
        return httpx.Response(
            200, json=_single(single_data(state, mismatched=case == "wrong_identity"))
        )

    gateway = gateway_for(handler)
    try:
        with pytest.raises(GatewayError) as failure:
            await gateway.upload_pdf_document_review_content(
                _session(),
                PDF_REVIEW_INTENT_ID,
                content_length=12,
                media_type="application/pdf",
                content=content(),
                idempotency_key="studio:review:original-content-key",
            )
    finally:
        await gateway.close()
    assert failure.value.status == 503
    assert failure.value.code == "APPLICATION_API_UNAVAILABLE"
    assert calls == ["PUT", "GET"]


@pytest.mark.anyio
@pytest.mark.parametrize("paired", [False, True])
async def test_validation_error_is_not_converted_to_pending_or_retried(paired):
    calls = []

    async def handler(request):
        calls.append(request.method)
        return httpx.Response(422, json={"error_code": "DOCUMENT_REVIEW_SOURCE_INVALID"})

    gateway = gateway_for(handler)
    try:
        with pytest.raises(GatewayError) as failure:
            if paired:
                await gateway.upload_paired_document_review_member(
                    _session(),
                    SET_ID,
                    "QUESTION",
                    content_length=12,
                    media_type="application/pdf",
                    content=content(),
                    idempotency_key="studio:review:original-question-key",
                )
            else:
                await gateway.upload_pdf_document_review_content(
                    _session(),
                    PDF_REVIEW_INTENT_ID,
                    content_length=12,
                    media_type="application/pdf",
                    content=content(),
                    idempotency_key="studio:review:original-content-key",
                )
    finally:
        await gateway.close()
    assert failure.value.status == 422
    assert calls == ["PUT"]


@pytest.mark.anyio
@pytest.mark.parametrize("paired", [False, True])
async def test_recovery_read_permission_denial_is_not_hidden_as_transport_failure(paired):
    calls = []

    async def handler(request):
        calls.append(request.method)
        if request.method == "PUT":
            raise httpx.ReadTimeout("synthetic lost response", request=request)
        return httpx.Response(403, json={"error_code": "PERMISSION_DENIED"})

    gateway = gateway_for(handler)
    try:
        with pytest.raises(GatewayError) as failure:
            if paired:
                await gateway.upload_paired_document_review_member(
                    _session(),
                    SET_ID,
                    "QUESTION",
                    content_length=12,
                    media_type="application/pdf",
                    content=content(),
                    idempotency_key="studio:review:original-question-key",
                )
            else:
                await gateway.upload_pdf_document_review_content(
                    _session(),
                    PDF_REVIEW_INTENT_ID,
                    content_length=12,
                    media_type="application/pdf",
                    content=content(),
                    idempotency_key="studio:review:original-content-key",
                )
    finally:
        await gateway.close()
    assert failure.value.status == 403
    assert failure.value.code == "PERMISSION_DENIED"
    assert calls == ["PUT", "GET"]


@pytest.mark.anyio
@pytest.mark.parametrize("phase", ["PROCESSING", "COMMITTED", "STARTED"])
async def test_paired_timeout_reads_only_the_exact_uploaded_member(phase):
    calls = []
    value = paired_data(
        question="COMMITTED" if phase == "STARTED" else phase,
        solution="COMMITTED" if phase == "STARTED" else "AWAITING_UPLOAD",
        started=phase == "STARTED",
    )

    async def handler(request):
        calls.append((request.method, request.url.path))
        if request.method == "PUT":
            raise httpx.ReadTimeout("synthetic lost response", request=request)
        return httpx.Response(200, json=_single(value))

    gateway = gateway_for(handler)
    try:
        view = await gateway.upload_paired_document_review_member(
            _session(),
            SET_ID,
            "QUESTION",
            content_length=12,
            media_type="application/pdf",
            content=content(),
            idempotency_key="studio:review:original-question-key",
        )
    finally:
        await gateway.close()
    assert view.review_set_id == SET_ID
    assert view.documents[0].state in {"PROCESSING", "COMMITTED"}
    assert calls == [
        ("PUT", f"/api/v1/pdf-document-reviews/sets/{SET_ID}/documents/QUESTION/content"),
        ("GET", f"/api/v1/pdf-document-reviews/sets/{SET_ID}"),
    ]


@pytest.mark.anyio
async def test_other_member_progress_does_not_claim_uploaded_member_was_accepted():
    calls = []

    async def handler(request):
        calls.append(request.method)
        if request.method == "PUT":
            raise httpx.ReadTimeout("synthetic lost response", request=request)
        return httpx.Response(
            200,
            json=_single(paired_data(question="AWAITING_UPLOAD", solution="PROCESSING")),
        )

    gateway = gateway_for(handler)
    try:
        with pytest.raises(GatewayError) as failure:
            await gateway.upload_paired_document_review_member(
                _session(),
                SET_ID,
                "QUESTION",
                content_length=12,
                media_type="application/pdf",
                content=content(),
                idempotency_key="studio:review:original-question-key",
            )
    finally:
        await gateway.close()
    assert failure.value.code == "APPLICATION_API_UNAVAILABLE"
    assert calls == ["PUT", "GET"]


@pytest.mark.anyio
@pytest.mark.parametrize("case", ["read_unavailable", "wrong_identity", "not_accepted"])
async def test_paired_timeout_does_not_recover_unverified_set(case):
    calls = []
    value = paired_data(question="AWAITING_UPLOAD" if case == "not_accepted" else "PROCESSING")
    if case == "wrong_identity":
        other_id = "docreviewset_" + "9" * 32
        value["review_set_id"] = other_id
        for member in value["documents"]:
            member["upload_url"] = member["upload_url"].replace(SET_ID, other_id)

    async def handler(request):
        calls.append(request.method)
        if request.method == "PUT" or case == "read_unavailable":
            raise httpx.ReadTimeout("synthetic unavailable", request=request)
        return httpx.Response(200, json=_single(value))

    gateway = gateway_for(handler)
    try:
        with pytest.raises(GatewayError) as failure:
            await gateway.upload_paired_document_review_member(
                _session(),
                SET_ID,
                "QUESTION",
                content_length=12,
                media_type="application/pdf",
                content=content(),
                idempotency_key="studio:review:original-question-key",
            )
    finally:
        await gateway.close()
    assert failure.value.code == "APPLICATION_API_UNAVAILABLE"
    assert calls == ["PUT", "GET"]
