from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import httpx
import pytest
from eom_web_gui.contracts import (
    CodexAccountStatusView,
    ExecutionPresetDraftSubmission,
    ExecutionPresetValidationView,
)
from eom_web_gui.gateways import GatewayError, HttpApplicationGateway
from pydantic import ValidationError

from tests.web_gui.helpers import FakeGateway, login, make_client
from tests.web_gui.test_execution_preset_editor import _grounded_preset
from tests.web_gui.test_gateway import NOW, _session, _single

PRESET = "execpreset_" + "4" * 32
BASE = "execpresetrev_" + "5" * 32
DRAFT = "execpresetrev_" + "6" * 32
JOB = "job_" + "7" * 32


def _submission() -> dict[str, Any]:
    revision = _grounded_preset()["revisions"][0]
    return {
        "schema_version": "execution-preset-draft-request/1.0",
        "target_revision_schema_version": revision["schema_version"],
        "preset_key": "knowledge-grounded-item",
        **{
            key: revision[key]
            for key in (
                "display_name",
                "description",
                "role_policies",
                "capacity_policy_revision_id",
                "general_knowledge_policy",
                "compatible_workflow_protocols",
                "retrieval_policy",
            )
        },
        "idempotency_key": "studio:preset:draft:test-v2",
    }


def _validation() -> dict[str, Any]:
    return {
        "validation_id": JOB,
        "preset_revision_id": DRAFT,
        "base_revision_id": BASE,
        "preset_policy_sha256": "sha256:" + "8" * 64,
        "status": "SUCCEEDED",
        "scope": "NON_LIVE",
        "error_code": None,
        "evaluation_id": "preseteval_" + "9" * 32,
        "quality_evaluated": False,
        "cases_total": 12,
        "cases_passed": 12,
        "completed_at": NOW.isoformat(),
    }


def test_grounded_preset_bff_preserves_the_exact_v2_contract() -> None:
    client, gateway = make_client()
    body = _submission()
    with client:
        session = login(client)
        result = client.post(
            "/studio/api/v1/admin/execution-presets",
            headers={"X-CSRF-Token": session["csrf_token"]},
            json=body,
        )
    assert result.status_code == 201
    assert gateway.last_preset_payload == {
        key: value for key, value in body.items() if key != "idempotency_key"
    }


def test_native_catalog_is_backward_compatible_metadata_not_model_admission() -> None:
    minimal = {
        "binding_id": "authbinding_" + "1" * 32,
        "slot_key": "slot01",
        "account_label": "test-slot",
        "state": "ACTIVE",
        "codex_cli_version": "0.1.0",
        "observed_at": NOW.isoformat(),
        "valid_until": "2026-08-21T10:00:00Z",
        "resource_version": 1,
        "capabilities": [{"model": "model-a", "reasoning_effort": "high", "state": "READY"}],
        "active_lease_count": 0,
    }
    assert CodexAccountStatusView.model_validate(minimal).model_catalog is None
    observed = {
        "source": "APP_SERVER_MODEL_LIST",
        "codex_cli_version": "0.1.0",
        "state": "OBSERVED",
        "reason_code": None,
        "models": [
            {
                "id": "catalog-only-model",
                "model": "catalog-only-model",
                "display_name": "발견된 모델",
                "hidden": False,
                "is_default": False,
                "default_reasoning_effort": "max",
                "supported_reasoning_efforts": ["max", "ultra"],
                "input_modalities": ["text"],
            }
        ],
        "observed_at": NOW.isoformat(),
        "valid_until": "2026-08-21T10:00:00Z",
        "catalog_sha256": "sha256:" + "2" * 64,
    }
    snapshot = {
        "capability_snapshot_id": "capsnap_" + "3" * 32,
        "source": "OPERATOR_ASSERTED",
        "codex_cli_version": "0.1.0",
        "observed_at": NOW.isoformat(),
        "valid_until": "2026-08-21T10:00:00Z",
        "snapshot_sha256": "sha256:" + "4" * 64,
    }
    projection = CodexAccountStatusView.model_validate(
        {**minimal, "model_catalog": observed, "capability_snapshot": snapshot}
    )
    assert projection.model_catalog is not None
    assert projection.model_catalog.models[0].supported_reasoning_efforts == ("max", "ultra")
    assert projection.capabilities[0].model == "model-a"


@pytest.mark.parametrize(
    "invalid", ["missing_policy", "missing_evidence", "v1_policy", "max", "ultra"]
)
def test_grounded_web_contract_rejects_revision_and_effort_mismatch(invalid: str) -> None:
    body = _submission()
    if invalid == "missing_policy":
        body["retrieval_policy"] = None
    elif invalid == "missing_evidence":
        body["role_policies"][0]["evidence_access"] = None
    elif invalid == "v1_policy":
        body["target_revision_schema_version"] = "execution-preset-revision/1.0"
    else:
        body["role_policies"][0]["model_candidates"][0]["reasoning_effort"] = invalid
    with pytest.raises(ValidationError):
        ExecutionPresetDraftSubmission.model_validate(body)


