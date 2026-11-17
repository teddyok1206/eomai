"""Use actual preset/capacity validators; fake SQL persistence is not live slot acceptance."""

from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from eom_orchestrator.control_models import (
    ExecutionPresetRecord,
    WorkerCapacityPolicyRevisionRecord,
)
from eom_orchestrator.control_service import ControlPlaneError, compute_control_document_hash
from eom_orchestrator.kakao_concept_plan_resolution import (
    resolve_kakao_concept_plan,
    validate_kakao_concept_execution_plan,
)
from eom_workflow.control_plane import ExecutionPresetRevision
from eom_workflow.kakao_concept_request import KakaoConceptWork
from eom_workflow.shared_worker_capacity import SharedWorkerCapacityPolicy

from tests.unit.test_external_item_learning_execution_resolver import _published_preset, _Session
from tests.unit.test_kakao_concept_workflow_contracts import work_value
from tests.unit.test_shared_worker_capacity import capacity_value


class Session(_Session):
    def __init__(self):
        logical, revision = _published_preset()
        logical.preset_key = "kakao-concepts"
        document = revision.canonical_document
        document["compatible_workflow_protocols"] = ["workflow-role/1.41.0"]
        capacity = SharedWorkerCapacityPolicy.model_validate(capacity_value()).model_dump(
            mode="json"
        )
        capacity["content_sha256"] = compute_control_document_hash(capacity, "content_sha256")
        document["capacity_policy_revision_id"] = capacity["capacity_policy_revision_id"]
        document["content_sha256"] = compute_control_document_hash(document, "content_sha256")
        revision.content_sha256 = document["content_sha256"]
        revision.compatible_workflow_protocols = document["compatible_workflow_protocols"]
        super().__init__(logical, revision)
        self.capacity = SimpleNamespace(**capacity, canonical_document=capacity)
        self.existing = None

    def get(self, model, identity):
        if model is WorkerCapacityPolicyRevisionRecord:
            return self.capacity
        return super().get(model, identity)

    def scalar(self, statement):
        if self.existing is not None:
            return self.existing
        self._scalar_calls += 1
        # This purpose uses the public read-only resolver; the other purpose's
        # fixture deliberately requires FOR UPDATE and remains unchanged.
        return (
            self.logical
            if statement.column_descriptions[0]["entity"] is ExecutionPresetRecord
            else None
        )


def resolve(session, **changes):
    values = dict(
        workflow_id="workflow_" + "2" * 32,
        workflow_definition_sha256="sha256:" + "6" * 64,
        workflow_role_schema_version="workflow-role/1.41.0",
        work=KakaoConceptWork.model_validate(work_value()),
        expected_preset=ExecutionPresetRevision.model_validate(session.revision.canonical_document),
        resolved_at=datetime(2026, 11, 17, tzinfo=UTC),
    )
    return resolve_kakao_concept_plan(session, **(values | changes))


def test_actual_published_preset_and_shared_capacity_produce_one_exact_phase_plan():
    session = Session()
    plan = resolve(session)
    assert (
        plan.steps[0].model
        == session.revision.canonical_document["role_policies"][0]["model_candidates"][0]["model"]
    )
    assert plan.steps[0].reasoning_effort == "xhigh"
    assert plan.steps[0].worker_pool_key == "support"
    assert len(session.added) == 2
    assert session.added[0].canonical_document == plan.model_dump(mode="json")
    assert session.added[1].step_key == "assist"
    assert session.added[1].model == plan.steps[0].model
    replay_session = Session()
    replay_session.existing = session.added[0]
    replay = resolve(replay_session)
    assert replay == plan and not replay_session.added
    assert replay_session._scalar_calls == 0  # No mutable current preset is substituted.


def test_source_owner_reads_without_preset_mutation_privilege_and_old_lock_is_preserved():
    from eom_orchestrator.execution_resolver import (
        lock_current_execution_preset,
        read_current_execution_preset,
    )
    from sqlalchemy.dialects import postgresql

    def query_for(resolver):
        session = Session()
        statements = []
        original = session.scalar

        def observed(statement):
            statements.append(str(statement.compile(dialect=postgresql.dialect())))
            return original(statement)

        session.scalar = observed
        value = resolver(
            session,
            preset_key="kakao-concepts",
            workflow_role_schema_version="workflow-role/1.41.0",
        )
        assert value == ExecutionPresetRevision.model_validate(session.revision.canonical_document)
        return statements[0]

    assert "FOR UPDATE" not in query_for(read_current_execution_preset)
    assert "FOR UPDATE" in query_for(lock_current_execution_preset)


