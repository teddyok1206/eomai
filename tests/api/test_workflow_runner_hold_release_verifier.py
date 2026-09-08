from __future__ import annotations

import fcntl
import json
import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from eom_api.services.mock_exam_production_coordinator import (
    MockExamProductionCoordinator,
    _advance_checkpoint,
)
from eom_api_contracts.mock_exam_execution import (
    MockExamGenerationBlockResolutionV1,
    MockExamProductionExecutionV2,
)
from eom_api_contracts.mock_exam_retirement import (
    MockExamProductionRetirementCommandV1,
    MockExamProductionRetirementOutcomeV1,
    MockExamProductionRetirementReceiptV1,
)
from eom_catalog_contracts import (
    build_integrated_science_mock_exam_production_plan,
    load_integrated_science_editorial_outline,
    load_integrated_science_mock_exam_layout_policy,
    load_integrated_science_mock_exam_policy,
)
from eom_identifiers import content_sha256

from scripts.api import verify_workflow_runner_hold_release as verifier

NOW = datetime(2026, 9, 8, 10, 0, tzinfo=UTC)
OPERATOR_ID = "operator_" + "a" * 32


def _checkpoint() -> MockExamProductionExecutionV2:
    plan = build_integrated_science_mock_exam_production_plan(
        policy=load_integrated_science_mock_exam_policy(),
        layout_policy=load_integrated_science_mock_exam_layout_policy(),
        outline=load_integrated_science_editorial_outline(),
    )
    checkpoint = MockExamProductionCoordinator.initialize(
        plan,
        production_request_id="productionreq_" + "b" * 32,
        operator_id=OPERATOR_ID,
        at=NOW,
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
    return MockExamProductionExecutionV2.model_validate(advanced.model_dump(mode="json"))


def _receipt(
    checkpoint: MockExamProductionExecutionV2,
) -> MockExamProductionRetirementReceiptV1:
    retired_at = NOW + timedelta(minutes=1)
    bindings = [
        {
            "position": row.position,
            "workflow_call_id": row.workflow_call_id,
            "workflow_id": row.workflow_id,
            "start_command_id": row.start_command_id,
            "expected_workflow_resource_version": row.position,
            "observed_workflow_state": "FAILED" if row.position == 25 else "REQUESTED",
        }
        for row in checkpoint.item_runs
    ]
    retirement_digest = content_sha256(
        {
            "schema_version": "mock-exam-production-retirement-identity/1.0",
            "execution_id": checkpoint.execution_id,
            "execution_revision_id": checkpoint.execution_revision_id,
            "checkpoint_sha256": checkpoint.checkpoint_sha256,
            "reason_code": "SUPERSEDED_BY_CORRECTED_PROTOCOL",
        }
    )
    retirement_id = "productionretire_" + retirement_digest.removeprefix("sha256:")[:32]
    command_body = {
        "schema_version": "mock-exam-production-retirement-command/1.0",
        "retirement_id": retirement_id,
        "execution_id": checkpoint.execution_id,
        "execution_revision_id": checkpoint.execution_revision_id,
        "checkpoint_sha256": checkpoint.checkpoint_sha256,
        "production_request_id": checkpoint.production_request_id,
        "production_plan_id": checkpoint.production_plan_id,
        "production_plan_sha256": checkpoint.production_plan_sha256,
        "operator_id": checkpoint.operator_id,
        "reason_code": "SUPERSEDED_BY_CORRECTED_PROTOCOL",
        "authorized_at": retired_at.isoformat().replace("+00:00", "Z"),
        "bindings": bindings,
    }
    command = MockExamProductionRetirementCommandV1.model_validate(
        {**command_body, "command_sha256": content_sha256(command_body)}
    )
    outcomes = tuple(
        MockExamProductionRetirementOutcomeV1(
            position=binding["position"],
            workflow_call_id=binding["workflow_call_id"],
            workflow_id=binding["workflow_id"],
            expected_workflow_resource_version=binding["expected_workflow_resource_version"],
            retirement_workflow_resource_version=(
                binding["expected_workflow_resource_version"] + 1
            ),
            retirement_event_sequence=binding["position"] + 1,
            prior_workflow_state=binding["observed_workflow_state"],
            disposition=(
                "UNSUCCESSFUL_TERMINAL_PRESERVED" if binding["position"] == 25 else "CANCEL_QUEUED"
            ),
            cancel_command_id=(
                None
                if binding["position"] == 25
                else "wfcmd_cancel_" + f"{binding['position']:032x}"
            ),
        )
        for binding in bindings
    )
    body = {
        "schema_version": "mock-exam-production-retirement-receipt/1.0",
        "retirement_id": command.retirement_id,
        "command_sha256": command.command_sha256,
        "execution_id": checkpoint.execution_id,
        "execution_revision_id": checkpoint.execution_revision_id,
        "checkpoint_sha256": checkpoint.checkpoint_sha256,
        "production_request_id": checkpoint.production_request_id,
        "production_plan_id": checkpoint.production_plan_id,
        "production_plan_sha256": checkpoint.production_plan_sha256,
        "operator_id": checkpoint.operator_id,
        "reason_code": "SUPERSEDED_BY_CORRECTED_PROTOCOL",
        "retired_at": retired_at.isoformat().replace("+00:00", "Z"),
        "outcomes": [outcome.model_dump(mode="json") for outcome in outcomes],
    }
    return MockExamProductionRetirementReceiptV1.model_validate(
        {**body, "receipt_sha256": content_sha256(body)}
    )


def _materialize(
    tmp_path: Path,
    checkpoint: MockExamProductionExecutionV2,
    receipt_document: dict[str, Any],
) -> tuple[Path, Path]:
    checkpoint_root = tmp_path / "checkpoints"
    checkpoint_root.mkdir(mode=0o700)
    lock = checkpoint_root / f".{checkpoint.execution_id}.lock"
    lock.touch(mode=0o600)
    lock.chmod(0o600)
    execution_root = checkpoint_root / checkpoint.execution_id
    execution_root.mkdir(mode=0o700)
    checkpoint_payload = checkpoint.model_dump_json(indent=2).encode() + b"\n"
    for name in ("current.json", f"{checkpoint.execution_revision_id}.json"):
        path = execution_root / name
        path.write_bytes(checkpoint_payload)
        path.chmod(0o600)
    receipt_root = tmp_path / "receipts"
    receipt_root.mkdir(mode=0o700)
    receipt_path = receipt_root / f"{checkpoint.execution_id}.retirement-receipt.json"
    receipt_path.write_text(
        json.dumps(receipt_document, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    receipt_path.chmod(0o600)
    return checkpoint_root, receipt_path


def _expected(
    checkpoint: MockExamProductionExecutionV2,
    receipt: MockExamProductionRetirementReceiptV1,
) -> verifier.ExpectedRetirementPins:
    return verifier.ExpectedRetirementPins(
        execution_id=checkpoint.execution_id,
        execution_revision_id=checkpoint.execution_revision_id,
        checkpoint_sha256=checkpoint.checkpoint_sha256,
        production_request_id=checkpoint.production_request_id,
        production_plan_id=checkpoint.production_plan_id,
        production_plan_sha256=checkpoint.production_plan_sha256,
        operator_id=checkpoint.operator_id,
        receipt_sha256=receipt.receipt_sha256,
    )


def _validate(
    monkeypatch: pytest.MonkeyPatch,
    checkpoint_root: Path,
    receipt_path: Path,
    expected: verifier.ExpectedRetirementPins,
) -> MockExamProductionRetirementReceiptV1:
    monkeypatch.setattr(verifier, "_require_installed_contract_packages", lambda: None)
    owner = verifier.FileOwner(uid=os.getuid(), gid=os.getgid())
    return verifier.validate_release_receipt(
        receipt_path=receipt_path,
        expected=expected,
        checkpoint_root=checkpoint_root,
        receipt_root=receipt_path.parent,
        receipt_owner=owner,
        checkpoint_owner=owner,
    )


def test_release_verifier_accepts_exact_envelope_checkpoint_and_24_to_1_fence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkpoint = _checkpoint()
    receipt = _receipt(checkpoint)
    checkpoint_root, receipt_path = _materialize(
        tmp_path,
        checkpoint,
        {"status": "SUCCEEDED", "data": receipt.model_dump(mode="json")},
    )

    verified = _validate(
        monkeypatch,
        checkpoint_root,
        receipt_path,
        _expected(checkpoint, receipt),
    )

    assert verified == receipt


def test_release_verifier_rejects_cancel_queued_from_terminal_workflow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkpoint = _checkpoint()
    receipt = _receipt(checkpoint)
    document = {"status": "SUCCEEDED", "data": receipt.model_dump(mode="json")}
    cancelled = document["data"]["outcomes"][0]
    cancelled["prior_workflow_state"] = "FAILED"
    bindings = [
        {
            "position": outcome["position"],
            "workflow_call_id": outcome["workflow_call_id"],
            "workflow_id": outcome["workflow_id"],
            "start_command_id": checkpoint.item_runs[outcome["position"] - 1].start_command_id,
            "expected_workflow_resource_version": outcome["expected_workflow_resource_version"],
            "observed_workflow_state": outcome["prior_workflow_state"],
        }
        for outcome in document["data"]["outcomes"]
    ]
    command_body = {
        "schema_version": "mock-exam-production-retirement-command/1.0",
        "retirement_id": document["data"]["retirement_id"],
        "execution_id": checkpoint.execution_id,
        "execution_revision_id": checkpoint.execution_revision_id,
        "checkpoint_sha256": checkpoint.checkpoint_sha256,
        "production_request_id": checkpoint.production_request_id,
        "production_plan_id": checkpoint.production_plan_id,
        "production_plan_sha256": checkpoint.production_plan_sha256,
        "operator_id": checkpoint.operator_id,
        "reason_code": "SUPERSEDED_BY_CORRECTED_PROTOCOL",
        "authorized_at": document["data"]["retired_at"],
        "bindings": bindings,
    }
    document["data"]["command_sha256"] = content_sha256(command_body)
    receipt_body = {
        key: value for key, value in document["data"].items() if key != "receipt_sha256"
    }
    document["data"]["receipt_sha256"] = content_sha256(receipt_body)
    expected = replace(
        _expected(checkpoint, receipt),
        receipt_sha256=document["data"]["receipt_sha256"],
    )
    checkpoint_root, receipt_path = _materialize(tmp_path, checkpoint, document)

    with pytest.raises(verifier.HoldReleaseReceiptError):
        _validate(monkeypatch, checkpoint_root, receipt_path, expected)


@pytest.mark.parametrize("tamper", ("expected_pin", "extra_envelope", "aggregate", "command"))
def test_release_verifier_rejects_pin_envelope_aggregate_and_command_tamper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tamper: str,
) -> None:
    checkpoint = _checkpoint()
    receipt = _receipt(checkpoint)
    document = {"status": "SUCCEEDED", "data": receipt.model_dump(mode="json")}
    expected = _expected(checkpoint, receipt)
    if tamper == "expected_pin":
        expected = replace(expected, receipt_sha256="sha256:" + "f" * 64)
    elif tamper == "extra_envelope":
        document["unexpected"] = True
    elif tamper == "aggregate":
        outcome = document["data"]["outcomes"][23]
        outcome["prior_workflow_state"] = "FAILED"
        outcome["disposition"] = "UNSUCCESSFUL_TERMINAL_PRESERVED"
        outcome["cancel_command_id"] = None
        body = {key: value for key, value in document["data"].items() if key != "receipt_sha256"}
        document["data"]["receipt_sha256"] = content_sha256(body)
        expected = replace(expected, receipt_sha256=document["data"]["receipt_sha256"])
    elif tamper == "command":
        document["data"]["command_sha256"] = "sha256:" + "f" * 64
        body = {key: value for key, value in document["data"].items() if key != "receipt_sha256"}
        document["data"]["receipt_sha256"] = content_sha256(body)
        expected = replace(expected, receipt_sha256=document["data"]["receipt_sha256"])
    checkpoint_root, receipt_path = _materialize(tmp_path, checkpoint, document)

    with pytest.raises(verifier.HoldReleaseReceiptError):
        _validate(monkeypatch, checkpoint_root, receipt_path, expected)


@pytest.mark.parametrize("tamper", ("mode", "symlink", "hardlink", "immutable"))
def test_release_verifier_rejects_unsafe_or_stale_materialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tamper: str,
) -> None:
    checkpoint = _checkpoint()
    receipt = _receipt(checkpoint)
    checkpoint_root, receipt_path = _materialize(
        tmp_path,
        checkpoint,
        {"status": "SUCCEEDED", "data": receipt.model_dump(mode="json")},
    )
    if tamper == "mode":
        receipt_path.chmod(0o640)
    elif tamper == "symlink":
        target = receipt_path.with_suffix(".foreign")
        receipt_path.replace(target)
        receipt_path.symlink_to(target)
    elif tamper == "hardlink":
        os.link(receipt_path, receipt_path.with_suffix(".foreign"))
    else:
        immutable = (
            checkpoint_root / checkpoint.execution_id / f"{checkpoint.execution_revision_id}.json"
        )
        immutable.write_text("{}\n", encoding="ascii")
        immutable.chmod(0o600)

    hold_sentinel = tmp_path / "deployment-hold.conf"
    hold_sentinel.write_bytes(b"[Unit]\nRefuseManualStart=yes\nConditionPathExists=!/\n")
    before = hold_sentinel.stat()

    with pytest.raises(verifier.HoldReleaseReceiptError):
        _validate(
            monkeypatch,
            checkpoint_root,
            receipt_path,
            _expected(checkpoint, receipt),
        )
    after = hold_sentinel.stat()
    assert hold_sentinel.read_bytes() == (
        b"[Unit]\nRefuseManualStart=yes\nConditionPathExists=!/\n"
    )
    assert (after.st_dev, after.st_ino, after.st_mtime_ns) == (
        before.st_dev,
        before.st_ino,
        before.st_mtime_ns,
    )


@pytest.mark.parametrize(
    "payload",
    (
        b"{",
        b'{"status":"FAILED","data":{}}\n',
        b'{"status":"SUCCEEDED","status":"SUCCEEDED","data":{}}\n',
    ),
)
def test_release_verifier_rejects_malformed_failed_or_duplicate_key_envelope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    payload: bytes,
) -> None:
    checkpoint = _checkpoint()
    receipt = _receipt(checkpoint)
    checkpoint_root, receipt_path = _materialize(
        tmp_path,
        checkpoint,
        {"status": "SUCCEEDED", "data": receipt.model_dump(mode="json")},
    )
    receipt_path.write_bytes(payload)
    receipt_path.chmod(0o600)

    with pytest.raises(verifier.HoldReleaseReceiptError):
        _validate(
            monkeypatch,
            checkpoint_root,
            receipt_path,
            _expected(checkpoint, receipt),
        )


