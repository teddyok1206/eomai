from __future__ import annotations

import hashlib
import os
import subprocess
from collections.abc import Sequence
from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from eom_api.services.mock_exam_production_coordinator import (
    MockExamProductionCoordinator,
    _advance_checkpoint,
)
from eom_api_contracts.mock_exam_execution import (
    MockExamGenerationBlockResolutionV1,
    MockExamProductionExecutionV1,
)
from eom_catalog_contracts import (
    build_integrated_science_mock_exam_production_plan,
    load_integrated_science_editorial_outline,
    load_integrated_science_mock_exam_layout_policy,
    load_integrated_science_mock_exam_policy,
)
from eom_operator_identity import ActorContext, ActorSource, ActorType
from eom_workflow import WorkflowRequest
from eom_workflow_runner.mock_exam_production_retirement import (
    MockExamProductionRetirementError,
    MockExamProductionRetirementService,
)
from eom_workflow_runner.repository import CommandType, workflow_request_storage_document
from eom_workflow_runner.retirement_quiescence import (
    WORKFLOW_RUNNER_DEPLOYMENT_HOLD_DIRECTORY,
    WORKFLOW_RUNNER_DEPLOYMENT_HOLD_PATH,
    WORKFLOW_RUNNER_DEPLOYMENT_HOLD_SHA256,
    WORKFLOW_RUNNER_FRAGMENT_PATH,
    WorkflowRunnerQuiescenceEvidence,
)
from eom_workflow_runner.systemd_retirement_quiescence import (
    SystemdWorkflowRunnerQuiescenceAdapter,
    WorkflowRunnerQuiescenceAdapterError,
)
from sqlalchemy import Engine, create_engine, event

NOW = datetime(2026, 9, 8, 10, 0, tzinfo=UTC)
OPERATOR_ID = "operator_" + "a" * 32


def _held_evidence(**changes: object) -> WorkflowRunnerQuiescenceEvidence:
    evidence = WorkflowRunnerQuiescenceEvidence(
        load_state="loaded",
        active_state="inactive",
        sub_state="dead",
        main_pid=0,
        unit_file_state="enabled",
        job="",
        fragment_path=WORKFLOW_RUNNER_FRAGMENT_PATH,
        drop_in_paths=(WORKFLOW_RUNNER_DEPLOYMENT_HOLD_PATH,),
        refuse_manual_start=True,
        need_daemon_reload=False,
        hold_directory_path=WORKFLOW_RUNNER_DEPLOYMENT_HOLD_DIRECTORY,
        hold_directory_owner_uid=0,
        hold_directory_group_gid=0,
        hold_directory_mode=0o755,
        hold_path=WORKFLOW_RUNNER_DEPLOYMENT_HOLD_PATH,
        hold_sha256=WORKFLOW_RUNNER_DEPLOYMENT_HOLD_SHA256,
        hold_owner_uid=0,
        hold_group_gid=0,
        hold_mode=0o644,
    )
    return replace(evidence, **changes)


class _ObservedUnit:
    def __init__(self, evidence: WorkflowRunnerQuiescenceEvidence | None = None) -> None:
        self._evidence = evidence or _held_evidence()

    def observe(self) -> WorkflowRunnerQuiescenceEvidence:
        return self._evidence


class _UnexpectedLeaseReconciliation:
    @staticmethod
    def reconcile_expired_for_workflows(
        workflow_ids: tuple[str, ...],
        *,
        observed_at: datetime,
    ) -> tuple[object, ...]:
        del workflow_ids, observed_at
        raise AssertionError("unsafe runner state must fail before lease reconciliation")


def _checkpoint() -> MockExamProductionExecutionV1:
    plan = build_integrated_science_mock_exam_production_plan(
        policy=load_integrated_science_mock_exam_policy(),
        layout_policy=load_integrated_science_mock_exam_layout_policy(),
        outline=load_integrated_science_editorial_outline(),
    )
    return MockExamProductionCoordinator.initialize(
        plan,
        production_request_id="productionreq_" + "b" * 32,
        operator_id=OPERATOR_ID,
        at=NOW,
    )


