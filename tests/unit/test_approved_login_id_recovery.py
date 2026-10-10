from __future__ import annotations

from contextlib import nullcontext
from dataclasses import FrozenInstanceError, dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest
from eom_identity_service import approved_login_id_recovery as recovery_module
from eom_identity_service.approved_login_id_recovery import (
    APPROVED_PAIR_PINS,
    ApprovedLoginIdPasswordRecoveryService,
    ApprovedLoginIdPasswordResetCommand,
    ApprovedRecoveryTarget,
)
from eom_identity_service.local_admin_recovery import LocalAdminRecoveryAuthorization
from eom_operator_identity.errors import IdentityError, IdentityErrorCode

# Opaque approved identity pins only; usernames, hashes, sessions and DB state below are synthetic.
OPERATOR_IDS = (
    "operator_21501765843779a7c3a13cd9afaf255b",
    "operator_9237daf1ce9ebad3098ef2372fb6ff91",
)
TARGETS = (
    ApprovedRecoveryTarget(OPERATOR_IDS[0], expected_resource_version=1),
    ApprovedRecoveryTarget(OPERATOR_IDS[1], expected_resource_version=1),
)
REQUEST_ID = "cli_" + "c" * 24
RESET_AT = datetime(2026, 10, 10, 9, 30, tzinfo=UTC)


def _command() -> ApprovedLoginIdPasswordResetCommand:
    return ApprovedLoginIdPasswordResetCommand(
        targets=(TARGETS[1], TARGETS[0]), request_id=REQUEST_ID
    )


@dataclass
class _RecoveryFixture:
    service: ApprovedLoginIdPasswordRecoveryService
    operators: dict[str, SimpleNamespace]
    credentials: dict[str, SimpleNamespace]
    authorizer: Mock
    passwords: Mock
    session: Mock
    transaction: Mock
    lock_invariants: Mock
    require_operator: Mock
    require_credential: Mock
    revoke: Mock
    event: Mock


def _service_fixture(monkeypatch: pytest.MonkeyPatch) -> _RecoveryFixture:
    operators = {
        target.operator_id: SimpleNamespace(
            operator_id=target.operator_id,
            username=f"TEST_ONLY_login_{index}",
            display_name=f"TEST_ONLY Operator {index}",
            status="ACTIVE",
            must_change_password=False,
            lock_version=target.expected_resource_version,
        )
        for index, target in enumerate(TARGETS)
    }
    credentials = {
        operator_id: SimpleNamespace(
            password_hash=f"TEST_ONLY_old_hash_{index}",
            password_algorithm="argon2id",
            password_version=index + 2,
            must_change_password=False,
            password_changed_at=datetime(2026, 1, 1, tzinfo=UTC),
            failed_login_count=4,
            first_failed_at=datetime(2026, 1, 2, tzinfo=UTC),
            last_failed_at=datetime(2026, 1, 3, tzinfo=UTC),
            locked_until=datetime(2026, 1, 4, tzinfo=UTC),
        )
        for index, operator_id in enumerate(OPERATOR_IDS)
    }
    session = Mock()
    transaction = Mock(return_value=nullcontext(session))
    lock_invariants = Mock()
    require_operator = Mock(side_effect=lambda _, operator_id, **__: operators[operator_id])
    require_credential = Mock(side_effect=lambda _, operator_id, **__: credentials[operator_id])
    passwords = Mock()
    passwords.hash_temporary_login_id_password.side_effect = lambda *, username: (
        f"TEST_ONLY_new_hash_{username}"
    )
    authorizer = Mock()
    authorizer.authorize.return_value = LocalAdminRecoveryAuthorization(
        os_principal="eom", os_uid=1000, os_gid=1000
    )
    revoke = Mock(
        side_effect=lambda _, operator_id, **__: 3 if operator_id == OPERATOR_IDS[0] else 1
    )
    event = Mock()
    service = object.__new__(ApprovedLoginIdPasswordRecoveryService)
    service.sessions = Mock()
    service.authorizer = authorizer
    service.passwords = passwords
    monkeypatch.setattr(recovery_module, "transaction", transaction)
    monkeypatch.setattr(recovery_module, "lock_identity_invariants", lock_invariants)
    monkeypatch.setattr(recovery_module, "require_operator", require_operator)
    monkeypatch.setattr(recovery_module, "require_credential", require_credential)
    monkeypatch.setattr(recovery_module, "revoke_operator_sessions", revoke)
    monkeypatch.setattr(recovery_module, "add_operator_event", event)
    monkeypatch.setattr(recovery_module, "utc_now", lambda: RESET_AT)
    return _RecoveryFixture(
        service,
        operators,
        credentials,
        authorizer,
        passwords,
        session,
        transaction,
        lock_invariants,
        require_operator,
        require_credential,
        revoke,
        event,
    )


