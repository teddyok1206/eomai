from __future__ import annotations

from dataclasses import dataclass

import pytest
from eom_api_contracts.workflows import WorkflowActionRequest
from eom_operator_identity import OperatorStatus, PermissionKey, RoleKey
from eom_workflow_runner.actor_authorization import (
    CompositeWorkflowActorAuthorizer,
    WorkflowActorAuthorizationReadiness,
    WorkflowActorDenialReason,
    WorkflowActorNamespace,
)
from eom_workflow_runner.actor_authorization_adapters import (
    OperatorActorSnapshot,
    OperatorIdentityWorkflowActorAuthorizer,
    StaticWorkflowActorAuthorizer,
)
from eom_workflow_runner.engine import WorkflowRunner
from eom_workflow_runner.errors import WorkflowError, WorkflowErrorCode
from eom_workflow_runner.settings import HumanActor, HumanActorConfig
from pydantic import ValidationError

OPERATOR_ID = "operator_" + "a" * 32


@dataclass
class FakeOperatorSource:
    snapshot: OperatorActorSnapshot | None
    available: bool = True

    def load(self, operator_id: str) -> OperatorActorSnapshot | None:
        if not self.available:
            raise RuntimeError("identity unavailable")
        if self.snapshot is None or self.snapshot.operator_id != operator_id:
            return None
        return self.snapshot

    def readiness(self) -> WorkflowActorAuthorizationReadiness:
        return WorkflowActorAuthorizationReadiness(
            ready=self.available,
            code="READY" if self.available else "WORKFLOW_ACTOR_IDENTITY_UNAVAILABLE",
            detail="test identity source",
        )


def _snapshot(
    *,
    status: OperatorStatus = OperatorStatus.ACTIVE,
    roles: frozenset[RoleKey] = frozenset({RoleKey.REVIEWER}),
    permissions: frozenset[PermissionKey] = frozenset(
        {
            PermissionKey.WORKFLOW_APPROVE,
            PermissionKey.WORKFLOW_REQUEST_REWORK,
        }
    ),
) -> OperatorActorSnapshot:
    return OperatorActorSnapshot(OPERATOR_ID, status, roles, permissions)


def _static(*actors: HumanActor) -> StaticWorkflowActorAuthorizer:
    return StaticWorkflowActorAuthorizer(HumanActorConfig(version=1, actors=actors))


def test_active_reviewer_operator_is_authorized_with_canonical_identity() -> None:
    authorizer = OperatorIdentityWorkflowActorAuthorizer(FakeOperatorSource(_snapshot()))

    result = authorizer.authorize(OPERATOR_ID, PermissionKey.WORKFLOW_APPROVE)

    assert result.authorized
    assert result.canonical_actor_id == OPERATOR_ID
    assert result.namespace is WorkflowActorNamespace.OPERATOR_IDENTITY
    assert result.workflow_roles == frozenset({"reviewer"})
    assert PermissionKey.WORKFLOW_APPROVE in result.capabilities


def test_disabled_and_permission_revoked_operators_are_denied_at_processing_time() -> None:
    disabled = OperatorIdentityWorkflowActorAuthorizer(
        FakeOperatorSource(_snapshot(status=OperatorStatus.DISABLED))
    ).authorize(OPERATOR_ID, PermissionKey.WORKFLOW_APPROVE)
    revoked = OperatorIdentityWorkflowActorAuthorizer(
        FakeOperatorSource(_snapshot(permissions=frozenset()))
    ).authorize(OPERATOR_ID, PermissionKey.WORKFLOW_APPROVE)

    assert not disabled.authorized
    assert disabled.denial_reason is WorkflowActorDenialReason.ACTOR_DISABLED
    assert not revoked.authorized
    assert revoked.denial_reason is WorkflowActorDenialReason.PERMISSION_ABSENT


