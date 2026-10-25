"""Concrete distinct outcome reader; only root/files/systemd leaves are synthetic."""

import os
import tempfile
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.embedding_gpu_control import embedding_gpu_control_bytes
from eom_catalog_service import embedding_retired_failure_read as application
from eom_catalog_service.embedding_gpu_batch_launch import native_embedding_gpu_batch_environment
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator.worker_systemd import FixedUnitStatus
from eom_workflow.embedding_unpublished_recovery import RetiredUnpublishedEmbeddingResult
from pydantic import TypeAdapter

from tests.unit.test_embedding_gpu_batch_controller import driver as driver
from tests.unit.test_embedding_gpu_batch_controller import machine as machine


@pytest.fixture
def original(driver, monkeypatch):
    retired = driver.retired
    assert retired.original_terminal.original_outcome == "SUCCEEDED"
    raw = canonical_json_bytes(
        dict(
            event="EMBEDDING_GPU_BATCH_RETIRED_NOT_PUBLISHED",
            observation=TypeAdapter(type(retired)).dump_python(retired, mode="json"),
        )
    )
    proof = RetiredUnpublishedEmbeddingResult(
        allocation_attempt_id=driver.ready.readiness.allocation_attempt_id,
        invocation_id=driver.ready.unit.invocation_id,
        retirement_sha256=sha256_bytes(raw),
        retired_at=retired.observed_at_utc,
        parent_plan_job_id="job_" + "e" * 32,
        parent_request_sha256="sha256:" + "f" * 64,
        original_outcome="SUCCEEDED",
        stored_descriptors=0,
        controller_invocation_id="c" * 32,
        controller_outcome="FAILED",
    )
    controller = replace(
        retired.original_terminal.terminal_unit,
        invocation_id="c" * 32,
        fragment_path="/etc/systemd/system/eom-embedding-native-gpu-batch-owner@.service",
        drop_in_paths="",
        status=FixedUnitStatus("loaded", "failed", "failed", "exit-code", 1, 1, 100, False),
    )
    launch = driver.captured.prepared.launch
    files = Mock(spec=application.NumericalRuntimeFileSnapshots)
    files.read.return_value = raw
    files.observe_protected_member_bytes.side_effect = lambda path, **_kw: SimpleNamespace(
        raw={
            "launch.env": native_embedding_gpu_batch_environment(launch),
            "allocation.json": embedding_gpu_control_bytes(driver.captured.prepared.request),
        }[path.name]
    )
    monkeypatch.setattr(application, "NumericalRuntimeFileSnapshots", lambda: files)
    stopped = Mock(return_value=retired.retired_unit)
    monkeypatch.setattr(application, "observe_stopped_gpu_unit", stopped)
    control = Mock(return_value=controller)
    monkeypatch.setattr(application, "inspect_cpu_unit", control)
    metadata = Mock(return_value=(launch.root_pid, 0))
    monkeypatch.setattr(application, "observe_failed_gpu_unit_metadata", metadata)
    processes = Mock(return_value=())
    monkeypatch.setattr(application, "root_owned_unit_processes", processes)
    monkeypatch.setattr(application.os, "getresuid", lambda: (0, 0, 0))
    return SimpleNamespace(
        proof=proof,
        retired=retired,
        files=files,
        controller=controller,
        control=control,
        metadata=metadata,
        processes=processes,
        launch=launch,
        raw=raw,
        stopped=stopped,
    )


def test_successful_numeric_and_failed_original_controller_are_both_verified(original):
    with application.read_retired_embedding_failure(original.proof) as resolved:
        assert resolved.proof.original_outcome == "SUCCEEDED"
        assert resolved.proof.controller_outcome == "FAILED"
    assert original.control.call_count == original.metadata.call_count == 2
    original.files.assert_unchanged.assert_called_once()
    assert original.files.observe_protected_member_bytes.call_count == 2
    assert original.retired.original_terminal.original_outcome == "SUCCEEDED"


