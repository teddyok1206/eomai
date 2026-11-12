"""Workbook BFF preserves small proposal pins and explicit, replayable imports."""

import copy
import json
import os
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest
from eom_catalog_contracts.content_workbook_import import (
    ContentWorkbookImportResult,
    ContentWorkbookPreview,
)
from eom_web_gui.content_workbook_contracts import (
    WORKBOOK_MAX_BYTES,
    WORKBOOK_MEDIA_TYPE,
    WorkbookCommit,
    WorkbookImportResult,
    WorkbookPreview,
    WorkbookQuery,
)
from eom_web_gui.gateways import GatewayError, HttpApplicationGateway
from eom_web_gui.request_limits import request_body_limit

from tests.unit.content_planning_fixtures import SHA, composition, identifier, source_target
from tests.web_gui.helpers import FakeGateway, login, make_client
from tests.web_gui.test_gateway import _session, _single


@pytest.fixture
def anyio_backend():
    return "asyncio"


def preview_data():
    return dict(
        schema_version="content-workbook-preview/1.0",
        proposal=dict(
            artifact_id=identifier("artifact"),
            artifact_revision_id=identifier("rev"),
            member_path="content-workbook-proposal.json",
            schema_ref="eom://schemas/content-planning/workbook-proposal/1.0",
            media_type="application/json",
            sha256=SHA,
        ),
        original_filename="교재.xlsx",
        workbook_sha256=SHA,
        metadata=dict(
            content_title="통합과학 합성 검증",
            content_type="TEXTBOOK",
            edition_label="2027 초판",
            academic_year=2027,
            print_status="PRINTED",
            printed_on="2026-11-01",
        ),
        total_rows=1,
        matched_rows=1,
        unresolved_rows=0,
        duplicate_uses=0,
        can_commit=True,
        offset=0,
        rows=[
            dict(
                row=dict(
                    row_number=2,
                    group_label="역학",
                    section_label="1회차",
                    display_number="1",
                    external_number="10321",
                    points_milli=2500,
                    note="원문 메모",
                ),
                resolution=dict(
                    row_number=2, status="MATCHED", title="합성 문항", target=source_target()
                ),
            )
        ],
        next_offset=None,
    )


def import_result():
    comp = composition()
    return dict(
        schema_version="content-workbook-import-result/1.0",
        disposition="IMPORTED",
        replayed=False,
        composition=comp,
        current_revision_id=comp["deliverable_revision_id"],
        print_record_id=identifier("print"),
    )


class WorkbookGateway(FakeGateway):
    def __init__(self):
        super().__init__()
        self.calls = []

    async def content_workbook_template(self, session):
        self.calls.append(("template", session.operator["operator_id"]))
        return b"PKsynthetic-xlsx"

    async def content_workbook_upload(self, session, **values):
        content = b"".join([chunk async for chunk in values.pop("content")])
        self.calls.append(("upload", session.operator["operator_id"], values, content))
        return WorkbookPreview.model_validate(preview_data())

    async def content_workbook_query(self, session, value):
        self.calls.append(("query", session.operator["operator_id"], value))
        return WorkbookPreview.model_validate(preview_data())

    async def content_workbook_commit(self, session, value, idempotency_key):
        self.calls.append(("commit", session.operator["operator_id"], value, idempotency_key))
        return WorkbookImportResult.model_validate(import_result())


def test_workbook_dtos_roundtrip_canonical_owners_without_domain_imports():
    owner = ContentWorkbookPreview.model_validate(preview_data())
    assert WorkbookPreview.model_validate(owner.model_dump(mode="json")).model_dump(
        mode="json"
    ) == owner.model_dump(mode="json")
    result = ContentWorkbookImportResult.model_validate(import_result())
    assert WorkbookImportResult.model_validate(result.model_dump(mode="json")).model_dump(
        mode="json"
    ) == result.model_dump(mode="json")
    source = Path("apps/web_gui/eom_web_gui/content_workbook_contracts.py").read_text()
    assert "eom_catalog_contracts" not in source


def test_bff_template_upload_preview_commit_require_actual_session_csrf_and_key():
    gateway = WorkbookGateway()
    client, _ = make_client(gateway=gateway)
    prefix = "/studio/api/v1/content-planning/imports"
    with client:
        assert client.get(prefix + "/template").status_code == 401
        session = login(client)
        response = client.get(prefix + "/template")
        assert response.content == b"PKsynthetic-xlsx"
        assert response.headers["content-type"] == WORKBOOK_MEDIA_TYPE
        assert "filename*=UTF-8''" in response.headers["content-disposition"]
        assert response.headers["cache-control"] == "no-store"
        key = "workbook-upload-bff-1234"
        headers = {
            "X-CSRF-Token": session["csrf_token"],
            "Idempotency-Key": key,
            "Content-Type": WORKBOOK_MEDIA_TYPE,
        }
        content = b"PKsynthetic-xlsx"
        path = prefix + "?original_filename=%EA%B5%90%EC%9E%AC.xlsx"
        assert client.put(path, content=content).status_code == 403
        assert (
            client.put(
                path, content=content, headers={**headers, "Content-Type": "text/plain"}
            ).status_code
            == 415
        )
        response = client.put(path, content=content, headers=headers)
        assert response.status_code == 201, response.text
        assert response.json() == preview_data()
        assert gateway.calls[-1][2]["idempotency_key"] == key
        assert gateway.calls[-1][3] == content
        headers = {name: value for name, value in headers.items() if name != "Content-Type"}
        pin = preview_data()["proposal"]
        assert client.post(prefix + "/query", json={"proposal": pin}).status_code == 403
        response = client.post(
            prefix + "/query", json={"proposal": pin, "offset": 0, "limit": 100}, headers=headers
        )
        assert response.status_code == 200, response.text
        response = client.post(prefix + "/commit", json={"proposal": pin}, headers=headers)
        assert response.status_code == 200, response.text
        assert response.json() == import_result()
        assert gateway.calls[-1][-1] == key
        assert all(call[1] == gateway.calls[0][1] for call in gateway.calls)
        assert (
            client.post(
                prefix + "/commit",
                json={"proposal": pin, "actor_id": identifier("operator", 99)},
                headers=headers,
            ).status_code
            == 422
        )
        assert (
            client.post(
                prefix + "/query", json={"proposal": pin, "limit": 101}, headers=headers
            ).status_code
            == 422
        )
        assert (
            client.put(
                prefix + "?original_filename=../evil.xlsx", content=content, headers=headers
            ).status_code
            == 422
        )