@pytest.mark.parametrize("tamper", ("zero", "oversize", "fifo", "wrong_path", "wrong_owner"))
def test_release_verifier_rejects_non_regular_bounded_path_or_owner_violation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tamper: str,
) -> None:
    checkpoint = _checkpoint()
    receipt = _receipt(checkpoint)
    checkpoint_root, receipt_path = _materialize(
        tmp_path,
        checkpoint,
        {"status": "SUCCEEDED", "data": receipt.model_dump(mode="json")},
    )
    owner = verifier.FileOwner(uid=os.getuid(), gid=os.getgid())
    supplied_path = receipt_path
    supplied_owner = owner
    if tamper == "zero":
        receipt_path.write_bytes(b"")
    elif tamper == "oversize":
        receipt_path.write_bytes(b"x" * (1024 * 1024 + 1))
    elif tamper == "fifo":
        receipt_path.unlink()
        os.mkfifo(receipt_path, mode=0o600)
    elif tamper == "wrong_path":
        supplied_path = receipt_path.with_name("foreign.retirement-receipt.json")
    else:
        supplied_owner = verifier.FileOwner(uid=os.getuid() + 1, gid=os.getgid())

    monkeypatch.setattr(verifier, "_require_installed_contract_packages", lambda: None)
    with pytest.raises(verifier.HoldReleaseReceiptError):
        verifier.validate_release_receipt(
            receipt_path=supplied_path,
            expected=_expected(checkpoint, receipt),
            checkpoint_root=checkpoint_root,
            receipt_root=receipt_path.parent,
            receipt_owner=supplied_owner,
            checkpoint_owner=owner,
        )


