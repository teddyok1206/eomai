"""Creative execution resolution pins one source and a released isolated policy."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from eom_catalog_contracts import ExternalItemLearningWorkInput
from eom_identifiers import content_sha256
from eom_orchestrator.control_service import ControlPlaneError, compute_control_document_hash
from eom_orchestrator.execution_resolver import resolve_external_item_learning_plan
from eom_workflow.control_plane import ExecutionPresetRevision

from tests.unit.test_external_item_learning_execution_plan import _plan
from tests.unit.test_external_item_learning_work_contract import _work


def _published_preset() -> tuple[SimpleNamespace, SimpleNamespace]:
    step = _plan()["steps"][0]
    assert isinstance(step, dict)
    preset: dict[str, Any] = {
        "schema_version": "execution-preset-revision/1.0",
        "preset_id": "execpreset_" + "3" * 32,
        "preset_revision_id": "execpresetrev_" + "4" * 32,
        "revision_number": 1,
        "state": "RELEASED",
        "display_name": "Creative learning",
        "description": "One private support worker over pinned source pages.",
        "role_policies": [
            {
                "role": "support",
                "model_candidates": [
                    {"model": step["model"], "reasoning_effort": step["reasoning_effort"]}
                ],
                "instruction_bundle": step["instruction_bundle"],
                "reference_bundle": None,
                "worker_pool_key": "support",
                "timeout_seconds": 7200,
                "sandbox": "read-only",
                "network": "disabled",
            }
        ],
        "capacity_policy_revision_id": "capacityrev_" + "7" * 32,
        "general_knowledge_policy": "DENY",
        "compatible_workflow_protocols": ["workflow-role/1.33.0"],
        "content_sha256": "sha256:" + "0" * 64,
        "created_at": "2026-10-27T11:00:00Z",
    }
    preset["content_sha256"] = compute_control_document_hash(preset, "content_sha256")
    logical = SimpleNamespace(
        preset_id=preset["preset_id"],
        preset_key="external-item-learning",
        state="ACTIVE",
        current_revision_id=preset["preset_revision_id"],
    )
    revision = SimpleNamespace(
        preset_id=preset["preset_id"],
        state="RELEASED",
        content_sha256=preset["content_sha256"],
        compatible_workflow_protocols=preset["compatible_workflow_protocols"],
        canonical_document=preset,
    )
    return logical, revision


class _Session:
    def __init__(self, logical: SimpleNamespace, revision: SimpleNamespace) -> None:
        self.logical = logical
        self.revision = revision
        self.added: list[Any] = []
        self._scalar_calls = 0

    def scalar(self, statement: Any) -> Any:
        self._scalar_calls += 1
        if self._scalar_calls == 1:
            return None
        assert statement._for_update_arg is not None
        return self.logical

    def get(self, _model: Any, _identity: str) -> Any:
        return self.revision

    def add(self, value: Any) -> None:
        self.added.append(value)

    def flush(self) -> None:
        pass


def _resolve(session: Any, work: ExternalItemLearningWorkInput, **kwargs: Any) -> Any:
    return resolve_external_item_learning_plan(
        session,
        workflow_id="workflow_" + "2" * 32,
        workflow_definition_sha256="sha256:" + "6" * 64,
        workflow_role_schema_version="workflow-role/1.33.0",
        work=work,
        resolved_at=datetime(2026, 10, 27, 11, tzinfo=UTC),
        **kwargs,
    )


def test_creative_plan_resolution_pins_exact_work_and_released_policy() -> None:
    logical, revision = _published_preset()
    session = _Session(logical, revision)
    work = ExternalItemLearningWorkInput.model_validate(_work())

    plan = _resolve(session, work)

    assert plan.work_input == work
    assert plan.steps[0].worker_pool_key == "support"
    assert plan.preset_sha256 == revision.content_sha256
    assert len(session.added) == 2
    assert session.added[0].canonical_document == plan.model_dump(mode="json")

    class _ReplaySession:
        def scalar(self, _statement: Any) -> Any:
            return session.added[0]

    assert _resolve(_ReplaySession(), work) == plan

    changed = deepcopy(_work())
    changed["request_id"] = "extlearnreq_" + "0" * 32
    changed["request_sha256"] = content_sha256(
        {key: value for key, value in changed.items() if key != "request_sha256"}
    )
    with pytest.raises(ControlPlaneError) as conflict:
        _resolve(_ReplaySession(), ExternalItemLearningWorkInput.model_validate(changed))
    assert conflict.value.code == "CONTROL_PLAN_CONFLICT"


@pytest.mark.parametrize("field", ["preset_id", "preset_revision_id", "content_sha256"])
def test_creative_plan_never_substitutes_another_expected_preset(field):
    logical, revision = _published_preset()
    expected = ExecutionPresetRevision.model_validate(revision.canonical_document)
    prefix = (
        "sha256:"
        if field == "content_sha256"
        else "execpresetrev_"
        if field == "preset_revision_id"
        else "execpreset_"
    )
    wrong = expected.model_copy(
        update={field: prefix + "0" * (64 if field == "content_sha256" else 32)}
    )
    session = _Session(logical, revision)
    with pytest.raises(ControlPlaneError, match="preset changed"):
        _resolve(
            session, ExternalItemLearningWorkInput.model_validate(_work()), expected_preset=wrong
        )
    assert session.added == []


def test_creative_plan_rejects_nonprivate_support_policy() -> None:
    logical, revision = _published_preset()
    revision.canonical_document["role_policies"][0]["worker_pool_key"] = "legacy-extraction"
    revision.content_sha256 = compute_control_document_hash(
        revision.canonical_document, "content_sha256"
    )
    revision.canonical_document["content_sha256"] = revision.content_sha256
    with pytest.raises(ControlPlaneError) as invalid:
        _resolve(_Session(logical, revision), ExternalItemLearningWorkInput.model_validate(_work()))
    assert invalid.value.code == "CONTROL_PRESET_POLICY_INVALID"