@pytest.mark.parametrize(
    "fault",
    [
        "numeric_failed",
        "controller_succeeded",
        "other_invocation",
        "controller_alive",
        "controller_pid",
        "store",
        "processes",
        "allocation",
        "root_nonowner",
    ],
)
def test_no_ambiguous_or_live_original_is_reclassified_as_unpublished(original, monkeypatch, fault):
    if fault == "numeric_failed":
        body = TypeAdapter(type(original.retired)).dump_python(original.retired, mode="json")
        body["original_terminal"]["original_outcome"] = "FAILED"
        original.files.read.return_value = canonical_json_bytes(
            dict(event="EMBEDDING_GPU_BATCH_RETIRED_NOT_PUBLISHED", observation=body)
        )
    elif fault == "controller_succeeded":
        original.control.return_value = replace(
            original.controller, status=original.retired.original_terminal.terminal_unit.status
        )
    elif fault == "other_invocation":
        original.control.return_value = replace(original.controller, invocation_id="d" * 32)
    elif fault == "controller_alive":
        original.control.return_value = replace(original.controller, main_pid=123)
    elif fault == "controller_pid":
        original.metadata.return_value = (original.launch.root_pid + 1, 0)
    elif fault == "store":
        original.metadata.return_value = (original.launch.root_pid, 1)
    elif fault == "processes":
        original.processes.return_value = (123,)
    elif fault == "allocation":
        original.proof = original.proof.model_copy(
            update={"allocation_attempt_id": "embeddingallocation_" + "0" * 32}
        )
    else:
        monkeypatch.setattr(application.os, "getresuid", lambda: (1000, 1000, 1000))
    with pytest.raises(ValueError), application.read_retired_embedding_failure(original.proof):
        pytest.fail("unproven original entered metadata mutation window")


def test_late_original_controller_change_invalidates_entire_mutation_window(original):
    original.control.side_effect = (
        original.controller,
        replace(original.controller, invocation_id="d" * 32),
    )
    with pytest.raises(ValueError), application.read_retired_embedding_failure(original.proof):
        pass


@pytest.fixture
def protected_filesystem():
    with tempfile.TemporaryDirectory(
        prefix="eom-protected-snapshot-", dir="/run" if os.getuid() == 0 else "/tmp"
    ) as directory:
        yield Path(directory)


def test_actual_protected_file_snapshot_is_read_once_and_epoch_fenced_at_exit(
    original, monkeypatch, protected_filesystem
):
    from eom_catalog_service.embedding_runtime_files import NumericalRuntimeFileSnapshots

    root = protected_filesystem / "gpu"
    lifetime = protected_filesystem / "lifetimes"
    instance = original.proof.allocation_attempt_id.removeprefix("embeddingallocation_")
    unit = "eom-embedding-native-gpu-batch@" + instance + ".service"
    execution = root / instance
    retirement = lifetime / unit / original.proof.invocation_id / "retirement/result.json"
    for directory in (
        root,
        execution,
        lifetime,
        lifetime / unit,
        lifetime / unit / original.proof.invocation_id,
        retirement.parent,
    ):
        directory.mkdir(mode=0o700)
    retirement.write_bytes(original.raw)
    retirement.chmod(0o600)
    for name in ("launch.env", "allocation.json"):
        raw = original.files.observe_protected_member_bytes(Path(name), maximum=32768).raw
        (execution / name).write_bytes(raw)
        (execution / name).chmod(0o600)
    monkeypatch.setattr(application, "GPU_BATCH_RUNTIME_ROOT", root)
    monkeypatch.setattr(application, "GPU_BATCH_LIFETIME_ROOT", lifetime)
    monkeypatch.setattr(
        application,
        "NumericalRuntimeFileSnapshots",
        lambda: NumericalRuntimeFileSnapshots(owner_uid=os.getuid()),
    )
    with application.read_retired_embedding_failure(original.proof):
        pass
    with (
        pytest.raises(ValueError, match="FILE_CHANGED"),
        application.read_retired_embedding_failure(original.proof),
    ):
        (execution / "launch.env").write_bytes(b"changed after admission")
