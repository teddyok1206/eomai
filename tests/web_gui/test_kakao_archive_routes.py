"""Studio cookie/CSRF gates and the real HTTP gateway's binding transport."""

import json

import httpx
import pytest
from eom_catalog_contracts.kakao_archive_binding import KakaoBindingMutation, KakaoBindingPage
from eom_web_gui.gateways import GatewayError, HttpApplicationGateway
from eom_web_gui.kakao_archive_contracts import (
    BindingCreate,
    BindingMutation,
    BindingPage,
    BindingRetire,
    SourceBinding,
)

from tests.api.test_kakao_archive_routes import kakao_client as _kakao_client
from tests.unit.kakao_binding_fixtures import (
    BINDING_ID,
    KEY,
    POLICY_ID,
    create_command,
    retire_command,
    source_binding,
)
from tests.web_gui.helpers import FakeGateway, login, make_client
from tests.web_gui.test_gateway import _session, _single

ROOT = "/studio/api/v1/kakao-archive/source-bindings"
kakao_api_fixture = _kakao_client


@pytest.fixture
def anyio_backend():
    return "asyncio"


class KakaoGateway(FakeGateway):
    def __init__(self, *, roles=None):
        super().__init__(roles=roles)
        self.calls = []

    async def kakao_binding_create(self, session, value, idempotency_key):
        self.calls.append(("create", session, value, idempotency_key))
        return BindingMutation.model_validate(
            KakaoBindingMutation(binding=source_binding(), replayed=False).model_dump(mode="json")
        )

    async def kakao_binding_read(self, session, binding_id):
        self.calls.append(("read", session, binding_id))
        return SourceBinding.model_validate(source_binding().model_dump(mode="json"))

    async def kakao_binding_list(self, session, *, limit=50, cursor=None):
        self.calls.append(("list", session, limit, cursor))
        return BindingPage.model_validate(
            KakaoBindingPage(items=(source_binding(),), next_cursor=None).model_dump(mode="json")
        )

    async def kakao_binding_command(self, session, binding_id, value, idempotency_key, if_match):
        self.calls.append(("command", session, binding_id, value, idempotency_key, if_match))
        return BindingMutation.model_validate(
            KakaoBindingMutation(binding=source_binding(retired=True), replayed=False).model_dump(
                mode="json"
            )
        )


def test_bff_login_csrf_and_exact_read_write_payloads():
    gateway = KakaoGateway()
    client, _ = make_client(gateway=gateway)
    with client:
        assert client.get(ROOT).status_code == 401
        session = login(client)
        body = create_command().model_dump(mode="json")
        assert client.post(ROOT, json=body).status_code == 403
        assert not gateway.calls
        headers = {"X-CSRF-Token": session["csrf_token"], "Idempotency-Key": KEY}
        response = client.post(ROOT, json=body, headers=headers)
        assert response.status_code == 201, response.text
        assert (
            response.headers["etag"] == '"v1"' and response.headers["cache-control"] == "no-store"
        )
        assert gateway.calls[0][2].model_dump(mode="json") == body
        assert gateway.calls[0][3] == KEY
        assert gateway.calls[0][1].operator["operator_id"] == session["operator"]["operator_id"]
        read = client.get(ROOT + "/" + BINDING_ID)
        assert read.status_code == 200 and read.json()["source_binding_id"] == BINDING_ID
        assert read.json()["policy_revision"]["policy_revision_id"] == POLICY_ID
        page = client.get(ROOT, params={"limit": 1})
        assert page.status_code == 200 and len(page.json()["items"]) == 1
        mutation = client.post(
            ROOT + "/" + BINDING_ID + "/commands",
            json=retire_command().model_dump(mode="json"),
            headers={**headers, "If-Match": '"v1"'},
        )
        assert mutation.status_code == 200 and mutation.headers["etag"] == '"v2"'
        assert gateway.calls[-1][-2:] == (KEY, '"v1"')


def test_bff_nonadmin_with_valid_csrf_cannot_change_binding():
    gateway = KakaoGateway(roles=["VIEWER"])
    client, _ = make_client(gateway=gateway)
    with client:
        session = login(client)
        response = client.post(
            ROOT,
            json=create_command().model_dump(mode="json"),
            headers={"X-CSRF-Token": session["csrf_token"], "Idempotency-Key": KEY},
        )
        assert response.status_code == 403
        assert response.json()["error_code"] == "OPERATOR_ADMIN_REQUIRED"
        assert not gateway.calls


@pytest.mark.parametrize(
    "field,value",
    [
        ("roles", ["ADMIN"]),
        ("actor_id", "operator_other"),
        ("state", "ACTIVE"),
        ("channel_id", "guessed-channel"),
    ],
)
def test_bff_rejects_unknown_authority_and_unverified_channel_fields(field, value):
    gateway = KakaoGateway()
    client, _ = make_client(gateway=gateway)
    with client:
        session = login(client)
        response = client.post(
            ROOT,
            json={**create_command().model_dump(mode="json"), field: value},
            headers={"X-CSRF-Token": session["csrf_token"], "Idempotency-Key": KEY},
        )
        assert response.status_code == 422 and not gateway.calls


