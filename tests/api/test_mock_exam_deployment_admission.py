from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from eom_api_contracts.mock_exam_execution import (
    MockExamProductionExecutionV1,
    MockExamProductionFailureV1,
    mock_exam_production_is_terminal,
)

from scripts.api.verify_mock_exam_deployment_admission import (
    DeploymentAdmissionError,
    inspect_checkpoint_root,
)


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
