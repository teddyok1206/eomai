"""Presentation DTO alignment and exact student/revision/PDF response correlation."""

from copy import deepcopy

import httpx
import pytest
from eom_web_gui.gateways import GatewayError
from eom_web_gui.kakao_study_contracts import StudyCreate, StudyExportCreate

from tests.unit.test_kakao_study_delivery_rpc import cases
from tests.unit.test_kakao_study_export import command as export_command
from tests.unit.test_kakao_study_store import command, identity, stored
from tests.web_gui.test_gateway import _session, _single
from tests.web_gui.test_kakao_archive_routes import http_gateway


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def call(gateway, name):
    study = stored()
    if name == "save":
        return await gateway.kakao_study_save(
            _session(),
            StudyCreate.model_validate(command().model_dump(mode="json")),
            "fixture-study-key-0001",
        )
    if name == "list":
        return await gateway.kakao_study_list(_session(), study.source_binding_id)
    if name == "read":
        return await gateway.kakao_study_read(
            _session(), study.source_binding_id, study.study_id, study.study_revision_id
        )
    if name == "selection":
        return await gateway.kakao_study_selection(
            _session(),
            study.source_binding_id,
            study.packet_id,
            study.packet_revision_id,
            study.student_id,
        )
    if name == "export":
        return await gateway.kakao_study_export_create(
            _session(),
            StudyExportCreate.model_validate(export_command().model_dump(mode="json")),
            "fixture-study-export-0001",
        )
    req, _result, _name = cases()[4]
    return await gateway.kakao_study_export_read(_session(), req.source_binding_id, req.export_id)


@pytest.mark.anyio
@pytest.mark.parametrize("_req,result,name", cases())
async def test_public_and_web_projection_values_match(_req, result, name):
    requests = []

    def response(request):
        requests.append(request)
        return httpx.Response(200, json=_single(result.model_dump(mode="json")))

    gateway = http_gateway(response)
    try:
        assert (await call(gateway, name)).model_dump(mode="json") == result.model_dump(mode="json")
        assert len(requests) == 1
        if name in {"save", "export"}:
            assert requests[0].method == "POST" and requests[0].headers[
                "Idempotency-Key"
            ].startswith("fixture-study")
        else:
            assert requests[0].method == "GET"
    finally:
        await gateway.close()


@pytest.mark.anyio
@pytest.mark.parametrize("_req,result,name", cases())
async def test_unrelated_student_or_binding_is_not_displayed(_req, result, name):
    value = deepcopy(result.model_dump(mode="json"))
    if name == "list":
        value["items"][0]["source_binding_id"] = identity("kakaobinding", 987)
    elif name == "export":
        value["result"]["study"]["study_revision_id"] = identity("kakaostudyrev", 987)
    elif name == "read-export":
        value["export"]["source_binding_id"] = identity("kakaobinding", 987)
    elif name == "selection":
        value["student_id"] = identity("kakaostudent", 987)
    else:
        value["study"]["source_binding_id"] = identity("kakaobinding", 987)
    gateway = http_gateway(lambda _: httpx.Response(200, json=_single(value)))
    try:
        with pytest.raises(GatewayError, match="APPLICATION_API_RESPONSE_INVALID"):
            await call(gateway, name)
    finally:
        await gateway.close()


@pytest.mark.parametrize(
    "field,value", [("slot", "05"), ("roles", ["ADMIN"]), ("path", "/private"), ("latest", True)]
)
def test_web_input_has_no_worker_authority_or_arbitrary_source(field, value):
    with pytest.raises(ValueError):
        StudyCreate.model_validate(command().model_dump(mode="json") | {field: value})