def test_release_verifier_rejects_exact_execution_cohort_pointer_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkpoint = _checkpoint()
    receipt = _receipt(checkpoint)
    document = {"status": "SUCCEEDED", "data": receipt.model_dump(mode="json")}
    document["data"]["outcomes"][0]["workflow_id"] = "workflow_" + "e" * 32
    body = {key: value for key, value in document["data"].items() if key != "receipt_sha256"}
    document["data"]["receipt_sha256"] = content_sha256(body)
    expected = replace(
        _expected(checkpoint, receipt),
        receipt_sha256=document["data"]["receipt_sha256"],
    )
    checkpoint_root, receipt_path = _materialize(tmp_path, checkpoint, document)

    with pytest.raises(verifier.HoldReleaseReceiptError):
        _validate(monkeypatch, checkpoint_root, receipt_path, expected)

    wrong_execution = replace(expected, execution_id="productionexec_" + "f" * 32)
    with pytest.raises(verifier.HoldReleaseReceiptError):
        _validate(monkeypatch, checkpoint_root, receipt_path, wrong_execution)


def test_release_verifier_rejects_concurrent_checkpoint_writer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkpoint = _checkpoint()
    receipt = _receipt(checkpoint)
    checkpoint_root, receipt_path = _materialize(
        tmp_path,
        checkpoint,
        {"status": "SUCCEEDED", "data": receipt.model_dump(mode="json")},
    )
    lock_path = checkpoint_root / f".{checkpoint.execution_id}.lock"
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CLOEXEC)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(verifier.HoldReleaseReceiptError):
            _validate(
                monkeypatch,
                checkpoint_root,
                receipt_path,
                _expected(checkpoint, receipt),
            )
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def test_release_verifier_holds_exclusive_checkpoint_lock_through_release_handshake(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkpoint = _checkpoint()
    receipt = _receipt(checkpoint)
    checkpoint_root, receipt_path = _materialize(
        tmp_path,
        checkpoint,
        {"status": "SUCCEEDED", "data": receipt.model_dump(mode="json")},
    )
    owner = verifier.FileOwner(uid=os.getuid(), gid=os.getgid())
    monkeypatch.setattr(verifier, "_require_installed_contract_packages", lambda: None)
    lock_path = checkpoint_root / f".{checkpoint.execution_id}.lock"

    with verifier._validated_release_receipt_lock(
        receipt_path=receipt_path,
        expected=_expected(checkpoint, receipt),
        checkpoint_root=checkpoint_root,
        receipt_root=receipt_path.parent,
        receipt_owner=owner,
        checkpoint_owner=owner,
    ):
        contender = os.open(lock_path, os.O_RDWR | os.O_CLOEXEC)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(contender)

    contender = os.open(lock_path, os.O_RDWR | os.O_CLOEXEC)
    try:
        fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        fcntl.flock(contender, fcntl.LOCK_UN)
        os.close(contender)
