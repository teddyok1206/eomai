"""Exact historical controls for explicit retry; synthetic metadata only."""

from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from typing import Any, cast

import pytest
from eom_identifiers import content_sha256
from eom_orchestrator import inference_transfer_resolution as owner
from eom_orchestrator.control_service import ControlPlaneError
from eom_workflow.inference_transfer_control import ResolvedExecutionPlanV22
from eom_workflow.inference_transfer_workflow import InferenceTransferWorkflowRequestV11
from sqlalchemy.orm import Session

from tests.unit.inference_transfer_fixtures import NOW
from tests.unit.test_inference_transfer_workflow_v11 import _plan, _workflow

CHILD_ID = "workflow_" + "f" * 32


class RetrySession:
    def __init__(self) -> None:
        self.existing: object | None = None
        self.protocol_available = True

    def get(self, _model: object, _identity: str) -> object | None:
        return object() if self.protocol_available else None

    def scalar(self, _query: object) -> object | None:
        return self.existing


def prepared(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    session = RetrySession()
    request = _workflow()
    parent = ResolvedExecutionPlanV22.model_validate(_plan())
    calls: list[tuple[str, object]] = []
    stored: list[ResolvedExecutionPlanV22] = []

    def read(_session: Session, **kwargs: Any) -> ResolvedExecutionPlanV22:
        calls.append(("parent_read", kwargs))
        assert kwargs["plan_id"] == parent.plan_id
        assert kwargs["workflow_id"] == parent.workflow_id
        assert kwargs["workflow_request"] == request
        return parent

    def pinned(_session: Session, plan: object) -> object:
        assert plan == parent
        calls.append(("pinned", plan))
        return object()

    def admit(_session: Session, **kwargs: Any) -> None:
        calls.append(("fresh_admission", kwargs["observed_at"]))

    monkeypatch.setattr(owner, "read_inference_transfer_execution_plan_v11", read)
    monkeypatch.setattr(owner, "_pinned_preset", pinned)
    monkeypatch.setattr(
        owner, "_single_policy", lambda _preset: SimpleNamespace(instruction_bundle=1)
    )
    monkeypatch.setattr(owner, "resolve_released_instruction_bundle", lambda *_a: object())
    monkeypatch.setattr(owner, "_admit_exact_controls", admit)
    monkeypatch.setattr(
        owner, "_record_validated_inference_transfer_plan", lambda _s, p: stored.append(p)
    )
    monkeypatch.setattr(
        owner, "_require_record_closure", lambda *_a: calls.append(("closure", None))
    )
    monkeypatch.setattr(
        owner,
        "lock_current_execution_preset",
        lambda *_a, **_k: pytest.fail("retry must never resolve latest controls"),
    )
    kwargs = {
        "parent_plan_id": parent.plan_id,
        "parent_workflow_id": parent.workflow_id,
        "parent_workflow_request": request,
        "workflow_id": CHILD_ID,
        "workflow_definition_sha256": parent.workflow_definition_sha256,
        "workflow_request": request,
        "core_prompt_sha256": parent.core_prompt_sha256,
        "prompt_sha256": parent.prompt_sha256,
        "resolved_at": NOW + timedelta(minutes=1),
    }
    return SimpleNamespace(
        session=session, request=request, parent=parent, calls=calls, stored=stored, kwargs=kwargs
    )


def resolve(value: SimpleNamespace, **changes: Any) -> ResolvedExecutionPlanV22:
    return owner.resolve_inference_transfer_retry_execution_plan_v11(
        cast(Session, value.session), **(value.kwargs | changes)
    )


def test_child_changes_only_execution_identity_time_and_preserves_parent_controls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = prepared(monkeypatch)
    before = value.parent.model_dump(mode="json")
    child = resolve(value)
    excluded = {"plan_id", "workflow_id", "resolved_at", "plan_sha256"}
    assert child.model_dump(mode="json", exclude=excluded) == value.parent.model_dump(
        mode="json", exclude=excluded
    )
    assert child.workflow_id == CHILD_ID and child.plan_id != value.parent.plan_id
    assert child.resolved_at == NOW + timedelta(minutes=1)
    assert child.plan_sha256 == content_sha256(
        child.model_dump(mode="json", exclude={"plan_sha256"})
    )
    assert value.parent.model_dump(mode="json") == before
    assert value.stored == [child]
    assert [name for name, _ in value.calls] == ["parent_read", "pinned", "fresh_admission"]


def test_new_permission_capture_is_provenance_not_changed_controls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = prepared(monkeypatch)
    body = value.request.model_dump(mode="json", exclude={"request_sha256"})
    body["requester_permissions_sha256"] = "sha256:" + "f" * 64
    child_request = InferenceTransferWorkflowRequestV11.model_validate(
        body | {"request_sha256": content_sha256(body)}
    )
    child = resolve(value, workflow_request=child_request)
    assert child.requester_permissions_sha256 == child_request.requester_permissions_sha256
    assert child.preset_revision_id == value.parent.preset_revision_id
    assert child.steps == value.parent.steps


def test_exact_existing_child_reuses_identity_time_and_rechecks_fresh_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = prepared(monkeypatch)
    first = resolve(value)
    value.session.existing = SimpleNamespace(canonical_document=first.model_dump(mode="json"))
    again = resolve(value, resolved_at=NOW + timedelta(hours=1))
    assert first == again
    assert len(value.stored) == 1
    assert ("fresh_admission", NOW + timedelta(hours=1)) in value.calls
    assert ("closure", None) in value.calls


@pytest.mark.parametrize(
    "field", ["preset_id", "preset_revision_id", "preset_sha256", "capacity_policy_revision_id"]
)
def test_rehashed_existing_child_cannot_change_parent_control_pins(
    monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    value = prepared(monkeypatch)
    first = resolve(value)
    body = first.model_dump(mode="json")
    old = body[field]
    body[field] = (
        old.split("_", 1)[0] + "_" + "a" * 32
        if not old.startswith("sha256:")
        else "sha256:" + "a" * 64
    )
    body["plan_sha256"] = content_sha256({k: v for k, v in body.items() if k != "plan_sha256"})
    value.session.existing = SimpleNamespace(canonical_document=body)
    monkeypatch.setattr(
        owner,
        "_require_record_closure",
        lambda _s, row, plan: (
            (_ for _ in ()).throw(
                ControlPlaneError("CONTROL_PLAN_CONFLICT", "different exact record")
            )
            if row.canonical_document != plan.model_dump(mode="json")
            else None
        ),
    )
    with pytest.raises(ControlPlaneError):
        resolve(value)
    assert len(value.stored) == 1


@pytest.mark.parametrize(
    "change",
    ["same_workflow", "changed_comparison", "changed_profile", "naive_time", "protocol_missing"],
)
def test_invalid_context_stops_before_any_child_plan_write(
    monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    value = prepared(monkeypatch)
    kwargs: dict[str, Any] = {}
    if change == "same_workflow":
        kwargs["workflow_id"] = value.parent.workflow_id
    elif change == "naive_time":
        kwargs["resolved_at"] = NOW.replace(tzinfo=None)
    elif change == "protocol_missing":
        value.session.protocol_available = False
    else:
        body = deepcopy(value.request.model_dump(mode="json", exclude={"request_sha256"}))
        if change == "changed_comparison":
            body["comparison"]["direction"] = "B_TO_A"
            nested = body["comparison"]
            nested["request_sha256"] = content_sha256(
                {k: v for k, v in nested.items() if k != "request_sha256"}
            )
        else:
            body["left_profile"]["profile_sha256"] = "sha256:" + "b" * 64
        kwargs["workflow_request"] = value.request.model_copy(update=body)
    with pytest.raises(ControlPlaneError):
        resolve(value, **kwargs)
    assert value.stored == []


def test_admission_failure_never_records_a_child_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    value = prepared(monkeypatch)

    def deny(*_args: Any, **_kwargs: Any) -> None:
        raise ControlPlaneError("CONTROL_PRESET_MODEL_UNAVAILABLE", "no fresh admitted slot")

    monkeypatch.setattr(owner, "_admit_exact_controls", deny)
    with pytest.raises(ControlPlaneError, match="no fresh"):
        resolve(value)
    assert value.stored == []
