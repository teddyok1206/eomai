from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from eom_api.app import create_app
from eom_api.dependencies import get_authentication
from eom_api.errors import ApiError
from eom_api.services.preset_model_selection_adapter import PresetModelSelectionAdapter
from eom_api_contracts.preset_model_selection import (
    PresetModelEvaluationRequest,
    PresetModelOptionsView,
    PresetModelValidationView,
)
from eom_identity_service.tokens import AccessAuthentication
from eom_operator_identity import OperatorProjection, OperatorStatus, PermissionKey, RoleKey
from eom_orchestrator.control_service import ControlPlaneError
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from tests.api.helpers import disconnected_services
from tests.api.test_hwpx_endpoints import FakeAudit, MemoryIdempotency

NOW = datetime(2026, 10, 9, 17, 0, tzinfo=UTC)
DRAFT = "execpresetrev_" + "1" * 32
BASE = "execpresetrev_" + "2" * 32
PRESET = "execpreset_" + "6" * 32
VALIDATION = "job_" + "3" * 32
OPERATOR = "operator_" + "7" * 32
HEADERS = {"Idempotency-Key": "preset-model-validation-test-0001", "If-Match": '"v2"'}
EVALUATIONS_PATH = f"/api/v1/execution-preset-revisions/{DRAFT}/evaluations"
OPTIONS_PATH = f"/api/v1/execution-presets/{PRESET}/model-options"
STATUS_PATH = f"/api/v1/execution-preset-validations/{VALIDATION}"


def _successful_validation() -> dict[str, Any]:
    return {
        "validation_id": "job_" + "3" * 32,
        "preset_revision_id": DRAFT,
        "base_revision_id": BASE,
        "preset_policy_sha256": "sha256:" + "4" * 64,
        "status": "SUCCEEDED",
        "scope": "NON_LIVE",
        "error_code": None,
        "evaluation_id": "preseteval_" + "5" * 32,
        "quality_evaluated": False,
        "cases_total": 8,
        "cases_passed": 8,
        "completed_at": NOW,
    }


def test_model_evaluation_request_contains_only_the_pinned_baseline() -> None:
    request = PresetModelEvaluationRequest(base_revision_id=BASE)
    assert request.model_dump(mode="json") == {"base_revision_id": BASE}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("requested_by", "admin"),
        ("actor_role", "ADMIN"),
        ("approved", True),
        ("scope", "LIVE_ONE_SHOT"),
        ("quality_evaluated", True),
        ("evaluator_source_commit", "a" * 40),
        ("artifact_revision_id", "rev_" + "6" * 32),
        ("model", "model-supplied-choice"),
        ("reasoning_effort", "ultra"),
    ],
)
def test_client_cannot_supply_validation_authority_or_evidence(field: str, value: object) -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        PresetModelEvaluationRequest.model_validate({"base_revision_id": BASE, field: value})


@pytest.mark.parametrize(
    "baseline",
    [
        "latest",
        "execpreset_" + "2" * 32,
        "execpresetrev_" + "2" * 31,
        "execpresetrev_" + "g" * 32,
        "execpresetrev_" + "2" * 32 + "/replacement",
    ],
)
def test_model_evaluation_requires_exact_revision_identity(baseline: str) -> None:
    with pytest.raises(ValidationError):
        PresetModelEvaluationRequest(base_revision_id=baseline)


def test_accepted_validation_does_not_claim_live_execution_or_quality() -> None:
    view = PresetModelValidationView.model_validate(_successful_validation())
    assert view.scope == "NON_LIVE"
    assert view.quality_evaluated is False
    assert view.evaluation_id is not None
    assert view.cases_total == view.cases_passed == 8


