"""Source-only authenticated-owner orchestration; no API/DB/NAS publication."""

from __future__ import annotations

import os
import pwd
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

import pytest
from eom_api_contracts.auth import CurrentOperator
from eom_operator_identity import PermissionKey
from eom_orchestrator import inference_transfer_control_invocation as invocation
from eom_orchestrator.control_artifacts import ControlArtifactPublisher
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.inference_transfer_bootstrap import (
    PreparedInferenceTransferControls,
    ReleasedInferenceTransferControls,
)
from sqlalchemy.orm import Session, sessionmaker

from tests.unit.inference_transfer_bootstrap_fixtures import PLATFORM_BYTES, RUBRIC_BYTES
from tests.unit.inference_transfer_control_invocation_fixtures import (
    prepared_receipt,
    release_request,
    release_result,
)

_NOW = datetime(2026, 10, 10, 9, 5, tzinfo=UTC)
_ACTOR = "operator_" + "a" * 32


def _principal(**changes: Any) -> CurrentOperator:
    return CurrentOperator.model_validate(
        {
            "operator_id": _ACTOR,
            "username": "synthetic-admin",
            "display_name": "합성 관리자",
            "roles": ["ADMIN"],
            "effective_permissions": ["execution_preset:manage"],
            "session_id": "apisession_" + "b" * 32,
            "authenticated_at": _NOW - timedelta(minutes=5),
            "access_expires_at": _NOW + timedelta(minutes=10),
            "password_change_required": False,
        }
        | changes
    )


class _Reader:
    def __init__(self, values: list[CurrentOperator] | None = None) -> None:
        self.values = values or [_principal()]
        self.calls = 0

    def read(self) -> CurrentOperator:
        self.calls += 1
        return self.values[min(self.calls - 1, len(self.values) - 1)]


class _Session:
    def __init__(self) -> None:
        self.operator: Any = SimpleNamespace(
            status="ACTIVE", deleted_at=None, must_change_password=False
        )
        self.calls = 0

    def __enter__(self) -> _Session:
        return self

    def __exit__(self, *_args: Any) -> None:
        pass

    def get(self, _model: Any, operator_id: str) -> Any:
        assert operator_id == _ACTOR
        self.calls += 1
        return self.operator


def _owner(
    monkeypatch: pytest.MonkeyPatch, reader: _Reader | None = None
) -> tuple[invocation.AuthenticatedInferenceTransferControlOwner, _Reader, _Session]:
    reader = reader or _Reader()
    session = _Session()
    monkeypatch.setattr(
        invocation,
        "active_role_assignments",
        lambda *_args: [(None, SimpleNamespace(role_key="ADMIN"))],
    )
    monkeypatch.setattr(
        invocation,
        "effective_permissions",
        lambda *_args: frozenset({PermissionKey.EXECUTION_PRESET_MANAGE}),
    )
    owner = invocation.AuthenticatedInferenceTransferControlOwner(
        cast(sessionmaker[Session], lambda: session),
        cast(ControlArtifactPublisher, object()),
        reader,
        now=lambda: _NOW,
    )
    return owner, reader, session


def test_prepare_calls_existing_draft_leaf_and_reauthenticates_every_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, reader, session = _owner(monkeypatch)
    receipt = prepared_receipt()
    leaf_calls = 0

    def prepare(*_args: Any, **kwargs: Any) -> PreparedInferenceTransferControls:
        nonlocal leaf_calls
        leaf_calls += 1
        assert kwargs["operator_id"] == _ACTOR
        assert kwargs["observed_at"] == _NOW
        assert kwargs["manifest"] == receipt.manifest
        for _ in range(3):
            kwargs["authorize_control_change"](_ACTOR, "PREPARE")
        return PreparedInferenceTransferControls(
            receipt.manifest, receipt.bootstrap_artifact, receipt.instruction_bundle, receipt.draft
        )

    monkeypatch.setattr(invocation, "prepare_inference_transfer_controls", prepare)
    monkeypatch.setattr(
        invocation, "release_inference_transfer_controls", lambda *_args, **_kwargs: pytest.fail()
    )
    assert (
        owner.prepare(
            receipt.manifest, platform_payload=PLATFORM_BYTES, rubric_payload=RUBRIC_BYTES
        )
        == receipt
    )
    assert leaf_calls == 1
    assert reader.calls == 4
    assert session.calls == 3


def test_explicit_release_calls_leaf_once_and_returns_only_non_live_quality_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, reader, session = _owner(monkeypatch)
    request = release_request()
    result = release_result(request)
    leaf_calls = 0

    def release(*_args: Any, **kwargs: Any) -> ReleasedInferenceTransferControls:
        nonlocal leaf_calls
        leaf_calls += 1
        assert kwargs["released_at"] == _NOW
        assert kwargs["prepared"].draft == request.receipt.draft
        kwargs["authorize_control_change"](_ACTOR, "RELEASE")
        kwargs["authorize_control_change"](_ACTOR, "RELEASE")
        return ReleasedInferenceTransferControls(
            result.preset, result.evaluation_id, result.evaluation_artifact, result.executed_cases
        )

    monkeypatch.setattr(invocation, "release_inference_transfer_controls", release)
    assert owner.release(request) == result
    assert leaf_calls == 1 and reader.calls == 3 and session.calls == 2
    assert result.quality_score_permille is None
    assert result.scientific_evaluation == result.human_transfer_evaluation == "NOT_EVALUATED"


