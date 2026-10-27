"""Real control-owner persistence, using guarded disposable DB and synthetic text.

The authorization callback is a test port, not production user authentication.
No Codex, capability refresh, evaluation/release or Workflow command is run.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import Mock

import pytest
from eom_orchestrator.control_artifacts import ControlArtifactPublisher
from eom_orchestrator.control_models import (
    ExecutionPresetEvaluationRecord,
    ExecutionPresetRecord,
    ExecutionPresetRevisionRecord,
)
from eom_orchestrator.control_service import (
    ControlPlaneError,
    publish_capacity_policy_revision,
    record_capacity_policy_revision,
)
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.external_item_learning_controls import (
    prepare_external_item_learning_control_draft,
    publish_external_item_learning_instruction_bundle,
)
from eom_orchestrator.models import JobRecord, WorkerSlotRecord
from eom_orchestrator.repository import ensure_protocol_version
from eom_orchestrator.settings import Settings
from eom_workflow.control_plane import ModelCandidate
from eom_workflow.schemas import role_schema_bundle_hash
from sqlalchemy import Engine, func, select

from tests.unit.test_external_item_learning_controls import NOW, OPERATOR, _capacity

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


def test_instruction_replay_and_concurrent_draft_do_not_activate_or_run(
    creative_engine: Engine, tmp_path
):
    sessions = build_session_factory(creative_engine)
    nas = tmp_path / "artifacts"
    nas.mkdir()
    publisher = ControlArtifactPublisher(
        creative_engine, Settings(staging_root=tmp_path / "staging", nas_artifact_root=nas)
    )
    capacity = _capacity()
    with sessions.begin() as session:
        for pool in capacity.pools:
            for slot_key in pool.slot_keys:
                slot_id = slot_key.removeprefix("slot")
                if session.get(WorkerSlotRecord, slot_id) is None:
                    session.add(
                        WorkerSlotRecord(
                            slot_id=slot_id,
                            linux_user="synthetic-control-slot" + slot_id,
                            role=str(pool.roles[0]),
                            enabled=True,
                            gpu=slot_id == "03",
                        )
                    )
        session.flush()
        record_capacity_policy_revision(
            session,
            policy_key="fixed-host",
            document=capacity.model_dump(mode="json"),
            created_by=OPERATOR,
        )
        publish_capacity_policy_revision(
            session,
            capacity_policy_id=capacity.capacity_policy_id,
            capacity_policy_revision_id=capacity.capacity_policy_revision_id,
        )
        ensure_protocol_version(
            session, "workflow-role/1.33.0", role_schema_bundle_hash("workflow-role/1.33.0")
        )
    arguments = dict(
        platform_payload=b"# Synthetic isolated platform\n",
        role_payload=b"# Synthetic closed creative proposal\n",
        source_commit="a" * 40,
        operator_id=OPERATOR,
        created_at=NOW,
        authorize_control_change=Mock(),
    )
    pointer = publish_external_item_learning_instruction_bundle(sessions, publisher, **arguments)
    assert pointer == publish_external_item_learning_instruction_bundle(
        sessions, publisher, **arguments
    )
    with sessions() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(JobRecord)
                .where(JobRecord.idempotency_key.like("creative-instruction:%"))
            )
            == 3
        )
    barrier = Barrier(2)
    draft_arguments = dict(
        instruction=pointer,
        capacity_revision_id=capacity.capacity_policy_revision_id,
        candidate=ModelCandidate(model="synthetic-reviewed-model", reasoning_effort="high"),
        operator_id=OPERATOR,
        created_at=NOW,
        authorize_control_change=Mock(),
    )

    def prepare(_index):
        with sessions.begin() as session:
            barrier.wait(timeout=10)
            return prepare_external_item_learning_control_draft(session, **draft_arguments)

    with ThreadPoolExecutor(max_workers=2) as pool:
        drafts = tuple(pool.map(prepare, range(2)))
    assert drafts[0] == drafts[1] and drafts[0].state == "DRAFT"
    with sessions() as session:
        logical = session.get(ExecutionPresetRecord, drafts[0].preset_id)
        assert logical.current_revision_id is None
        assert (
            session.scalar(
                select(func.count())
                .select_from(ExecutionPresetRevisionRecord)
                .where(ExecutionPresetRevisionRecord.preset_id == logical.preset_id)
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(ExecutionPresetEvaluationRecord)
                .where(ExecutionPresetEvaluationRecord.preset_id == logical.preset_id)
            )
            == 0
        )
        original = session.get(ExecutionPresetRevisionRecord, drafts[0].preset_revision_id)
        original_document = original.canonical_document

    revoked = Mock(side_effect=[None, ValueError("synthetic authorization revoked")])
    with pytest.raises(ValueError), sessions.begin() as session:
        prepare_external_item_learning_control_draft(
            session, **{**draft_arguments, "authorize_control_change": revoked}
        )
    with pytest.raises(ControlPlaneError), sessions.begin() as session:
        prepare_external_item_learning_control_draft(
            session,
            **{
                **draft_arguments,
                "candidate": ModelCandidate(
                    model="different-synthetic-model", reasoning_effort="low"
                ),
            },
        )
    with sessions() as session:
        assert (
            session.get(
                ExecutionPresetRevisionRecord, drafts[0].preset_revision_id
            ).canonical_document
            == original_document
        )
        assert session.get(ExecutionPresetRecord, drafts[0].preset_id).current_revision_id is None