def test_unknown_malformed_and_backend_unavailable_operator_reasons_are_distinct() -> None:
    unknown = OperatorIdentityWorkflowActorAuthorizer(FakeOperatorSource(None)).authorize(
        OPERATOR_ID, PermissionKey.WORKFLOW_APPROVE
    )
    malformed = OperatorIdentityWorkflowActorAuthorizer(FakeOperatorSource(None)).authorize(
        "operator_not-canonical", PermissionKey.WORKFLOW_APPROVE
    )
    unavailable = OperatorIdentityWorkflowActorAuthorizer(
        FakeOperatorSource(None, available=False)
    ).authorize(OPERATOR_ID, PermissionKey.WORKFLOW_APPROVE)

    assert unknown.denial_reason is WorkflowActorDenialReason.ACTOR_UNKNOWN
    assert malformed.denial_reason is WorkflowActorDenialReason.ACTOR_MALFORMED
    assert unavailable.denial_reason is WorkflowActorDenialReason.IDENTITY_BACKEND_UNAVAILABLE


def test_static_reviewer_compatibility_and_requester_denial() -> None:
    authorizer = _static(
        HumanActor(actor_id="reviewer_01", role="reviewer", enabled=True),
        HumanActor(actor_id="requester_01", role="requester", enabled=True),
    )

    reviewer = authorizer.authorize("reviewer_01", PermissionKey.WORKFLOW_APPROVE)
    requester = authorizer.authorize("requester_01", PermissionKey.WORKFLOW_APPROVE)

    assert reviewer.authorized and reviewer.workflow_roles == frozenset({"reviewer"})
    assert not requester.authorized
    assert requester.denial_reason is WorkflowActorDenialReason.PERMISSION_ABSENT
    username_like = authorizer.authorize("review01", PermissionKey.WORKFLOW_APPROVE)
    assert not username_like.authorized
    assert username_like.denial_reason is WorkflowActorDenialReason.ACTOR_UNKNOWN


def test_composite_never_falls_back_from_operator_namespace_to_static_alias() -> None:
    static = _static(HumanActor(actor_id=OPERATOR_ID, role="reviewer", enabled=True))
    composite = CompositeWorkflowActorAuthorizer(
        operator=OperatorIdentityWorkflowActorAuthorizer(FakeOperatorSource(None)),
        static=static,
    )

    result = composite.authorize(OPERATOR_ID, PermissionKey.WORKFLOW_APPROVE)

    assert not result.authorized
    assert result.namespace is WorkflowActorNamespace.OPERATOR_IDENTITY
    assert result.denial_reason is WorkflowActorDenialReason.ACTOR_UNKNOWN


def test_action_specific_permissions_are_not_interchangeable() -> None:
    authorizer = OperatorIdentityWorkflowActorAuthorizer(FakeOperatorSource(_snapshot()))

    assert authorizer.authorize(OPERATOR_ID, PermissionKey.WORKFLOW_APPROVE).authorized
    assert not authorizer.authorize(OPERATOR_ID, PermissionKey.WORKFLOW_CANCEL).authorized


def test_api_role_strings_are_not_part_of_the_workflow_action_contract() -> None:
    with pytest.raises(ValidationError):
        WorkflowActionRequest.model_validate({"role": "REVIEWER"})


def test_runner_maps_denial_and_identity_backend_failure_separately() -> None:
    denied_runner = object.__new__(WorkflowRunner)
    denied_runner.actor_authorizer = OperatorIdentityWorkflowActorAuthorizer(
        FakeOperatorSource(_snapshot(permissions=frozenset()))
    )
    with pytest.raises(WorkflowError) as denied:
        denied_runner._authorize_actor(OPERATOR_ID, PermissionKey.WORKFLOW_APPROVE)
    assert denied.value.code is WorkflowErrorCode.APPROVAL_UNAUTHORIZED

    unavailable_runner = object.__new__(WorkflowRunner)
    unavailable_runner.actor_authorizer = OperatorIdentityWorkflowActorAuthorizer(
        FakeOperatorSource(None, available=False)
    )
    with pytest.raises(WorkflowError) as unavailable:
        unavailable_runner._authorize_actor(OPERATOR_ID, PermissionKey.WORKFLOW_APPROVE)
    assert unavailable.value.code is WorkflowErrorCode.ACTOR_AUTHORIZATION_UNAVAILABLE