def _snapshot(fixture: _RecoveryFixture) -> tuple[dict[str, object], ...]:
    return tuple(
        dict(vars(value))
        for mapping in (fixture.operators, fixture.credentials)
        for value in mapping.values()
    )


def _assert_no_changes(fixture: _RecoveryFixture, before: tuple[dict[str, object], ...]) -> None:
    assert _snapshot(fixture) == before
    fixture.revoke.assert_not_called()
    fixture.event.assert_not_called()
    fixture.session.flush.assert_not_called()


def test_command_accepts_exact_distinct_version_pinned_pair_and_is_frozen() -> None:
    command = _command()

    assert frozenset((operator_id, 1) for operator_id in OPERATOR_IDS) == APPROVED_PAIR_PINS
    assert command.targets == (TARGETS[1], TARGETS[0])
    assert command.request_id == REQUEST_ID
    with pytest.raises(FrozenInstanceError):
        command.request_id = "cli_" + "d" * 24  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        TARGETS[0].expected_resource_version = 8  # type: ignore[misc]


@pytest.mark.parametrize(
    "operator_id",
    ["", "operator_short", "operator_" + "A" * 32, "operator_" + "a" * 32 + "\n"],
)
def test_target_rejects_invalid_operator_id(operator_id: str) -> None:
    with pytest.raises(ValueError, match="invalid approved Operator ID"):
        ApprovedRecoveryTarget(operator_id, expected_resource_version=1)


@pytest.mark.parametrize("version", [0, -1, True, False, 1.0, "7", None])
def test_target_requires_positive_integer_version(version: object) -> None:
    with pytest.raises(ValueError, match="invalid approved Operator version"):
        ApprovedRecoveryTarget(OPERATOR_IDS[0], expected_resource_version=version)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "targets",
    [
        (),
        (TARGETS[0],),
        (TARGETS[0], TARGETS[1], TARGETS[0]),
        [TARGETS[0], TARGETS[1]],
        (TARGETS[0], TARGETS[0]),
        (TARGETS[0], ApprovedRecoveryTarget(OPERATOR_IDS[0], expected_resource_version=8)),
        (TARGETS[0], "untrusted-target"),
    ],
)
def test_command_requires_exactly_two_distinct_typed_targets(targets: object) -> None:
    with pytest.raises(ValueError, match="exactly two distinct approved targets"):
        ApprovedLoginIdPasswordResetCommand(targets=targets, request_id=REQUEST_ID)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "targets",
    [
        (
            ApprovedRecoveryTarget("operator_" + "a" * 32, expected_resource_version=1),
            ApprovedRecoveryTarget("operator_" + "b" * 32, expected_resource_version=1),
        ),
        (
            TARGETS[0],
            ApprovedRecoveryTarget("operator_" + "b" * 32, expected_resource_version=1),
        ),
        (
            ApprovedRecoveryTarget(OPERATOR_IDS[0], expected_resource_version=2),
            TARGETS[1],
        ),
        (
            TARGETS[0],
            ApprovedRecoveryTarget(OPERATOR_IDS[1], expected_resource_version=2),
        ),
        (
            ApprovedRecoveryTarget(OPERATOR_IDS[0], expected_resource_version=2),
            ApprovedRecoveryTarget(OPERATOR_IDS[1], expected_resource_version=2),
        ),
    ],
)
def test_command_rejects_another_pair_or_refreshed_approval_versions(
    targets: tuple[ApprovedRecoveryTarget, ApprovedRecoveryTarget],
) -> None:
    with pytest.raises(ValueError, match="original one-use owner approval"):
        ApprovedLoginIdPasswordResetCommand(targets=targets, request_id=REQUEST_ID)


@pytest.mark.parametrize("request_id", ["", "arbitrary-reason", "cli_short", "cli_" + "C" * 24])
def test_command_rejects_invalid_request_id(request_id: str) -> None:
    with pytest.raises(ValueError, match="invalid approved recovery request ID"):
        ApprovedLoginIdPasswordResetCommand(targets=TARGETS, request_id=request_id)