def _pinned_checkpoint() -> MockExamProductionExecutionV1:
    checkpoint = _checkpoint()
    plan = build_integrated_science_mock_exam_production_plan(
        policy=load_integrated_science_mock_exam_policy(),
        layout_policy=load_integrated_science_mock_exam_layout_policy(),
        outline=load_integrated_science_editorial_outline(),
    )
    block = plan.one_item_generation_block
    resolution = MockExamGenerationBlockResolutionV1(
        generation_block_key=block.block_key,
        generation_block_revision=block.block_revision,
        generation_block_sha256=block.block_sha256,
        workflow_definition_key=block.workflow_definition_key,
        workflow_definition_version=block.workflow_definition_version,
        workflow_definition_sha256="sha256:" + "1" * 64,
        content_pack_release_id="packrel_" + "2" * 32,
        content_pack_key=block.content_pack_key,
        content_pack_version=block.content_pack_version,
        content_pack_release_sha256="sha256:" + "3" * 64,
        content_pack_source_tree_sha256=block.content_pack_source_tree_sha256,
        execution_preset_id="execpreset_" + "4" * 32,
        execution_preset_revision_id="execpresetrev_" + "5" * 32,
        execution_preset_key=block.execution_preset_key,
        execution_preset_sha256="sha256:" + "6" * 64,
        resolved_at=NOW,
    )
    items = tuple(
        row.model_copy(
            update={
                "state": "WORKFLOW_ACTIVE",
                "start_command_id": "wfcmd_" + f"{row.position:032x}",
                "workflow_id": "workflow_" + f"{row.position:032x}",
                "workflow_resource_version": 1,
            }
        )
        for row in checkpoint.item_runs
    )
    advanced = _advance_checkpoint(
        checkpoint,
        at=NOW + timedelta(seconds=1),
        generation_block_resolution=resolution,
        item_runs=items,
    )
    return type(advanced).model_validate(advanced.model_dump(mode="json"))


def _stored_request(checkpoint: MockExamProductionExecutionV1, call_id: str) -> dict[str, Any]:
    request = WorkflowRequest.model_validate(
        {
            "request_name": "GENERATED_KNOWLEDGE_ITEM_REQUEST",
            "image_mode": "required",
            "content_pack": {
                "pack_key": "generated-knowledge-item",
                "environment": "development",
            },
            "profiles": {
                "authoring": "generated-knowledge-authoring",
                "review": "generated-knowledge-review",
                "image": "generated-stimulus-drawing",
                "registration": "generated-structured-registration",
            },
            "source_intake": {"batch_ids": []},
            "registry_intent": {"mode": "CREATE_ITEM"},
            "item_brief": {
                "subject": "통합과학",
                "topic": "생태계 평형",
                "task_type": "data_interpretation",
                "difficulty": "hard",
                "quality_profile": "deep",
                "original_request_sha256": "3" * 64,
            },
            "execution_preset_key": "knowledge-grounded-item",
            "educational_retrieval": {
                "corpus_key": "science-core",
                "query_kind": "ITEM_PREPARATION",
                "curriculum_root_key": "ecology.balance",
                "topic_keys": [],
                "required_item_elements": ["choice", "paragraph"],
                "source_classes": ["APPROVED_ITEM", "TEXTBOOK"],
            },
            "production_occurrence": {
                "production_request_id": checkpoint.production_request_id,
                "workflow_call_id": call_id,
            },
            "expected_resolution": {
                "workflow_definition_key": "generic-item-development",
                "workflow_definition_version": "1.8.0",
                "workflow_definition_sha256": "sha256:" + "4" * 64,
                "content_pack_release_id": "packrel_" + "5" * 32,
                "content_pack_key": "generated-knowledge-item",
                "content_pack_version": "1.13.0",
                "content_pack_bundle_sha256": "sha256:" + "6" * 64,
                "content_pack_source_tree_sha256": "sha256:" + "7" * 64,
                "execution_preset_id": "execpreset_" + "8" * 32,
                "execution_preset_revision_id": "execpresetrev_" + "9" * 32,
                "execution_preset_key": "knowledge-grounded-item",
                "execution_preset_content_sha256": "sha256:" + "a" * 64,
            },
        }
    )
    return workflow_request_storage_document(request)


def _actor() -> ActorContext:
    return ActorContext(
        actor_type=ActorType.OPERATOR,
        operator_id=OPERATOR_ID,
        session_id="apisession_" + "c" * 32,
        request_id="retirement-quiescence-test",
        authentication_time=NOW,
        permissions=frozenset(),
        source=ActorSource.CLI,
    )