@pytest.mark.parametrize(
    "changes",
    [
        {"roles": []},
        {"effective_permissions": []},
        {"password_change_required": True},
        {"access_expires_at": _NOW},
        {"authenticated_at": _NOW + timedelta(seconds=1)},
        {"authenticated_at": _NOW - timedelta(minutes=15, seconds=1)},
        {"operator_id": "untrusted"},
        {"session_id": "untrusted"},
    ],
)
def test_invalid_official_principal_fails_before_any_leaf_or_database_read(
    monkeypatch: pytest.MonkeyPatch, changes: dict[str, Any]
) -> None:
    owner, reader, session = _owner(monkeypatch, _Reader([_principal(**changes)]))
    monkeypatch.setattr(
        invocation, "release_inference_transfer_controls", lambda *_args, **_kwargs: pytest.fail()
    )
    with pytest.raises(ControlPlaneError, match="authorization") as caught:
        owner.release(release_request())
    assert caught.value.code == "CONTROL_AUTHORIZATION_REQUIRED"
    assert reader.calls == 1 and session.calls == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"operator_id": "operator_" + "c" * 32},
        {"session_id": "apisession_" + "d" * 32},
        {"roles": []},
        {"effective_permissions": []},
    ],
)
def test_publication_boundary_rejects_actor_session_or_authority_drift(
    monkeypatch: pytest.MonkeyPatch, changes: dict[str, Any]
) -> None:
    owner, reader, session = _owner(monkeypatch, _Reader([_principal(), _principal(**changes)]))

    def release(*_args: Any, **kwargs: Any) -> None:
        kwargs["authorize_control_change"](_ACTOR, "RELEASE")
        pytest.fail("publication must not pass revoked or foreign official identity")

    monkeypatch.setattr(invocation, "release_inference_transfer_controls", release)
    with pytest.raises(ControlPlaneError):
        owner.release(release_request())
    assert reader.calls == 2 and session.calls == 0


@pytest.mark.parametrize(
    "change",
    ["MISSING", "DISABLED", "DELETED", "PASSWORD_CHANGE", "ROLE", "PERMISSION"],
)
def test_owner_database_rechecks_current_identity_independently_of_api_snapshot(
    monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    owner, reader, session = _owner(monkeypatch)
    if change == "MISSING":
        session.operator = None
    elif change == "DISABLED":
        session.operator.status = "DISABLED"
    elif change == "DELETED":
        session.operator.deleted_at = _NOW
    elif change == "PASSWORD_CHANGE":
        session.operator.must_change_password = True
    elif change == "ROLE":
        monkeypatch.setattr(invocation, "active_role_assignments", lambda *_args: [])
    elif change == "PERMISSION":
        monkeypatch.setattr(invocation, "effective_permissions", lambda *_args: frozenset())
    with pytest.raises(ControlPlaneError):
        owner._authorize(_ACTOR, "PREPARE")
    assert reader.calls == session.calls == 1


def test_wrong_actor_action_and_non_utc_clock_cannot_grant_permission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, _, _ = _owner(monkeypatch)
    with pytest.raises(ControlPlaneError):
        owner._authorize("operator_" + "f" * 32, "PREPARE")
    with pytest.raises(ControlPlaneError):
        owner._authorize(_ACTOR, cast(Any, "ACTIVATE"))
    owner._now = lambda: _NOW.replace(tzinfo=None)
    with pytest.raises(ControlPlaneError) as caught:
        owner._current_principal()
    assert caught.value.code == "CONTROL_OWNER_CLOCK_INVALID"


def test_manifest_member_hash_or_forged_receipt_is_rejected_before_authentication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, reader, session = _owner(monkeypatch)
    with pytest.raises(ValueError):
        owner.prepare(
            prepared_receipt().manifest,
            platform_payload=PLATFORM_BYTES + b"changed",
            rubric_payload=RUBRIC_BYTES,
        )
    request = release_request().model_copy(update={"request_sha256": "sha256:" + "0" * 64})
    with pytest.raises(ValueError):
        owner.release(request)
    assert reader.calls == session.calls == 0


def test_uncertain_release_failure_is_not_retried_or_reinterpreted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, _, _ = _owner(monkeypatch)
    calls = 0

    def release(*_args: Any, **_kwargs: Any) -> None:
        nonlocal calls
        calls += 1
        raise ControlPlaneError("CONTROL_REVISION_CONFLICT", "synthetic partial publication")

    monkeypatch.setattr(invocation, "release_inference_transfer_controls", release)
    with pytest.raises(ControlPlaneError) as caught:
        owner.release(release_request())
    assert caught.value.code == "CONTROL_REVISION_CONFLICT" and calls == 1


@pytest.mark.parametrize(
    "uid,gid,euid,egid", [(0, 0, 0, 0), (991, 991, 992, 991), (991, 991, 991, 992)]
)
def test_root_wrong_or_setid_owner_fails_before_any_protected_input(
    monkeypatch: pytest.MonkeyPatch, uid: int, gid: int, euid: int, egid: int
) -> None:
    monkeypatch.setattr(pwd, "getpwnam", lambda name: SimpleNamespace(pw_uid=991))
    for name, value in (("getuid", uid), ("getgid", gid), ("geteuid", euid), ("getegid", egid)):
        monkeypatch.setattr(os, name, lambda value=value: value)
    with pytest.raises(ControlPlaneError) as caught:
        invocation.require_inference_transfer_control_owner()
    assert caught.value.code == "CONTROL_OWNER_IDENTITY_REQUIRED"


def test_expected_fixed_owner_identity_and_missing_account(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pwd, "getpwnam", lambda name: SimpleNamespace(pw_uid=991))
    for name in ("getuid", "getgid", "geteuid", "getegid"):
        monkeypatch.setattr(os, name, lambda: 991)
    invocation.require_inference_transfer_control_owner()
    monkeypatch.setattr(pwd, "getpwnam", lambda name: (_ for _ in ()).throw(KeyError(name)))
    with pytest.raises(ControlPlaneError):
        invocation.require_inference_transfer_control_owner()