@pytest.mark.parametrize("refusal", ["exception", "none", "untrusted-object"])
def test_local_authorization_refusal_precedes_transaction(
    monkeypatch: pytest.MonkeyPatch, refusal: str
) -> None:
    fixture = _service_fixture(monkeypatch)
    if refusal == "exception":
        fixture.authorizer.authorize.side_effect = IdentityError(
            IdentityErrorCode.EMERGENCY_RESET_UNAUTHORIZED, "not the trusted local principal"
        )
    else:
        fixture.authorizer.authorize.return_value = None if refusal == "none" else object()
    before = _snapshot(fixture)

    with pytest.raises(IdentityError) as raised:
        fixture.service.reset_approved_pair(_command())

    assert raised.value.code is IdentityErrorCode.EMERGENCY_RESET_UNAUTHORIZED
    fixture.authorizer.authorize.assert_called_once_with()
    fixture.transaction.assert_not_called()
    fixture.lock_invariants.assert_not_called()
    fixture.require_operator.assert_not_called()
    fixture.require_credential.assert_not_called()
    fixture.passwords.hash_temporary_login_id_password.assert_not_called()
    _assert_no_changes(fixture, before)


@pytest.mark.parametrize("operator_id", OPERATOR_IDS)
@pytest.mark.parametrize(
    ("failure", "expected_code"),
    [
        ("disabled", IdentityErrorCode.OPERATOR_DISABLED),
        ("stale", IdentityErrorCode.OPERATOR_VERSION_CONFLICT),
        ("missing-operator", IdentityErrorCode.OPERATOR_NOT_FOUND),
        ("missing-credential", IdentityErrorCode.OPERATOR_NOT_FOUND),
    ],
)
def test_invalid_target_refuses_both_before_hashing_or_mutation(
    monkeypatch: pytest.MonkeyPatch,
    operator_id: str,
    failure: str,
    expected_code: IdentityErrorCode,
) -> None:
    fixture = _service_fixture(monkeypatch)
    if failure == "disabled":
        fixture.operators[operator_id].status = "DISABLED"
    elif failure == "stale":
        fixture.operators[operator_id].lock_version += 1
    else:

        def require_target(_: object, requested_id: str, **__: object) -> SimpleNamespace:
            if requested_id == operator_id:
                raise IdentityError(IdentityErrorCode.OPERATOR_NOT_FOUND, "target not found")
            mapping = fixture.operators if failure == "missing-operator" else fixture.credentials
            return mapping[requested_id]

        require = (
            fixture.require_operator
            if failure == "missing-operator"
            else fixture.require_credential
        )
        require.side_effect = require_target
    before = _snapshot(fixture)

    with pytest.raises(IdentityError) as raised:
        fixture.service.reset_approved_pair(_command())

    assert raised.value.code is expected_code
    fixture.passwords.hash_temporary_login_id_password.assert_not_called()
    _assert_no_changes(fixture, before)


def test_both_hashes_are_prepared_before_either_target_mutates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _service_fixture(monkeypatch)
    before = _snapshot(fixture)
    hashed: list[str] = []

    def hash_password(*, username: str) -> str:
        _assert_no_changes(fixture, before)
        assert fixture.require_operator.call_count == 2
        assert fixture.require_credential.call_count == 2
        hashed.append(username)
        return f"TEST_ONLY_new_hash_{username}"

    fixture.passwords.hash_temporary_login_id_password.side_effect = hash_password

    fixture.service.reset_approved_pair(_command())

    assert hashed == [fixture.operators[operator_id].username for operator_id in OPERATOR_IDS]


@pytest.mark.parametrize("failed_hash", [1, 2])
def test_hashing_failure_leaves_both_targets_unchanged(
    monkeypatch: pytest.MonkeyPatch, failed_hash: int
) -> None:
    fixture = _service_fixture(monkeypatch)
    before = _snapshot(fixture)
    hashed = 0

    def hash_password(*, username: str) -> str:
        nonlocal hashed
        hashed += 1
        if hashed == failed_hash:
            raise IdentityError(IdentityErrorCode.AUTH_PASSWORD_POLICY_FAILED, "hashing refused")
        return f"TEST_ONLY_new_hash_{username}"

    fixture.passwords.hash_temporary_login_id_password.side_effect = hash_password

    with pytest.raises(IdentityError) as raised:
        fixture.service.reset_approved_pair(_command())

    assert raised.value.code is IdentityErrorCode.AUTH_PASSWORD_POLICY_FAILED
    assert fixture.passwords.hash_temporary_login_id_password.call_count == failed_hash
    _assert_no_changes(fixture, before)