@pytest.mark.parametrize(
    "changes",
    (
        {"active_state": "active", "sub_state": "running", "main_pid": 42},
        {"active_state": "activating", "sub_state": "start", "main_pid": 42},
        {"active_state": "deactivating", "sub_state": "stop-sigterm", "main_pid": 42},
        {"active_state": "failed", "sub_state": "failed"},
        {"load_state": "not-found"},
        {"main_pid": 9},
        {"unit_file_state": "masked-runtime"},
        {"job": "1234"},
        {"fragment_path": "/usr/lib/systemd/system/eom-workflow-runner.service"},
        {"drop_in_paths": ()},
        {"drop_in_paths": (WORKFLOW_RUNNER_DEPLOYMENT_HOLD_PATH, "/tmp/override.conf")},
        {"refuse_manual_start": False},
        {"need_daemon_reload": True},
        {"hold_directory_path": "/tmp/foreign.d"},
        {"hold_directory_owner_uid": 1000},
        {"hold_directory_group_gid": 1000},
        {"hold_directory_mode": 0o775},
        {"hold_path": "/tmp/foreign.conf"},
        {"hold_sha256": "sha256:" + "f" * 64},
        {"hold_owner_uid": 1000},
        {"hold_group_gid": 1000},
        {"hold_mode": 0o664},
    ),
)
def test_unsafe_unit_state_is_rejected_before_any_database_statement(
    changes: dict[str, object],
) -> None:
    engine: Engine = create_engine("sqlite+pysqlite:///:memory:")
    statements: list[str] = []

    @event.listens_for(engine, "before_cursor_execute")
    def record_statement(
        _connection: Any,
        _cursor: Any,
        statement: str,
        _parameters: Any,
        _context: Any,
        _executemany: bool,
    ) -> None:
        statements.append(statement)

    service = MockExamProductionRetirementService(
        engine,
        quiescence=_ObservedUnit(_held_evidence(**changes)),
        lease_reconciler=_UnexpectedLeaseReconciliation(),
    )
    try:
        with pytest.raises(MockExamProductionRetirementError) as raised:
            service.retire(_checkpoint(), _actor(), at=NOW)
        assert raised.value.code == "PRODUCTION_RETIREMENT_RUNNER_NOT_QUIESCENT"
        assert statements == []
    finally:
        engine.dispose()


def test_foreign_checkpoint_scope_fails_before_expired_lease_reconciliation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkpoint = _pinned_checkpoint()
    workflows = {
        row.workflow_id: SimpleNamespace(
            workflow_id=row.workflow_id,
            created_actor_type="human",
            created_actor_id=("operator_" + "f" * 32 if row.position == 1 else OPERATOR_ID),
            initial_request=_stored_request(checkpoint, row.workflow_call_id),
        )
        for row in checkpoint.item_runs
        if row.workflow_id is not None
    }
    starts = {
        row.start_command_id: SimpleNamespace(
            workflow_id=row.workflow_id,
            command_type=CommandType.START_WORKFLOW.value,
        )
        for row in checkpoint.item_runs
        if row.start_command_id is not None
    }
    session = SimpleNamespace(get=lambda _model, identity: starts.get(identity))
    lease_calls: list[tuple[str, ...]] = []
    lease_events: list[tuple[str, str]] = []

    class RecordingLeaseReconciler:
        @staticmethod
        def reconcile_expired_for_workflows(
            workflow_ids: tuple[str, ...],
            *,
            observed_at: datetime,
        ) -> tuple[object, ...]:
            del observed_at
            lease_calls.append(workflow_ids)
            lease_events.append(("ACTIVE", "RECONCILING"))
            return ()

    monkeypatch.setattr(
        "eom_workflow_runner.mock_exam_production_retirement._load_workflows",
        lambda _session, _workflow_ids, for_update: workflows,
    )
    monkeypatch.setattr(
        "eom_workflow_runner.mock_exam_production_retirement._reject_other_retirement",
        lambda _session, _workflow_ids, retirement_id: None,
    )
    engine: Engine = create_engine("sqlite+pysqlite:///:memory:")
    service = MockExamProductionRetirementService(
        engine,
        quiescence=_ObservedUnit(),
        lease_reconciler=RecordingLeaseReconciler(),
    )
    cast(Any, service)._sessions = lambda: nullcontext(session)
    try:
        with pytest.raises(MockExamProductionRetirementError) as raised:
            service.retire(checkpoint, _actor(), at=NOW + timedelta(minutes=1))
        assert raised.value.code == "PRODUCTION_RETIREMENT_OCCURRENCE_MISMATCH"
        assert lease_calls == []
        assert lease_events == []
    finally:
        engine.dispose()