@pytest.mark.parametrize(
    "updates",
    [
        {"scope": "STATIC"},
        {"scope": "LIVE_ONE_SHOT"},
        {"quality_evaluated": True},
        {"completed_at": None},
        {"evaluation_id": None},
        {"error_code": "INFERENCE_FAILED"},
        {"cases_total": 0, "cases_passed": 0},
        {"cases_passed": 7},
        {"cases_passed": 9},
        {"cases_total": -1},
        {"status": "QUEUED"},
        {"status": "RUNNING"},
        {"status": "FAILED"},
        {"quality_score_permille": 1000},
        {"entitlement_verified": True},
    ],
)
def test_validation_metadata_rejects_incoherent_or_overstated_acceptance(
    updates: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        PresetModelValidationView.model_validate(_successful_validation() | updates)


@pytest.mark.parametrize(
    "updates",
    [
        {"scope": "LIVE_ONE_SHOT"},
        {"quality_evaluated": True},
        {"completed_at": None},
        {"evaluation_id": None},
        {"error_code": "CONTROL_VALIDATION_EXECUTION_FAILED"},
        {"cases_total": 0, "cases_passed": 0},
        {"status": "QUEUED"},
        {"status": "RUNNING"},
        {"status": "FAILED", "evaluation_id": None},
        {"entitlement_verified": True},
    ],
)
def test_validation_wire_schema_rejects_false_acceptance_without_python_validation(
    updates: dict[str, Any],
) -> None:
    """Cross-service receivers enforce terminal meaning, not just the Python owner."""
    name = "preset-model-validation-view-v1.schema.json"
    canonical = Path("schemas/api/v1") / name
    packaged = Path("packages/api_contracts/eom_api_contracts/schemas") / name
    assert canonical.read_bytes() == packaged.read_bytes()
    schema = json.loads(canonical.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    document = PresetModelValidationView.model_validate(_successful_validation()).model_dump(
        mode="json"
    )
    assert validator.is_valid(document)
    assert not validator.is_valid(document | updates)


@pytest.mark.parametrize("status", ["QUEUED", "RUNNING"])
def test_pending_validation_has_no_accepted_evidence(status: str) -> None:
    document = _successful_validation() | {
        "status": status,
        "evaluation_id": None,
        "completed_at": None,
        "cases_total": 0,
        "cases_passed": 0,
    }
    view = PresetModelValidationView.model_validate(document)
    assert view.evaluation_id is None
    assert view.completed_at is None


def test_failed_validation_preserves_explicit_failure_without_acceptance() -> None:
    document = _successful_validation() | {
        "status": "FAILED",
        "error_code": "CONTROL_PRESET_MODEL_UNAVAILABLE",
        "evaluation_id": None,
        "cases_total": 0,
        "cases_passed": 0,
    }
    view = PresetModelValidationView.model_validate(document)
    assert view.status == "FAILED"
    assert view.error_code == "CONTROL_PRESET_MODEL_UNAVAILABLE"
    assert view.evaluation_id is None


def test_model_options_cannot_turn_discovery_into_entitlement() -> None:
    options: dict[str, Any] = {
        "preset_revision_id": BASE,
        "roles": [
            {
                "role": "authoring",
                "worker_pool_key": "authoring",
                "candidates": [{"model": "test-model", "reasoning_effort": "high"}],
            }
        ],
        "catalog_is_entitlement": False,
    }
    assert PresetModelOptionsView.model_validate(options).catalog_is_entitlement is False
    with pytest.raises(ValidationError):
        PresetModelOptionsView.model_validate(options | {"catalog_is_entitlement": True})


def test_model_options_bound_covers_the_full_reviewed_model_effort_set() -> None:
    candidates = [
        {"model": f"fixture-model-{index}", "reasoning_effort": effort}
        for index in range(64)
        for effort in ("minimal", "low", "medium", "high", "xhigh")
    ]
    options: dict[str, Any] = {
        "preset_revision_id": BASE,
        "roles": [{"role": "authoring", "worker_pool_key": "authoring", "candidates": candidates}],
        "catalog_is_entitlement": False,
    }
    assert len(PresetModelOptionsView.model_validate(options).roles[0].candidates) == 320
    options["roles"][0]["candidates"] = [
        *candidates,
        {"model": "overflow", "reasoning_effort": "low"},
    ]
    with pytest.raises(ValidationError):
        PresetModelOptionsView.model_validate(options)


@pytest.mark.parametrize("effort", ["max", "ultra"])
def test_provider_metadata_efforts_are_not_api_execution_candidates(effort: str) -> None:
    with pytest.raises(ValidationError):
        PresetModelOptionsView.model_validate(
            {
                "preset_revision_id": BASE,
                "roles": [
                    {
                        "role": "authoring",
                        "worker_pool_key": "authoring",
                        "candidates": [{"model": "fixture-model", "reasoning_effort": effort}],
                    }
                ],
            }
        )


class FakePresetModels:
    """Application-port fixture: routes do not decide baseline or release policy."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.failure_code: str | None = None
        self.validation = PresetModelValidationView.model_validate(
            _successful_validation()
            | {
                "status": "QUEUED",
                "evaluation_id": None,
                "completed_at": None,
                "cases_total": 0,
                "cases_passed": 0,
            }
        )

    def options(self, preset_id: str) -> PresetModelOptionsView:
        self.calls.append({"operation": "options", "preset_id": preset_id})
        return PresetModelOptionsView.model_validate(
            {
                "preset_revision_id": BASE,
                "roles": [
                    {
                        "role": "authoring",
                        "worker_pool_key": "authoring",
                        "candidates": [{"model": "fixture-model", "reasoning_effort": "high"}],
                    }
                ],
                "catalog_is_entitlement": False,
            }
        )

    def enqueue(self, **values: Any) -> PresetModelValidationView:
        self.calls.append({"operation": "enqueue", **values})
        if self.failure_code is not None:
            raise ApiError(409, self.failure_code, "Rejected", "Owner rejected the transition.")
        return self.validation

    def status(self, validation_id: str) -> PresetModelValidationView:
        self.calls.append({"operation": "status", "validation_id": validation_id})
        return self.validation

    def release_preset(self, **values: Any) -> None:
        self.calls.append({"operation": "release", **values})
        assert self.failure_code is not None
        raise ApiError(409, self.failure_code, "Rejected", "Owner rejected the release.")


def _route_client(
    *, admin: bool = True, fresh: bool = True, read: bool = True, manage: bool = True
) -> tuple[TestClient, Any, FakePresetModels]:
    services = disconnected_services()  # type: ignore[no-untyped-call]
    owner = FakePresetModels()
    services.preset_models = owner
    services.control_plane = owner
    services.idempotency = MemoryIdempotency()
    services.audit = FakeAudit()
    app = create_app(services)

    def authenticated(request: Request) -> AccessAuthentication:
        now = datetime.now(UTC)
        permissions = frozenset(
            permission
            for permission, allowed in (
                (PermissionKey.EXECUTION_PRESET_READ, read),
                (PermissionKey.EXECUTION_PRESET_MANAGE, manage),
            )
            if allowed
        )
        authentication = AccessAuthentication(
            operator=OperatorProjection(
                operator_id=OPERATOR,
                username="fixture-preset-admin",
                display_name="Fixture admin",
                status=OperatorStatus.ACTIVE,
                must_change_password=False,
                roles=(RoleKey.ADMIN if admin else RoleKey.AUTHOR,),
                effective_permissions=tuple(sorted(permissions, key=str)),
                resource_version=1,
                created_at=now,
                updated_at=now,
            ),
            session_id="apisession_" + "8" * 32,
            authenticated_at=now if fresh else now - timedelta(days=1),
            access_expires_at=now + timedelta(hours=1),
            permissions=permissions,
            password_change_required=False,
        )
        request.state.request_context.authentication = authentication
        return authentication

    app.dependency_overrides[get_authentication] = authenticated
    return TestClient(app, base_url="http://localhost"), services, owner


@pytest.fixture
def route_client() -> Iterator[tuple[TestClient, FakePresetModels]]:
    client, services, owner = _route_client()
    try:
        with client:
            yield client, owner
    finally:
        services.engine.dispose()


def test_model_selection_openapi_preserves_administrator_and_permission_metadata(
    route_client: tuple[TestClient, FakePresetModels],
) -> None:
    client, owner = route_client
    document = cast(FastAPI, client.app).openapi()
    expected = (
        (
            "/api/v1/execution-presets/{preset_id}/model-options",
            "get",
            "execution_preset_model_options_get",
            "execution_preset:read",
        ),
        (
            "/api/v1/execution-preset-revisions/{draft_revision_id}/evaluations",
            "post",
            "execution_preset_model_evaluation_create",
            "execution_preset:manage",
        ),
        (
            "/api/v1/execution-preset-validations/{validation_id}",
            "get",
            "execution_preset_model_validation_get",
            "execution_preset:read",
        ),
    )
    for path, method, operation_id, permission in expected:
        operation = document["paths"][path][method]
        assert operation["operationId"] == operation_id
        assert operation["x-eom-admin-only"] is True
        assert operation["x-eom-permission"] == permission
        assert operation["security"]
        assert not operation.get("x-eom-public")
    assert owner.calls == []


def test_model_evaluation_submit_is_accepted_metadata_not_a_false_pass(
    route_client: tuple[TestClient, FakePresetModels],
) -> None:
    client, owner = route_client
    response = client.post(EVALUATIONS_PATH, headers=HEADERS, json={"base_revision_id": BASE})
    assert response.status_code == 202
    command = response.json()["data"]
    assert command["status"] == "ACCEPTED"
    assert command["resource_id"] == command["command_id"] == VALIDATION
    assert command["resource_version"] == 2
    assert command["status_url"] == STATUS_PATH
    assert owner.calls[0]["draft_revision_id"] == DRAFT
    assert owner.calls[0]["body"].base_revision_id == BASE
    assert owner.calls[0]["actor"].actor_id == OPERATOR
    assert owner.calls[0]["expected_version"] == 2
    assert owner.calls[0]["idempotency_key"].startswith("api:")
    status = client.get(STATUS_PATH)
    assert status.status_code == 200
    view = status.json()["data"]
    assert view["status"] == "QUEUED"
    assert view["quality_evaluated"] is False
    assert view["evaluation_id"] is None
    assert view["cases_total"] == view["cases_passed"] == 0


def test_model_evaluation_identical_http_replay_does_not_enqueue_again(
    route_client: tuple[TestClient, FakePresetModels],
) -> None:
    client, owner = route_client
    first = client.post(EVALUATIONS_PATH, headers=HEADERS, json={"base_revision_id": BASE})
    replay = client.post(EVALUATIONS_PATH, headers=HEADERS, json={"base_revision_id": BASE})
    assert first.status_code == replay.status_code == 202
    assert first.json()["data"] == replay.json()["data"]
    assert len(owner.calls) == 1


@pytest.mark.parametrize("change", ["baseline", "draft"])
def test_model_evaluation_replay_cannot_change_pinned_input(
    route_client: tuple[TestClient, FakePresetModels], change: str
) -> None:
    client, owner = route_client
    first = client.post(EVALUATIONS_PATH, headers=HEADERS, json={"base_revision_id": BASE})
    assert first.status_code == 202
    path = (
        EVALUATIONS_PATH.replace(DRAFT, "execpresetrev_" + "9" * 32)
        if change == "draft"
        else EVALUATIONS_PATH
    )
    baseline = "execpresetrev_" + "a" * 32 if change == "baseline" else BASE
    conflict = client.post(path, headers=HEADERS, json={"base_revision_id": baseline})
    assert conflict.status_code == 409
    assert conflict.json()["error_code"] == "API_IDEMPOTENCY_CONFLICT"
    assert len(owner.calls) == 1


@pytest.mark.parametrize(
    ("headers", "status", "code"),
    [
        ({"If-Match": '"v2"'}, 400, "API_IDEMPOTENCY_REQUIRED"),
        ({"Idempotency-Key": HEADERS["Idempotency-Key"]}, 428, "API_PRECONDITION_REQUIRED"),
        (HEADERS | {"If-Match": "v2"}, 412, "API_PRECONDITION_FAILED"),
    ],
)
def test_model_evaluation_missing_or_invalid_guards_do_not_enqueue(
    route_client: tuple[TestClient, FakePresetModels],
    headers: dict[str, str],
    status: int,
    code: str,
) -> None:
    client, owner = route_client
    response = client.post(EVALUATIONS_PATH, headers=headers, json={"base_revision_id": BASE})
    assert response.status_code == status
    assert response.json()["error_code"] == code
    assert owner.calls == []


def test_model_evaluation_request_rejects_client_supplied_acceptance(
    route_client: tuple[TestClient, FakePresetModels],
) -> None:
    client, owner = route_client
    response = client.post(
        EVALUATIONS_PATH,
        headers=HEADERS,
        json={"base_revision_id": BASE, "quality_evaluated": True, "scope": "LIVE_ONE_SHOT"},
    )
    assert response.status_code == 422
    assert owner.calls == []


@pytest.mark.parametrize(
    "method,path", [("GET", OPTIONS_PATH), ("GET", STATUS_PATH), ("POST", EVALUATIONS_PATH)]
)
@pytest.mark.parametrize("denial", ["admin", "fresh", "permission"])
def test_model_selection_routes_require_admin_recent_authentication_and_permission(
    method: str, path: str, denial: str
) -> None:
    client, services, owner = _route_client(
        admin=denial != "admin",
        fresh=denial != "fresh",
        read=denial != "permission",
        manage=denial != "permission",
    )
    try:
        with client:
            response = client.request(
                method,
                path,
                headers=HEADERS,
                **({"json": {"base_revision_id": BASE}} if method == "POST" else {}),
            )
        assert response.status_code == 403
        assert response.json()["error_code"] == (
            "AUTH_REAUTHENTICATION_REQUIRED" if denial == "fresh" else "PERMISSION_DENIED"
        )
        assert owner.calls == []
    finally:
        services.engine.dispose()


@pytest.mark.parametrize(
    "code",
    [
        "CONTROL_PRESET_BASE_STALE",
        "CONTROL_PRESET_FIXED_POLICY_CHANGED",
        "CONTROL_PRESET_MODEL_UNAVAILABLE",
        "CONTROL_VALIDATION_REPLAY_CONFLICT",
    ],
)
def test_model_evaluation_owner_rejection_is_not_reinterpreted_as_pass(
    route_client: tuple[TestClient, FakePresetModels], code: str
) -> None:
    client, owner = route_client
    owner.failure_code = code
    response = client.post(EVALUATIONS_PATH, headers=HEADERS, json={"base_revision_id": BASE})
    assert response.status_code == 409
    assert response.json()["error_code"] == code
    assert "data" not in response.json()
    assert len(owner.calls) == 1


@pytest.mark.parametrize(
    "code",
    [
        "CONTROL_PRESET_EVALUATION_REQUIRED",
        "CONTROL_PRESET_BASE_STALE",
        "CONTROL_PRESET_MODEL_UNAVAILABLE",
    ],
)
def test_release_keeps_owner_evaluation_baseline_and_freshness_denials(
    route_client: tuple[TestClient, FakePresetModels], code: str
) -> None:
    client, owner = route_client
    owner.failure_code = code
    response = client.post(
        f"/api/v1/execution-preset-revisions/{DRAFT}/releases", headers=HEADERS, json={}
    )
    assert response.status_code == 409
    assert response.json()["error_code"] == code
    assert "data" not in response.json()
    assert owner.calls[0]["operation"] == "release"


def test_api_adapter_uses_the_metadata_command_identity_without_creating_a_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """API queue insertion returns a command, not an Orchestrator Job record."""
    services = disconnected_services()  # type: ignore[no-untyped-call]
    adapter = PresetModelSelectionAdapter(services.engine)
    calls: list[dict[str, Any]] = []
    session = object()
    command = SimpleNamespace(validation_id=VALIDATION)

    @contextmanager
    def transaction(_sessions: object) -> Iterator[object]:
        yield session

    def enqueue(actual_session: object, **values: Any) -> SimpleNamespace:
        assert actual_session is session
        calls.append(values)
        return command

    def status(actual_session: object, validation_id: str) -> dict[str, Any]:
        assert actual_session is session
        assert validation_id == command.validation_id
        return _successful_validation() | {
            "status": "QUEUED",
            "evaluation_id": None,
            "completed_at": None,
            "cases_total": 0,
            "cases_passed": 0,
        }

    monkeypatch.setattr("eom_api.services.preset_model_selection_adapter.transaction", transaction)
    monkeypatch.setattr(
        "eom_api.services.preset_model_selection_adapter.enqueue_preset_model_validation", enqueue
    )
    monkeypatch.setattr("eom_api.services.preset_model_selection_adapter.validation_status", status)
    actor: Any = SimpleNamespace(actor_id=OPERATOR)
    try:
        view = adapter.enqueue(
            draft_revision_id=DRAFT,
            body=PresetModelEvaluationRequest(base_revision_id=BASE),
            actor=actor,
            expected_version=2,
            idempotency_key="api:" + "b" * 64,
        )
        assert view.validation_id == VALIDATION
        assert view.status == "QUEUED"
        assert len(calls) == 1
        assert calls[0]["draft_revision_id"] == DRAFT
        assert calls[0]["base_revision_id"] == BASE
        assert calls[0]["requested_by"] == OPERATOR
        assert calls[0]["expected_version"] == 2
    finally:
        services.engine.dispose()


@pytest.mark.parametrize(
    ("code", "status"),
    [
        ("CONTROL_PRESET_MISSING", 404),
        ("CONTROL_VALIDATION_MISSING", 404),
        ("CONTROL_PRESET_BASE_STALE", 409),
        ("CONTROL_VALIDATION_REPLAY_CONFLICT", 409),
        ("CONTROL_PRESET_EVALUATION_REQUIRED", 409),
        ("CONTROL_PRESET_FIXED_POLICY_CHANGED", 422),
        ("CONTROL_VALIDATION_REQUEST_INVALID", 422),
    ],
)
def test_api_adapter_keeps_stable_owner_errors_and_redacts_internal_detail(
    code: str, status: int
) -> None:
    error = ControlPlaneError(code, "internal fixture path /srv/private and secret fixture")
    with pytest.raises(ApiError) as exc_info:
        PresetModelSelectionAdapter._raise_api_error(error)
    assert exc_info.value.status == status
    assert exc_info.value.error_code == code
    assert "internal fixture" not in exc_info.value.detail
    assert "/srv/private" not in exc_info.value.detail


@pytest.mark.parametrize(
    ("logical_changes", "row_changes", "expected_code"),
    [
        ({"state": "RETIRED"}, {}, "CONTROL_PRESET_RETIRED"),
        ({"current_revision_id": None}, {}, "CONTROL_PRESET_NOT_PUBLISHED"),
        ({}, {"preset_id": "execpreset_" + "8" * 32}, "CONTROL_PRESET_POINTER_INVALID"),
        ({}, {"state": "DRAFT"}, "CONTROL_PRESET_POINTER_INVALID"),
    ],
)
def test_model_options_adapter_never_replaces_an_ineligible_current_pointer(
    monkeypatch: pytest.MonkeyPatch,
    logical_changes: dict[str, Any],
    row_changes: dict[str, Any],
    expected_code: str,
) -> None:
    from eom_orchestrator.control_models import ExecutionPresetRecord

    services = disconnected_services()  # type: ignore[no-untyped-call]
    adapter = PresetModelSelectionAdapter(services.engine)
    logical = SimpleNamespace(
        **({"preset_id": PRESET, "state": "ACTIVE", "current_revision_id": BASE} | logical_changes)
    )
    row = SimpleNamespace(**({"preset_id": PRESET, "state": "RELEASED"} | row_changes))
    lookups: list[tuple[type[Any], str]] = []

    class Session:
        def get(self, model: type[Any], identity: str) -> Any:
            lookups.append((model, identity))
            return logical if model is ExecutionPresetRecord else row

    @contextmanager
    def sessions() -> Iterator[Session]:
        yield Session()

    def forbidden_resolution(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("ineligible current pointer must not resolve any fallback")

    monkeypatch.setattr(adapter, "sessions", sessions)
    monkeypatch.setattr(
        "eom_api.services.preset_model_selection_adapter.validated_preset", forbidden_resolution
    )
    monkeypatch.setattr(
        "eom_api.services.preset_model_selection_adapter.preset_model_options", forbidden_resolution
    )
    try:
        with pytest.raises(ApiError) as error:
            adapter.options(PRESET)
        assert error.value.error_code == expected_code
        assert lookups[0] == (ExecutionPresetRecord, PRESET)
        assert all(identity in {PRESET, BASE} for _model, identity in lookups)
    finally:
        services.engine.dispose()


def test_model_options_adapter_resolves_only_the_exact_released_current_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from eom_orchestrator.control_models import ExecutionPresetRecord, ExecutionPresetRevisionRecord

    services = disconnected_services()  # type: ignore[no-untyped-call]
    adapter = PresetModelSelectionAdapter(services.engine)
    logical = SimpleNamespace(preset_id=PRESET, state="ACTIVE", current_revision_id=BASE)
    row = SimpleNamespace(preset_id=PRESET, state="RELEASED")
    policy = SimpleNamespace(role="authoring", worker_pool_key="science-authoring")
    preset = SimpleNamespace(preset_revision_id=BASE, role_policies=(policy,))
    lookups: list[tuple[type[Any], str]] = []

    class Session:
        def get(self, model: type[Any], identity: str) -> Any:
            lookups.append((model, identity))
            return logical if model is ExecutionPresetRecord else row

    session = Session()

    @contextmanager
    def sessions() -> Iterator[Session]:
        yield session

    def resolve_preset(actual_row: Any) -> Any:
        assert actual_row is row
        return preset

    def options(
        actual_session: Any, actual_preset: Any, *, observed_at: datetime
    ) -> dict[str, Any]:
        assert actual_session is session and actual_preset is preset
        assert observed_at.tzinfo is UTC
        return {"authoring": ()}  # Unknown catalog stays unavailable, never guessed.

    monkeypatch.setattr(adapter, "sessions", sessions)
    monkeypatch.setattr(
        "eom_api.services.preset_model_selection_adapter.validated_preset", resolve_preset
    )
    monkeypatch.setattr(
        "eom_api.services.preset_model_selection_adapter.preset_model_options", options
    )
    try:
        result = adapter.options(PRESET)
        assert lookups == [(ExecutionPresetRecord, PRESET), (ExecutionPresetRevisionRecord, BASE)]
        assert result.preset_revision_id == BASE
        assert result.roles[0].worker_pool_key == "science-authoring"
        assert result.roles[0].candidates == ()
        assert result.catalog_is_entitlement is False
    finally:
        services.engine.dispose()
