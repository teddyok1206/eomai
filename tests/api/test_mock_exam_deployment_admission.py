from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from eom_api.services.mock_exam_production_coordinator import (
    MockExamProductionCoordinator,
    _advance_checkpoint,
)
from eom_api_contracts.mock_exam_execution import (
    MockExamGenerationBlockResolutionV2,
    MockExamProductionExecutionV1,
    MockExamProductionExecutionV2,
    MockExamProductionFailureV1,
    mock_exam_production_is_terminal,
)
from eom_catalog_contracts import (
    build_integrated_science_mock_exam_production_plan_v2,
    load_integrated_science_editorial_outline,
    load_integrated_science_mock_exam_layout_policy,
    load_integrated_science_mock_exam_policy,
)

from scripts.api.verify_mock_exam_deployment_admission import (
    DeploymentAdmissionError,
    _installed_contract_validator,
    inspect_checkpoint_root,
)

NOW = datetime(2026, 9, 8, 19, 0, tzinfo=UTC)


def _validator(payload: bytes) -> tuple[str, bool]:
    value = json.loads(payload)
    terminal = value["state"] == "COMPLETED" or (
        value["state"] == "BLOCKED" and value.get("retryable") is False
    )
    return value["execution_id"], terminal


def _write_checkpoint(
    root: Path,
    execution_id: str,
    state: str,
    *,
    retryable: bool | None = None,
) -> None:
    directory = root / execution_id
    directory.mkdir(mode=0o750)
    current = directory / "current.json"
    current.write_text(
        json.dumps({"execution_id": execution_id, "state": state, "retryable": retryable}),
        encoding="ascii",
    )
    current.chmod(0o640)


def _inspect(root: Path) -> int:
    return inspect_checkpoint_root(
        root,
        validator=_validator,
        expected_owner_uid=os.geteuid(),
        expected_owner_gid=os.getegid(),
    ).terminal_execution_count


def test_missing_or_terminal_checkpoint_root_admits_deployment(tmp_path: Path) -> None:
    root = tmp_path / "production"
    assert _inspect(root) == 0

    root.mkdir(mode=0o750)
    _write_checkpoint(root, "productionexec_" + "1" * 32, "COMPLETED")
    _write_checkpoint(
        root,
        "productionexec_" + "2" * 32,
        "BLOCKED",
        retryable=False,
    )

    assert _inspect(root) == 2


def test_nonterminal_checkpoint_refuses_deployment(tmp_path: Path) -> None:
    root = tmp_path / "production"
    root.mkdir(mode=0o750)
    _write_checkpoint(root, "productionexec_" + "1" * 32, "GRAPH_PUBLICATION")

    with pytest.raises(DeploymentAdmissionError, match="NONTERMINAL_EXECUTION_PRESENT"):
        _inspect(root)


def test_retryable_blocked_checkpoint_refuses_deployment(tmp_path: Path) -> None:
    root = tmp_path / "production"
    root.mkdir(mode=0o750)
    _write_checkpoint(
        root,
        "productionexec_" + "1" * 32,
        "BLOCKED",
        retryable=True,
    )

    with pytest.raises(DeploymentAdmissionError, match="NONTERMINAL_EXECUTION_PRESENT"):
        _inspect(root)


def test_contract_terminal_rule_distinguishes_retryable_blocked_execution() -> None:
    completed = MockExamProductionExecutionV1.model_construct(
        state="COMPLETED",
        failure=None,
        item_runs=(),
    )
    retryable = MockExamProductionExecutionV1.model_construct(
        state="BLOCKED",
        failure=MockExamProductionFailureV1.model_construct(retryable=True),
        item_runs=(),
    )
    final_failure = MockExamProductionExecutionV1.model_construct(
        state="BLOCKED",
        failure=MockExamProductionFailureV1.model_construct(retryable=False),
        item_runs=(),
    )

    assert mock_exam_production_is_terminal(completed)
    assert not mock_exam_production_is_terminal(retryable)
    assert mock_exam_production_is_terminal(final_failure)


def _initial_execution_v2() -> MockExamProductionExecutionV2:
    plan = build_integrated_science_mock_exam_production_plan_v2(
        policy=load_integrated_science_mock_exam_policy(),
        layout_policy=load_integrated_science_mock_exam_layout_policy(),
        outline=load_integrated_science_editorial_outline(),
    )
    initial = MockExamProductionCoordinator.initialize(
        plan,
        production_request_id="productionreq_" + "b" * 32,
        operator_id="operator_" + "a" * 32,
        at=NOW,
    )
    assert isinstance(initial, MockExamProductionExecutionV2)
    return initial


def _generation_resolution_v2() -> MockExamGenerationBlockResolutionV2:
    block = build_integrated_science_mock_exam_production_plan_v2(
        policy=load_integrated_science_mock_exam_policy(),
        layout_policy=load_integrated_science_mock_exam_layout_policy(),
        outline=load_integrated_science_editorial_outline(),
    ).one_item_generation_block
    return MockExamGenerationBlockResolutionV2(
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


def test_installed_contract_validator_dispatches_nonterminal_execution_v2() -> None:
    checkpoint = _initial_execution_v2()

    execution_id, terminal = _installed_contract_validator(
        checkpoint.model_dump_json().encode("utf-8")
    )

    assert execution_id == checkpoint.execution_id
    assert checkpoint.schema_version == "mock-exam-production-execution/2.0"
    assert terminal is False


def test_installed_contract_validator_dispatches_terminal_execution_v2() -> None:
    initial = _initial_execution_v2()
    failure = MockExamProductionFailureV1(
        stage="WORKFLOW_EXECUTION",
        category="WORKFLOW_EXECUTION_FAILED",
        code="WORKER_RESULT_INVALID",
        retryable=False,
        observed_at=NOW + timedelta(seconds=1),
    )
    failed = initial.item_runs[4].model_copy(
        update={
            "state": "FAILED",
            "start_command_id": "wfcmd_" + "1" * 32,
            "workflow_id": "workflow_" + "2" * 32,
            "workflow_resource_version": 1,
            "failure": failure,
        }
    )
    checkpoint = _advance_checkpoint(
        initial,
        at=NOW + timedelta(seconds=1),
        generation_block_resolution=_generation_resolution_v2(),
        item_runs=(*initial.item_runs[:4], failed, *initial.item_runs[5:]),
    )

    execution_id, terminal = _installed_contract_validator(
        checkpoint.model_dump_json().encode("utf-8")
    )

    assert execution_id == checkpoint.execution_id
    assert checkpoint.schema_version == "mock-exam-production-execution/2.0"
    assert terminal is True


def test_invalid_current_checkpoint_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "production"
    root.mkdir(mode=0o750)
    execution_id = "productionexec_" + "1" * 32
    directory = root / execution_id
    directory.mkdir(mode=0o750)
    current = directory / "current.json"
    current.write_text("{}", encoding="ascii")
    current.chmod(0o640)

    with pytest.raises(DeploymentAdmissionError, match="CHECKPOINT_CONTRACT_INVALID"):
        _inspect(root)


def test_execution_symlink_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "production"
    root.mkdir(mode=0o750)
    outside = tmp_path / "outside"
    outside.mkdir(mode=0o750)
    (root / ("productionexec_" + "1" * 32)).symlink_to(outside, target_is_directory=True)

    with pytest.raises(DeploymentAdmissionError, match="EXECUTION_DIRECTORY_INVALID"):
        _inspect(root)