def test_model_options_validation_and_release_bff_require_admin_and_csrf() -> None:
    for roles in (["ADMIN"], ["EDITOR"]):
        client, gateway = make_client(gateway=FakeGateway(roles=roles))
        with client:
            session = login(client)
            is_admin = roles == ["ADMIN"]
            options = client.get(f"/studio/api/v1/admin/execution-presets/{PRESET}/model-options")
            assert options.status_code == (200 if is_admin else 403)
            if is_admin:
                assert options.json()["catalog_is_entitlement"] is False
            path = f"/studio/api/v1/admin/execution-preset-revisions/{DRAFT}/evaluations"
            payload = {
                "base_revision_id": BASE,
                "resource_version": 6,
                "idempotency_key": "studio:preset:evaluate:focused-case",
            }
            assert client.post(path, json=payload).status_code == 403
            response = client.post(
                path, headers={"X-CSRF-Token": session["csrf_token"]}, json=payload
            )
            assert response.status_code == (200 if is_admin else 403)
            observed = client.get(f"/studio/api/v1/admin/execution-preset-validations/{JOB}")
            assert observed.status_code == (200 if is_admin else 403)
            if is_admin:
                assert observed.json()["quality_evaluated"] is False
            forged = {**payload, "outcome": "PASS", "quality_evaluated": True}
            assert (
                client.post(
                    path, headers={"X-CSRF-Token": session["csrf_token"]}, json=forged
                ).status_code
                == 422
            )
            assert gateway.preset_mutation_calls == int(is_admin)


@pytest.mark.parametrize(
    "change",
    [
        {"cases_passed": 11},
        {"evaluation_id": None},
        {"quality_evaluated": True},
        {"scope": "LIVE_ONE_SHOT"},
        {"completed_at": None},
        {"cases_total": 10001, "cases_passed": 10001},
        {"status": "RUNNING", "evaluation_id": None, "completed_at": None},
        {"status": "QUEUED", "evaluation_id": None, "completed_at": None},
        {"error_code": "ERROR"},
        {"status": "FAILED", "evaluation_id": None, "error_code": None},
    ],
)
def test_validation_projection_never_invents_passing_or_quality_evidence(
    change: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        ExecutionPresetValidationView.model_validate({**_validation(), **change})


@pytest.mark.parametrize("code", ["E", "E" + "_" * 95])
def test_validation_error_code_bounds_match_the_application_api(code: str) -> None:
    failed = _validation() | {
        "status": "FAILED",
        "evaluation_id": None,
        "error_code": code,
    }
    assert ExecutionPresetValidationView.model_validate(failed).error_code == code


@pytest.mark.anyio
async def test_preset_gateway_maps_pinned_validation_and_idempotency_headers() -> None:
    calls: list[httpx.Request] = []
    options = {
        "preset_revision_id": BASE,
        "roles": [{"role": "authoring", "worker_pool_key": "item-workers", "candidates": []}],
        "catalog_is_entitlement": False,
    }

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path.endswith("/model-options"):
            data = options
        elif request.url.path.endswith("/evaluations"):
            data = {"resource_id": JOB, "status": "ACCEPTED"}
        elif request.url.path.endswith("/releases"):
            data = {"resource_id": "execpresetrev_" + "a" * 32, "status": "COMPLETED"}
        else:
            data = _validation()
        return httpx.Response(200, json=_single(data))

    gateway = HttpApplicationGateway(
        application_api_url="http://127.0.0.1:8765",
        observability_url="http://127.0.0.1:8780",
        observability_access_token=None,
        timeout=1,
        transport=httpx.MockTransport(respond),
    )
    try:
        assert (
            await gateway.execution_preset_model_options(_session(), PRESET)
        ).preset_revision_id == BASE
        await gateway.evaluate_execution_preset(
            _session(),
            DRAFT,
            base_revision_id=BASE,
            resource_version=6,
            idempotency_key="studio:preset:evaluate:transport-test",
        )
        assert (await gateway.execution_preset_validation(_session(), JOB)).validation_id == JOB
        await gateway.release_execution_preset(
            _session(),
            DRAFT,
            resource_version=6,
            idempotency_key="studio:preset:release:transport-test",
        )
    finally:
        await gateway.close()

    assert json.loads(calls[1].content) == {"base_revision_id": BASE}
    assert calls[1].headers["if-match"] == '"v6"'
    assert calls[1].headers["idempotency-key"] == "studio:preset:evaluate:transport-test"
    assert calls[3].headers["if-match"] == '"v6"'
    assert calls[3].headers["idempotency-key"] == "studio:preset:release:transport-test"
    assert all(request.headers["authorization"].startswith("Bearer ") for request in calls)


@pytest.mark.anyio
async def test_preset_gateway_rejects_bad_model_and_validation_projections() -> None:
    invalid = deepcopy(_validation())
    invalid["quality_evaluated"] = True
    gateway = HttpApplicationGateway(
        application_api_url="http://127.0.0.1:8765",
        observability_url="http://127.0.0.1:8780",
        observability_access_token=None,
        timeout=1,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=_single(invalid))),
    )
    try:
        with pytest.raises(GatewayError, match="APPLICATION_API_RESPONSE_INVALID"):
            await gateway.execution_preset_validation(_session(), JOB)
        with pytest.raises(GatewayError, match="APPLICATION_API_RESPONSE_INVALID"):
            await gateway.execution_preset_model_options(_session(), PRESET)
    finally:
        await gateway.close()
