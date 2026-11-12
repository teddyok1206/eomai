from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import httpx
import pytest
from eom_api_contracts.feature_model_settings import FeatureModelSettingsView
from eom_web_gui.contracts import FeatureModelSettingsView as WebFeature
from eom_web_gui.gateways import GatewayError, HttpApplicationGateway
from eom_workflow.feature_model_settings import (
    FEATURE_PRESET_KEYS,
    MODEL_SETTINGS_FEATURES,
    OBSOLETE_PRESET_KEYS,
)
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from tests.web_gui.helpers import FakeGateway, login, make_client
from tests.web_gui.test_execution_preset_admin import _wire_preset
from tests.web_gui.test_gateway import _list, _session


def feature_fixtures() -> tuple[dict[str, Any], ...]:
    result = []
    index = 0
    for feature in MODEL_SETTINGS_FEATURES:
        stages = []
        for stage in feature.stages:
            index += 1
            preset = _wire_preset()
            identity = f"{index:032x}"
            preset["preset_id"] = "execpreset_" + identity
            preset["preset_key"] = stage.preset_key
            preset["current_revision_id"] = "execpresetrev_" + identity
            revision = preset["revisions"][0]
            revision.update(
                preset_id=preset["preset_id"],
                preset_revision_id=preset["current_revision_id"],
                evaluations=[],
            )
            stages.append({"stage_key": stage.key, "label": stage.label, "preset": preset})
        result.append(
            {
                "feature_key": feature.key,
                "label": feature.label,
                "kind": "CHAT" if feature.key == "chat" else "WORKFLOW",
                "stages": stages,
            }
        )
    return tuple(result)


def test_feature_catalog_is_unique_and_excludes_old_slot_variants() -> None:
    assert [f.label for f in MODEL_SETTINGS_FEATURES] == [
        "문항 제작",
        "자료 검토",
        "자료 학습",
        "기존 문항 등록",
        "유사도 정밀 비교",
        "고객지원",
        "ChatGPT",
    ]
    keys = [s.preset_key for f in MODEL_SETTINGS_FEATURES for s in f.stages]
    assert len(keys) == len(set(keys)) == 13
    assert not FEATURE_PRESET_KEYS & OBSOLETE_PRESET_KEYS


@pytest.mark.parametrize("roles", [["ADMIN"], ["EDITOR"], ["REVIEWER"]])
def test_feature_and_exact_preset_bff_routes_require_admin(roles) -> None:
    client, _gateway = make_client(gateway=FakeGateway(roles=roles))
    with client:
        login(client)
        expected = 200 if roles == ["ADMIN"] else 403
        response = client.get("/studio/api/v1/admin/feature-model-settings")
        assert response.status_code == expected
        if expected == 200:
            assert len(response.json()) == 7
        response = client.get("/studio/api/v1/admin/execution-presets/execpreset_" + "1" * 32)
        assert response.status_code == expected


def test_feature_schema_api_and_isolated_web_agree() -> None:
    root = Path(__file__).resolve().parents[2]
    schema = root / "schemas/api/v1/feature-model-settings-view-v1.schema.json"
    assert (
        schema.read_bytes()
        == (root / "packages/api_contracts/eom_api_contracts/schemas" / schema.name).read_bytes()
    )
    validator = Draft202012Validator(json.loads(schema.read_text()))
    for raw in feature_fixtures():
        validator.validate(raw)
        assert FeatureModelSettingsView.model_validate(raw).model_dump(
            mode="json"
        ) == WebFeature.model_validate(raw).model_dump(mode="json")


@pytest.mark.parametrize(
    "error", ["history", "missing_current", "retired", "duplicate", "kind", "chat_stage", "owner"]
)
def test_feature_contract_rejects_invalid_owned_stage(error: str) -> None:
    raw = deepcopy(feature_fixtures()[0])
    preset = raw["stages"][0]["preset"]
    if error == "history":
        older = deepcopy(preset["revisions"][0])
        older["preset_revision_id"] = "execpresetrev_" + "f" * 32
        older["revision_number"] = 2
        preset["revisions"].append(older)
    elif error == "missing_current":
        preset["current_revision_id"] = "execpresetrev_" + "f" * 32
    elif error == "retired":
        preset["state"] = "RETIRED"
    elif error == "duplicate":
        raw["stages"].append(deepcopy(raw["stages"][0]))
    elif error == "kind":
        raw["kind"] = "CHAT"
    elif error == "chat_stage":
        raw["feature_key"] = "chat"
    else:
        preset["revisions"][0]["preset_id"] = "execpreset_" + "f" * 32
    for model in (FeatureModelSettingsView, WebFeature):
        with pytest.raises(ValidationError):
            model.model_validate(raw)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "error", [None, "duplicate_feature", "missing_feature", "duplicate_preset"]
)
async def test_feature_gateway_exact_seven_and_no_duplicate_targets(error: str | None) -> None:
    raw = list(feature_fixtures())
    if error == "duplicate_feature":
        raw[-1] = raw[0]
    elif error == "missing_feature":
        raw.pop()
    elif error == "duplicate_preset":
        raw[1]["stages"][0]["preset"] = deepcopy(raw[0]["stages"][0]["preset"])

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/feature-model-settings"
        return httpx.Response(200, json=_list(raw))

    gateway = HttpApplicationGateway(
        application_api_url="http://127.0.0.1:8765",
        observability_url="http://127.0.0.1:8780",
        observability_access_token=None,
        timeout=1,
        transport=httpx.MockTransport(handler),
    )
    try:
        if error:
            with pytest.raises(GatewayError, match="APPLICATION_API_RESPONSE_INVALID"):
                await gateway.feature_model_settings(_session())
        else:
            assert await gateway.feature_model_settings(_session()) == tuple(raw)
    finally:
        await gateway.close()