def test_pair_reset_rotates_both_credentials_revokes_sessions_and_audits_redacted_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _service_fixture(monkeypatch)

    results = fixture.service.reset_approved_pair(_command())

    assert tuple(result.operator_id for result in results) == OPERATOR_IDS
    fixture.authorizer.authorize.assert_called_once_with()
    fixture.transaction.assert_called_once_with(fixture.service.sessions)
    fixture.lock_invariants.assert_called_once_with(fixture.session)
    fixture.session.flush.assert_called_once_with()
    assert fixture.revoke.call_count == fixture.event.call_count == 2
    fixture.passwords.hash_temporary_login_id_password.assert_has_calls(
        [call(username=fixture.operators[operator_id].username) for operator_id in OPERATOR_IDS]
    )
    fixture.passwords.hash_password.assert_not_called()
    for index, (target, result) in enumerate(zip(TARGETS, results, strict=True)):
        operator = fixture.operators[target.operator_id]
        credential = fixture.credentials[target.operator_id]
        revoked_sessions = 3 if index == 0 else 1
        assert (
            result.resource_version == operator.lock_version == target.expected_resource_version + 1
        )
        assert result.password_version == credential.password_version == index + 3
        assert result.revoked_sessions == revoked_sessions
        assert result.reset_at == credential.password_changed_at == RESET_AT
        assert result.reset_at.tzinfo is UTC
        assert result.must_change_password is True
        assert operator.must_change_password is True
        assert credential.must_change_password is True
        assert credential.password_hash == f"TEST_ONLY_new_hash_{operator.username}"
        assert credential.password_algorithm == "argon2id"
        assert credential.failed_login_count == 0
        assert credential.first_failed_at is None
        assert credential.last_failed_at is None
        assert credential.locked_until is None
        assert operator.status == "ACTIVE"
        assert fixture.revoke.call_args_list[index] == call(
            fixture.session,
            target.operator_id,
            actor_id="system",
            reason="APPROVED_LOGIN_ID_PASSWORD_RESET",
            now=RESET_AT,
        )
        expected_payload = {
            "actor_type": "SYSTEM",
            "source": "CLI",
            "os_principal": "eom",
            "os_uid": 1000,
            "os_gid": 1000,
            "password_version": index + 3,
            "reason_code": "USER_APPROVED_TEMPORARY_LOGIN_ID_PAIR",
            "revoked_sessions": revoked_sessions,
            "must_change_password": True,
        }
        assert fixture.event.call_args_list[index] == call(
            fixture.session,
            operator,
            event_type="APPROVED_LOGIN_ID_PASSWORD_RESET",
            actor_id="system",
            request_id=REQUEST_ID,
            payload=expected_payload,
            now=RESET_AT,
        )
        redacted = repr((expected_payload, result))
        for value in fixture.operators.values():
            assert value.username not in redacted
        for value in fixture.credentials.values():
            assert value.password_hash not in redacted
        assert "TEST_ONLY_old_hash" not in redacted


def test_reset_replay_refuses_changed_versions_without_rehashing_or_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _service_fixture(monkeypatch)
    command = _command()
    fixture.service.reset_approved_pair(command)
    before_replay = _snapshot(fixture)
    fixture.passwords.reset_mock()
    fixture.revoke.reset_mock()
    fixture.event.reset_mock()
    fixture.session.reset_mock()

    with pytest.raises(IdentityError) as raised:
        fixture.service.reset_approved_pair(command)

    assert raised.value.code is IdentityErrorCode.OPERATOR_VERSION_CONFLICT
    fixture.passwords.hash_temporary_login_id_password.assert_not_called()
    _assert_no_changes(fixture, before_replay)


def test_locks_pair_in_deterministic_operator_id_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _service_fixture(monkeypatch)
    ordered = Mock()
    ordered.attach_mock(fixture.lock_invariants, "invariants")
    ordered.attach_mock(fixture.require_operator, "operator")
    ordered.attach_mock(fixture.require_credential, "credential")
    ordered.attach_mock(fixture.passwords.hash_temporary_login_id_password, "hash_password")

    results = fixture.service.reset_approved_pair(_command())

    assert ordered.mock_calls == [
        call.invariants(fixture.session),
        call.operator(fixture.session, OPERATOR_IDS[0], for_update=True),
        call.credential(fixture.session, OPERATOR_IDS[0], for_update=True),
        call.operator(fixture.session, OPERATOR_IDS[1], for_update=True),
        call.credential(fixture.session, OPERATOR_IDS[1], for_update=True),
        call.hash_password(username=fixture.operators[OPERATOR_IDS[0]].username),
        call.hash_password(username=fixture.operators[OPERATOR_IDS[1]].username),
    ]
    assert tuple(result.operator_id for result in results) == OPERATOR_IDS