def test_systemd_adapter_reads_exact_runner_hold_without_shell(tmp_path: Path) -> None:
    calls: list[tuple[Sequence[str], dict[str, Any]]] = []
    hold = tmp_path / "zzzz-eom-deployment-hold.conf"
    content = b"[Unit]\nRefuseManualStart=yes\nConditionPathExists=!/\n"
    hold.write_bytes(content)
    hold.chmod(0o644)

    def run(argv: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=(
                b"ActiveState=inactive\n"
                b"SubState=dead\n"
                b"MainPID=0\n"
                b"UnitFileState=enabled\n"
                b"Job=\n"
                b"LoadState=loaded\n"
                b"FragmentPath=/etc/systemd/system/eom-workflow-runner.service\n"
                + f"DropInPaths={hold}\n".encode()
                + b"RefuseManualStart=yes\n"
                b"NeedDaemonReload=no\n"
            ),
            stderr=b"",
        )

    evidence = SystemdWorkflowRunnerQuiescenceAdapter(
        command_runner=run,
        hold_path=hold,
    ).observe()

    assert evidence == WorkflowRunnerQuiescenceEvidence(
        load_state="loaded",
        active_state="inactive",
        sub_state="dead",
        main_pid=0,
        unit_file_state="enabled",
        job="",
        fragment_path=WORKFLOW_RUNNER_FRAGMENT_PATH,
        drop_in_paths=(str(hold),),
        refuse_manual_start=True,
        need_daemon_reload=False,
        hold_directory_path=str(hold.parent),
        hold_directory_owner_uid=hold.parent.stat().st_uid,
        hold_directory_group_gid=hold.parent.stat().st_gid,
        hold_directory_mode=hold.parent.stat().st_mode & 0o777,
        hold_path=str(hold),
        hold_sha256="sha256:" + hashlib.sha256(content).hexdigest(),
        hold_owner_uid=hold.stat().st_uid,
        hold_group_gid=hold.stat().st_gid,
        hold_mode=0o644,
    )
    assert calls[0][0][0] == "/usr/bin/systemctl"
    assert calls[0][0][1:3] == ("show", "eom-workflow-runner.service")
    assert calls[0][1]["stdin"] is subprocess.DEVNULL
    assert calls[0][1]["timeout"] == 5


def test_systemd_adapter_rejects_incomplete_or_noisy_evidence() -> None:
    def incomplete(argv: Sequence[str], **_: Any) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=b"ActiveState=inactive\nSubState=dead\nMainPID=0\nJob=\n",
            stderr=b"",
        )

    with pytest.raises(WorkflowRunnerQuiescenceAdapterError) as missing:
        SystemdWorkflowRunnerQuiescenceAdapter(command_runner=incomplete).observe()
    assert missing.value.code == "PRODUCTION_RETIREMENT_QUIESCENCE_INVALID"

    def noisy(argv: Sequence[str], **_: Any) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=(
                b"ActiveState=inactive\n"
                b"SubState=dead\n"
                b"MainPID=0\n"
                b"UnitFileState=enabled\n"
                b"Job=\n"
                b"LoadState=loaded\n"
                b"FragmentPath=/etc/systemd/system/eom-workflow-runner.service\n"
                b"DropInPaths=/etc/systemd/system/eom-workflow-runner.service.d/"
                b"zzzz-eom-deployment-hold.conf\n"
                b"RefuseManualStart=yes\n"
                b"NeedDaemonReload=no\n"
            ),
            stderr=b"warning",
        )

    with pytest.raises(WorkflowRunnerQuiescenceAdapterError) as unavailable:
        SystemdWorkflowRunnerQuiescenceAdapter(command_runner=noisy).observe()
    assert unavailable.value.code == "PRODUCTION_RETIREMENT_QUIESCENCE_UNAVAILABLE"


@pytest.mark.parametrize("tamper", ("symlink", "hardlink", "empty", "fifo", "oversized"))
def test_systemd_adapter_rejects_non_regular_or_unbounded_hold(
    tmp_path: Path,
    tamper: str,
) -> None:
    hold = tmp_path / "zzzz-eom-deployment-hold.conf"
    if tamper == "symlink":
        target = tmp_path / "foreign.conf"
        target.write_text("foreign", encoding="ascii")
        hold.symlink_to(target)
    elif tamper == "hardlink":
        hold.write_text("foreign", encoding="ascii")
        (tmp_path / "foreign.conf").hardlink_to(hold)
    elif tamper == "empty":
        hold.write_bytes(b"")
    elif tamper == "fifo":
        os.mkfifo(hold, mode=0o600)
    else:
        hold.write_bytes(b"x" * 4097)

    def valid(argv: Sequence[str], **_: Any) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=(
                b"ActiveState=inactive\n"
                b"SubState=dead\n"
                b"MainPID=0\n"
                b"UnitFileState=enabled\n"
                b"Job=\n"
                b"LoadState=loaded\n"
                b"FragmentPath=/etc/systemd/system/eom-workflow-runner.service\n"
                + f"DropInPaths={hold}\n".encode()
                + b"RefuseManualStart=yes\n"
                b"NeedDaemonReload=no\n"
            ),
            stderr=b"",
        )

    with pytest.raises(WorkflowRunnerQuiescenceAdapterError) as invalid:
        SystemdWorkflowRunnerQuiescenceAdapter(
            command_runner=valid,
            hold_path=hold,
        ).observe()
    assert invalid.value.code == "PRODUCTION_RETIREMENT_QUIESCENCE_INVALID"
