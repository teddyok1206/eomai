"""Native EXTERNAL read projection and editable downloads keep pinned Item identity."""

import httpx
import pytest
from eom_identifiers import sha256_bytes
from eom_web_gui.contracts import ExternalItemDbFilterSubmission
from eom_web_gui.gateways import ExternalItemDocumentDownload, GatewayError, HttpApplicationGateway
from eom_web_gui.material_learning_contracts import (
    MaterialNativeItemDbEntry,
    MaterialNativeItemMetadata,
)

from tests.unit.test_material_native_files import metadata_data
from tests.web_gui.helpers import FakeGateway, login, make_client
from tests.web_gui.test_gateway import _session

REVISION = "itemrev_" + "2" * 32
MANIFEST = "sha256:" + "3" * 64
BODY = b"PK\x03\x04synthetic-native-document"


@pytest.fixture
def anyio_backend():
    return "asyncio"


def native_entry():
    return dict(
        schema_version="material-item-db-entry/2.0",
        metadata=metadata_data(),
        material_title="한글 원본 모의고사",
        registration=dict(
            item_id="item_" + "1" * 32,
            item_revision_id=REVISION,
            item_manifest_sha256=MANIFEST,
            approval_state="APPROVED",
            difficulty_band=None,
            item_type_key="uploaded-material-item",
        ),
    )


def test_native_web_metadata_keeps_raw_unit_null_number_and_typed_binding_pointer():
    view = MaterialNativeItemDbEntry.model_validate(native_entry())
    assert view.metadata.original_unit == " 단원 원문 "
    assert view.metadata.external_number is None
    assert view.metadata.original_classification == "통합과학 - 창작"
    assert view.metadata.source_kind == "EXTERNAL"
    assert view.metadata.native_binding.member_path == "native/binding.json"


@pytest.mark.anyio
async def test_native_list_and_original_source_dispatch_preserve_v2():
    requests = []

    def respond(request):
        requests.append(request)
        if request.url.path.endswith("/source"):
            assert request.url.params["manifest_sha256"] == MANIFEST
            return httpx.Response(200, json={"data": metadata_data()})
        assert request.url.path == "/api/v1/item-db/materials"
        return httpx.Response(
            200,
            json={"data": [native_entry()], "page": {"has_more": False, "next_cursor": None}},
        )

    gateway = HttpApplicationGateway(
        application_api_url="http://api.invalid",
        observability_url="http://observe.invalid",
        timeout=5,
        observability_access_token=None,
        transport=httpx.MockTransport(respond),
    )
    try:
        page = await gateway.registered_item_db_entries(
            _session(),
            "EXTERNAL",
            "APPROVED",
            ExternalItemDbFilterSubmission(
                schema_version="external-item-db-filter/1.0",
                match_mode="ALL",
                conditions=(),
                limit=50,
                cursor=None,
            ),
        )
        assert isinstance(page.values[0], MaterialNativeItemDbEntry)
        source = await gateway.item_db_registration_source(_session(), REVISION, MANIFEST)
        assert isinstance(source, MaterialNativeItemMetadata)
        assert source.original_unit == " 단원 원문 " and source.external_number is None
        assert all(
            request.headers["Authorization"] == "Bearer eom_at_TEST_ONLY_ACCESS"
            for request in requests
        )
    finally:
        await gateway.close()


class NativeGateway(FakeGateway):
    def __init__(self):
        super().__init__()
        self.native_reads = []

    async def material_native_item_document_download(self, session, revision, manifest, role):
        self.native_reads.append((revision, manifest, role))
        return ExternalItemDocumentDownload(
            BODY,
            "application/vnd.hancom.hwpx",
            f'attachment; filename="eom-item-{role.lower()}.hwpx"',
            f'"{sha256_bytes(BODY)}"',
        )


@pytest.mark.parametrize("role", ["MAIN", "SOLUTIONS"])
def test_native_download_is_session_protected_pinned_and_not_new_render(role):
    gateway = NativeGateway()
    client, _ = make_client(gateway=gateway)
    path = f"/studio/api/v1/item-db/registrations/{REVISION}/native-document"
    params = dict(manifest_sha256=MANIFEST, source_role=role)
    with client:
        assert client.get(path, params=params).status_code == 401
        assert not gateway.native_reads
        login(client)
        response = client.get(path, params=params)
        assert response.status_code == 200, response.text
        assert response.content == BODY
        assert response.headers["ETag"] == f'"{sha256_bytes(BODY)}"'
        assert response.headers["Cache-Control"] == "no-store"
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert gateway.native_reads == [(REVISION, MANIFEST, role)]
        assert client.get(path, params={**params, "source_role": "OTHER"}).status_code == 422
        assert client.get(path, params={**params, "manifest_sha256": "latest"}).status_code == 422


@pytest.mark.anyio
@pytest.mark.parametrize("fault", [None, "sha", "length", "media", "filename"])
async def test_native_actual_download_verifies_response_and_never_falls_back(fault):
    role = "MAIN"

    def respond(request):
        assert request.url.path == f"/api/v1/item-db/registrations/{REVISION}/native-document"
        assert request.url.params == httpx.QueryParams(manifest_sha256=MANIFEST, source_role=role)
        return httpx.Response(
            200,
            content=BODY,
            headers={
                "Content-Type": "application/pdf" if fault == "media" else "application/hwp+zip",
                "Content-Length": str(len(BODY) + (fault == "length")),
                "Content-Disposition": 'attachment; filename="wrong.pdf"'
                if fault == "filename"
                else (
                    'attachment; filename="eom-item-main.hwpx"; '
                    "filename*=UTF-8''EOM-test-main.hwpx"
                ),
                "ETag": '"sha256:' + "0" * 64 + '"'
                if fault == "sha"
                else f'"{sha256_bytes(BODY)}"',
            },
        )

    gateway = HttpApplicationGateway(
        application_api_url="http://api.invalid",
        observability_url="http://observe.invalid",
        timeout=5,
        observability_access_token=None,
        transport=httpx.MockTransport(respond),
    )
    try:
        if fault:
            with pytest.raises(GatewayError) as error:
                await gateway.material_native_item_document_download(
                    _session(), REVISION, MANIFEST, role
                )
            assert error.value.code == "MATERIAL_NATIVE_DOCUMENT_RESPONSE_INVALID"
        else:
            result = await gateway.material_native_item_document_download(
                _session(), REVISION, MANIFEST, role
            )
            assert result.content == BODY
            assert result.content_type == "application/hwp+zip"
    finally:
        await gateway.close()
