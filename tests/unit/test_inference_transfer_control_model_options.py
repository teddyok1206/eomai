"""Source-only exact model metadata reads; no runtime DB, observation or publication."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

import pytest
from eom_api_contracts.auth import CurrentOperator
from eom_identity_service.models import OperatorRecord
from eom_operator_identity import PermissionKey
from eom_orchestrator import inference_transfer_control_invocation as invocation
from eom_orchestrator.control_artifacts import ControlArtifactPublisher
from eom_orchestrator.control_service import ControlPlaneError
from eom_workflow.control_plane import ModelCandidate, ReasoningEffort, WorkerRole
from eom_workflow.inference_transfer_bootstrap_contract import InferenceTransferBootstrapCapacityPin
from sqlalchemy.orm import Session, sessionmaker

NOW = datetime(2026, 10, 11, 18, 50, tzinfo=UTC)
ACTOR = "operator_" + "a" * 32
PIN = InferenceTransferBootstrapCapacityPin(
    capacity_policy_id="capacity_" + "1" * 32,
    capacity_policy_revision_id="capacityrev_" + "2" * 32,
    schema_version="worker-capacity-policy/1.3",
    content_sha256="sha256:" + "3" * 64,
)
OPTIONS = (
    ModelCandidate(model="synthetic-model-a", reasoning_effort=ReasoningEffort.MEDIUM),
    ModelCandidate(model="synthetic-model-b", reasoning_effort=ReasoningEffort.HIGH),
)


def principal(**changes: Any) -> CurrentOperator:
    return CurrentOperator.model_validate(
        {
            "operator_id": ACTOR,
            "username": "synthetic-admin",
            "display_name": "합성 관리자",
            "roles": ["ADMIN"],
            "effective_permissions": ["execution_preset:manage"],
            "session_id": "apisession_" + "b" * 32,
            "authenticated_at": NOW - timedelta(minutes=5),
            "access_expires_at": NOW + timedelta(minutes=10),
            "password_change_required": False,
        }
        | changes
    )


class PrincipalReader:
    def __init__(self, events: list[str]) -> None:
        self.value = principal()
        self.events = events
        self.calls = 0

    def read(self) -> CurrentOperator:
        self.events.append("principal")
        self.calls += 1
        return self.value


class ReadSession:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.operator = SimpleNamespace(
            status="ACTIVE", deleted_at=None, must_change_password=False
        )
        self.allowed = True
        self.calls = 0

    def __enter__(self) -> ReadSession:
        return self

    def __exit__(self, *_args: Any) -> None:
        pass

    def get(self, model: Any, operator_id: str) -> SimpleNamespace:
        assert model is OperatorRecord and operator_id == ACTOR
        self.events.append("db-authorization")
        self.calls += 1
        return self.operator


def owner(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[
    invocation.AuthenticatedInferenceTransferControlOwner,
    PrincipalReader,
    ReadSession,
    list[str],
]:
    events: list[str] = []
    reader, session = PrincipalReader(events), ReadSession(events)
    monkeypatch.setattr(
        invocation,
        "active_role_assignments",
        lambda *_args: [(None, SimpleNamespace(role_key="ADMIN"))],
    )
    monkeypatch.setattr(
        invocation,
        "effective_permissions",
        lambda *_args: (
            frozenset({PermissionKey.EXECUTION_PRESET_MANAGE}) if session.allowed else frozenset()
        ),
    )

    def resolve(actual: Any, revision_id: str) -> InferenceTransferBootstrapCapacityPin:
        assert actual is session
        events.append("exact-pin")
        assert revision_id == PIN.capacity_policy_revision_id
        return PIN

    monkeypatch.setattr(invocation, "resolve_released_capacity_policy", resolve)
    for leaf in (
        "prepare_inference_transfer_controls",
        "prepare_inference_transfer_controls_v11",
        "release_inference_transfer_controls",
        "release_inference_transfer_controls_v11",
    ):
        monkeypatch.setattr(invocation, leaf, lambda *_args, **_kwargs: pytest.fail("mutation"))
    value = invocation.AuthenticatedInferenceTransferControlOwner(
        cast(sessionmaker[Session], lambda: session),
        cast(ControlArtifactPublisher, object()),
        reader,
        now=lambda: NOW,
    )
    return value, reader, session, events


@pytest.mark.parametrize("options", [OPTIONS, ()])
def test_exact_options_use_existing_admission_and_reauthorize_before_and_after(
    monkeypatch: pytest.MonkeyPatch, options: tuple[ModelCandidate, ...]
) -> None:
    actual, reader, session, events = owner(monkeypatch)
    before = PIN.model_dump(mode="json")
    calls = 0

    def read_options(native: Any, **kwargs: Any) -> tuple[ModelCandidate, ...]:
        nonlocal calls
        assert native is session
        assert kwargs == {
            "capacity_policy_revision_id": PIN.capacity_policy_revision_id,
            "role": WorkerRole.SUPPORT,
            "worker_pool_key": "customer-support",
            "observed_at": NOW,
        }
        events.append("model-options")
        calls += 1
        return options

    monkeypatch.setattr(invocation, "capacity_pool_model_options", read_options)
    assert actual.read_model_options(PIN) is options
    assert PIN.model_dump(mode="json") == before
    assert calls == 1 and reader.calls == 6 and session.calls == 4
    position = events.index("model-options")
    assert "db-authorization" in events[:position]
    assert events[position + 1 :] == ["principal", "db-authorization"]


@pytest.mark.parametrize(
    "changes",
    [
        {"capacity_policy_id": "capacity_" + "4" * 32},
        {"schema_version": "worker-capacity-policy/1.0"},
        {"content_sha256": "sha256:" + "5" * 64},
    ],
)
def test_mismatched_expected_capacity_pin_never_reads_options(
    monkeypatch: pytest.MonkeyPatch, changes: dict[str, str]
) -> None:
    actual, _, _, events = owner(monkeypatch)
    monkeypatch.setattr(
        invocation, "capacity_pool_model_options", lambda *_args, **_kwargs: pytest.fail()
    )
    with pytest.raises(ControlPlaneError) as caught:
        actual.read_model_options(PIN.model_copy(update=changes))
    assert caught.value.code == "CONTROL_CAPACITY_POINTER_INVALID"
    assert events.count("exact-pin") == 1


def test_nonexact_revision_is_denied_before_authentication_or_model_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actual, reader, session, _ = owner(monkeypatch)
    monkeypatch.setattr(
        invocation, "capacity_pool_model_options", lambda *_args, **_kwargs: pytest.fail()
    )
    with pytest.raises(ControlPlaneError) as caught:
        actual.read_model_options(PIN.model_copy(update={"capacity_policy_revision_id": "latest"}))
    assert caught.value.code == "CONTROL_CAPACITY_POINTER_INVALID"
    assert reader.calls == session.calls == 0


def test_missing_exact_capacity_has_stable_error_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actual, _, _, _ = owner(monkeypatch)

    def missing(*_args: Any) -> None:
        raise ControlPlaneError("CONTROL_CAPACITY_POINTER_INVALID", "capacity policy unavailable")

    monkeypatch.setattr(invocation, "resolve_released_capacity_policy", missing)
    monkeypatch.setattr(
        invocation, "capacity_pool_model_options", lambda *_args, **_kwargs: pytest.fail()
    )
    with pytest.raises(ControlPlaneError) as caught:
        actual.read_model_options(PIN)
    assert caught.value.code == "CONTROL_CAPACITY_POINTER_INVALID"


@pytest.mark.parametrize(
    "changes",
    [
        {"roles": []},
        {"effective_permissions": []},
        {"password_change_required": True},
        {"access_expires_at": NOW},
        {"authenticated_at": NOW - timedelta(minutes=15, seconds=1)},
    ],
)
def test_denied_fresh_principal_cannot_resolve_pin_or_options(
    monkeypatch: pytest.MonkeyPatch, changes: dict[str, Any]
) -> None:
    actual, reader, session, events = owner(monkeypatch)
    reader.value = principal(**changes)
    monkeypatch.setattr(
        invocation, "capacity_pool_model_options", lambda *_args, **_kwargs: pytest.fail()
    )
    with pytest.raises(ControlPlaneError) as caught:
        actual.read_model_options(PIN)
    assert caught.value.code == "CONTROL_AUTHORIZATION_REQUIRED"
    assert reader.calls == 1 and session.calls == 0 and "exact-pin" not in events


def test_current_database_denial_cannot_resolve_pin_or_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actual, _, session, events = owner(monkeypatch)
    session.allowed = False
    monkeypatch.setattr(
        invocation, "capacity_pool_model_options", lambda *_args, **_kwargs: pytest.fail()
    )
    with pytest.raises(ControlPlaneError) as caught:
        actual.read_model_options(PIN)
    assert caught.value.code == "CONTROL_AUTHORIZATION_REQUIRED" and "exact-pin" not in events


@pytest.mark.parametrize(
    "changes",
    [
        {"operator_id": "operator_" + "c" * 32},
        {"session_id": "apisession_" + "d" * 32},
        {"roles": []},
        {"effective_permissions": []},
        {"access_expires_at": NOW},
    ],
)
def test_post_read_principal_drift_never_returns_collected_options(
    monkeypatch: pytest.MonkeyPatch, changes: dict[str, Any]
) -> None:
    actual, reader, _, _ = owner(monkeypatch)
    calls = 0

    def read_options(*_args: Any, **_kwargs: Any) -> tuple[ModelCandidate, ...]:
        nonlocal calls
        calls += 1
        reader.value = principal(**changes)
        return OPTIONS

    monkeypatch.setattr(invocation, "capacity_pool_model_options", read_options)
    with pytest.raises(ControlPlaneError) as caught:
        actual.read_model_options(PIN)
    assert caught.value.code == "CONTROL_AUTHORIZATION_REQUIRED" and calls == 1


def test_post_read_database_permission_revocation_never_returns_collected_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actual, _, session, _ = owner(monkeypatch)
    calls = 0

    def read_options(*_args: Any, **_kwargs: Any) -> tuple[ModelCandidate, ...]:
        nonlocal calls
        calls += 1
        session.allowed = False
        return OPTIONS

    monkeypatch.setattr(invocation, "capacity_pool_model_options", read_options)
    with pytest.raises(ControlPlaneError) as caught:
        actual.read_model_options(PIN)
    assert caught.value.code == "CONTROL_AUTHORIZATION_REQUIRED" and calls == 1


@pytest.mark.parametrize(
    "code", ["CONTROL_CAPACITY_POINTER_INVALID", "CONTROL_PRESET_POOL_INVALID"]
)
def test_native_options_error_is_preserved_without_fabricated_candidates(
    monkeypatch: pytest.MonkeyPatch, code: str
) -> None:
    actual, _, _, _ = owner(monkeypatch)

    def unavailable(*_args: Any, **_kwargs: Any) -> tuple[ModelCandidate, ...]:
        raise ControlPlaneError(code, "native metadata unavailable")

    monkeypatch.setattr(invocation, "capacity_pool_model_options", unavailable)
    with pytest.raises(ControlPlaneError) as caught:
        actual.read_model_options(PIN)
    assert caught.value.code == code