@pytest.mark.parametrize(
    "change", ["old-policy", "missing-policy", "bad-policy-hash", "missing-support"]
)
def test_no_dedicated_slot_or_unverified_capacity_policy_is_silently_used(change):
    session = Session()
    if change == "old-policy":
        session.capacity.schema_version = "worker-capacity-policy/1.6"
    elif change == "missing-policy":
        session.capacity = None
    elif change == "bad-policy-hash":
        session.capacity.content_sha256 = "sha256:" + "0" * 64
    else:
        capacity = deepcopy(session.capacity.canonical_document)
        capacity["pools"] = [pool for pool in capacity["pools"] if pool["pool_key"] != "support"]
        capacity["content_sha256"] = compute_control_document_hash(capacity, "content_sha256")
        session.capacity = SimpleNamespace(**capacity, canonical_document=capacity)
    with pytest.raises(ControlPlaneError):
        resolve(session)
    assert not session.added


def test_wrong_role_protocol_cannot_select_a_previous_material_or_support_plan():
    session = Session()
    with pytest.raises(ControlPlaneError, match="concept protocol differs"):
        resolve(session, workflow_role_schema_version="workflow-role/1.40.0")
    assert not session.added


def test_preset_change_before_pin_is_explicit_and_does_not_create_partial_plan():
    session = Session()
    expected = ExecutionPresetRevision.model_validate(session.revision.canonical_document)
    document = session.revision.canonical_document
    document["description"] = "Changed after initial selection"
    document["content_sha256"] = compute_control_document_hash(document, "content_sha256")
    session.revision.content_sha256 = document["content_sha256"]
    with pytest.raises(ControlPlaneError, match="changed before pin"):
        resolve(session, expected_preset=expected)
    assert not session.added


@pytest.mark.parametrize(
    "field",
    [
        "workflow_id",
        "preset_revision_id",
        "plan_sha256",
        "graph_snapshot_revision_id",
        "evidence_bundle_revision_id",
    ],
)
def test_stored_plan_record_cannot_disagree_with_its_document(field):
    session = Session()
    plan = resolve(session)
    row = session.added[0]
    setattr(row, field, "other")
    with pytest.raises(ControlPlaneError, match="exact concept execution plan"):
        validate_kakao_concept_execution_plan(
            row, workflow_id=plan.workflow_id, step_key="assist", work=plan.work_input
        )


def test_changed_work_on_replay_does_not_reuse_a_stale_input():
    session = Session()
    resolve(session)
    session.existing = session.added[0]
    changed = work_value() | dict(phase="COMPOSE")
    with pytest.raises(ControlPlaneError, match="exact concept execution plan"):
        resolve(session, work=KakaoConceptWork.model_validate(changed))


def test_missing_source_authority_does_not_fall_back_to_another_support_prompt(monkeypatch):
    from contextlib import nullcontext
    from unittest.mock import Mock

    from eom_workflow.kakao_concept_request import KakaoConceptWorkerRequest
    from eom_workflow_runner import engine as engine_module
    from eom_workflow_runner.engine import PlatformRoleJobExecutor

    executor = object.__new__(PlatformRoleJobExecutor)
    executor.sessions = lambda: nullcontext(Mock())
    executor.orchestrator = Mock()
    executor.creative_page_publisher = Mock()
    executor.similarity_context_provider = None
    monkeypatch.setattr(
        engine_module,
        "prepare_kakao_concept_execution_context",
        Mock(side_effect=ControlPlaneError("SOURCE_NOT_ACCEPTED", "source not accepted")),
    )
    with pytest.raises(ControlPlaneError, match="source not accepted"):
        executor.execute(
            workflow=SimpleNamespace(workflow_id="workflow_" + "a" * 32),
            step=SimpleNamespace(worker_role="support", result_schema="kakao-concepts-result@1.0"),
            request=KakaoConceptWorkerRequest(work_input=work_value()),
            upstream=(),
            idempotency_key="synthetic-no-dispatch",
            prompt_text=None,
        )
    executor.orchestrator.submit_workflow_role.assert_not_called()