@pytest.mark.parametrize("numeric", [0, 1])
def test_bff_does_not_coerce_numeric_image_policy(numeric):
    gateway = KakaoGateway()
    client, _ = make_client(gateway=gateway)
    body = create_command().model_dump(mode="json")
    body["policy"]["include_images"] = numeric
    with client:
        session = login(client)
        response = client.post(
            ROOT, json=body, headers={"X-CSRF-Token": session["csrf_token"], "Idempotency-Key": KEY}
        )
        assert response.status_code == 422 and not gateway.calls


def test_bff_commands_require_strong_if_match_and_key():
    gateway = KakaoGateway()
    client, _ = make_client(gateway=gateway)
    with client:
        session = login(client)
        headers = {"X-CSRF-Token": session["csrf_token"], "Idempotency-Key": KEY}
        path = ROOT + "/" + BINDING_ID + "/commands"
        body = retire_command().model_dump(mode="json")
        assert client.post(path, json=body, headers=headers).status_code == 422
        assert (
            client.post(path, json=body, headers={**headers, "If-Match": 'W/"v1"'}).status_code
            == 422
        )
        assert not gateway.calls


def http_gateway(handler):
    return HttpApplicationGateway(
        application_api_url="http://api",
        observability_url="http://observe",
        timeout=2,
        observability_access_token=None,
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.anyio
async def test_real_http_gateway_to_api_preserves_payload_and_replay_identity(kakao_api_fixture):
    api, owner, _ = kakao_api_fixture
    requests = []

    def transport(request):
        requests.append(request)
        response = api.request(
            request.method,
            str(request.url.copy_with(scheme="http", host="localhost")),
            headers={
                **{key: value for key, value in request.headers.items() if key != "host"},
                "Host": "localhost",
            },
            content=request.content,
        )
        assert response.status_code < 400, response.text
        return httpx.Response(
            response.status_code, headers=response.headers, content=response.content
        )

    gateway = http_gateway(transport)
    try:
        create = BindingCreate.model_validate(create_command().model_dump(mode="json"))
        for _ in range(2):
            result = await gateway.kakao_binding_create(_session(), create, KEY)
            assert result.binding.source_binding_id == BINDING_ID
        assert requests[0].content == requests[1].content
        assert (
            requests[0].headers["Idempotency-Key"] == requests[1].headers["Idempotency-Key"] == KEY
        )
        assert requests[0].headers["authorization"] == "Bearer eom_at_TEST_ONLY_ACCESS"
        assert json.loads(requests[0].content) == create_command().model_dump(mode="json")
        assert owner.create_kakao_binding.call_count == 2  # Owner owns replay, not this adapter.
        assert (
            await gateway.kakao_binding_read(_session(), BINDING_ID)
        ).source_binding_id == BINDING_ID
        assert len((await gateway.kakao_binding_list(_session(), limit=1)).items) == 1
        retired = await gateway.kakao_binding_command(
            _session(),
            BINDING_ID,
            BindingRetire.model_validate(retire_command().model_dump(mode="json")),
            KEY,
            '"v1"',
        )
        assert retired.binding.state == "RETIRED"
        assert requests[-1].headers["If-Match"] == '"v1"'
    finally:
        await gateway.close()


@pytest.mark.anyio
@pytest.mark.parametrize("case", ["other-binding", "mixed-policy", "wrong-policy", "wrong-state"])
async def test_gateway_rejects_unrelated_or_mixed_identity(case):
    binding = source_binding(retired=case in {"wrong-policy", "wrong-state"}).model_dump(
        mode="json"
    )
    if case == "other-binding":
        binding["source_binding_id"] = "kakaobinding_" + "9" * 32
    elif case == "mixed-policy":
        binding["policy_revision"]["source_binding_id"] = "kakaobinding_" + "9" * 32
    elif case == "wrong-policy":
        binding["policy_revision"]["policy_revision_id"] = "kakaopolicyrev_" + "9" * 32
    else:
        binding["state"] = "DRAFT"
    data = {"binding": binding, "replayed": False} if case.startswith("wrong") else binding
    gateway = http_gateway(lambda _: httpx.Response(200, json=_single(data)))
    try:
        with pytest.raises(GatewayError, match="APPLICATION_API_RESPONSE_INVALID"):
            if case.startswith("wrong"):
                await gateway.kakao_binding_command(
                    _session(),
                    BINDING_ID,
                    BindingRetire.model_validate(retire_command().model_dump(mode="json")),
                    KEY,
                    '"v1"',
                )
            else:
                await gateway.kakao_binding_read(_session(), BINDING_ID)
    finally:
        await gateway.close()