def test_upload_counts_actual_chunks_and_does_not_increase_other_routes():
    assert (
        request_body_limit("PUT", "/studio/api/v1/content-planning/imports") == WORKBOOK_MAX_BYTES
    )
    assert request_body_limit("POST", "/studio/api/v1/content-planning/imports/commit") == 262144
    gateway = WorkbookGateway()
    client, _ = make_client(gateway=gateway)
    with client:
        session = login(client)
        response = client.put(
            "/studio/api/v1/content-planning/imports?original_filename=large.xlsx",
            content=b"x" * (WORKBOOK_MAX_BYTES + 1),
            headers={
                "Content-Type": WORKBOOK_MEDIA_TYPE,
                "Content-Length": "10",
                "X-CSRF-Token": session["csrf_token"],
                "Idempotency-Key": "workbook-bff-large-1234",
            },
        )
        assert response.status_code == 413, response.text
        assert not gateway.calls


@pytest.mark.anyio
async def test_gateway_raw_upload_small_pin_query_and_commit_keep_identity():
    calls = []

    async def handler(request):
        await request.aread()
        calls.append(request)
        if request.url.path.endswith("/template"):
            return httpx.Response(
                200, content=b"PKsynthetic-xlsx", headers={"Content-Type": WORKBOOK_MEDIA_TYPE}
            )
        value = import_result() if request.url.path.endswith("/commit") else preview_data()
        return httpx.Response(200, json=_single(value))

    gateway = HttpApplicationGateway(
        application_api_url="http://api",
        observability_url="http://observe",
        timeout=2,
        observability_access_token=None,
        transport=httpx.MockTransport(handler),
    )

    async def content():
        yield b"PKsynthetic-xlsx"

    try:
        assert await gateway.content_workbook_template(_session()) == b"PKsynthetic-xlsx"
        await gateway.content_workbook_upload(
            _session(),
            original_filename="교재.xlsx",
            content_length=16,
            content=content(),
            idempotency_key="workbook-gateway-upload-1",
        )
        assert calls[-1].content == b"PKsynthetic-xlsx"
        assert calls[-1].headers["Content-Type"] == WORKBOOK_MEDIA_TYPE
        assert calls[-1].url.params["original_filename"] == "교재.xlsx"
        pin = preview_data()["proposal"]
        query = WorkbookQuery(proposal=pin, limit=100)
        await gateway.content_workbook_query(_session(), query)
        assert json.loads(calls[-1].content) == query.model_dump(mode="json")
        result = await gateway.content_workbook_commit(
            _session(), WorkbookCommit(proposal=pin), "workbook-gateway-save-1"
        )
        assert result.model_dump(mode="json") == import_result()
        assert calls[-1].headers["Idempotency-Key"] == "workbook-gateway-save-1"
    finally:
        await gateway.close()


@pytest.mark.anyio
@pytest.mark.parametrize("change", ["proposal", "offset", "limit"])
async def test_gateway_rejects_different_workbook_page(change):
    data = copy.deepcopy(preview_data())
    if change == "proposal":
        data["proposal"]["artifact_revision_id"] = identifier("rev", 2)
    elif change == "offset":
        data["offset"] = 1
    else:
        data["rows"].append(copy.deepcopy(data["rows"][0]))
    gateway = HttpApplicationGateway(
        application_api_url="http://api",
        observability_url="http://observe",
        timeout=2,
        observability_access_token=None,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=_single(data))),
    )
    try:
        with pytest.raises(GatewayError, match="APPLICATION_API_RESPONSE_INVALID"):
            await gateway.content_workbook_query(
                _session(), WorkbookQuery(proposal=preview_data()["proposal"], limit=1)
            )
    finally:
        await gateway.close()


def test_workbook_import_actual_browser_owner_replay_preview_and_explicit_commit():
    node = shutil.which("node")
    if not node or not os.environ.get("EOM_WEB_PLAYWRIGHT_MODULE"):
        pytest.skip("Actual browser requires the existing opt-in Playwright environment")
    result = subprocess.run(
        [node, str(Path(__file__).with_name("content_workbook_import_browser_checks.mjs"))],
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "CONTENT_WORKBOOK_IMPORT_BROWSER=PASS" in result.stdout
    assert "live_writes=0" in result.stdout
