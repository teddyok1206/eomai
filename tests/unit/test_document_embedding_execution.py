"""Actual temporary publication IO; numerical backend, owner and native launcher synthetic."""

from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import FrozenInstanceError
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_service.embedding_encoder_adapter import encode_incremental_batch
from eom_orchestrator.inference_transfer_cpu_handoff import CpuHandoffIdentity
from eom_orchestrator.native_embedding_index_systemd import (
    FixedNativeIndexLauncher,
    NativeIndexLaunchError,
)
from eom_workflow_runner import document_embedding_batch_material as material
from eom_workflow_runner import document_embedding_cpu_execution as cpu
from eom_workflow_runner.document_embedding_execution import (
    DocumentExecutionState,
    OwnedDocumentEmbedding,
)

from tests.unit.local_embedding_admission_fixtures import native_fixture
from tests.unit.test_embedding_incremental_encoding import SyntheticNativeBackend


@pytest.fixture
def staged(tmp_path, monkeypatch):
    root = tmp_path / "documents"
    root.mkdir(mode=0o700)
    monkeypatch.setattr(material, "DOCUMENT_PUBLICATION_ROOT", root)
    monkeypatch.setattr(
        material, "fixed_owner_identity", lambda: CpuHandoffIdentity(os.getuid(), os.getgid())
    )
    fixture = native_fixture(device="CUDA")
    work = OwnedDocumentEmbedding(fixture.association, fixture.native_input)
    backend = SyntheticNativeBackend(fixture.native_input.space)
    backend.batch_size = backend.threads = 4
    encoded = encode_incremental_batch(fixture.native_input, backend)
    return work, encoded


def test_cuda_output_uses_existing_child_publication_layout_and_exact_replay(staged):
    work, encoded = staged
    first = material.stage_batch_document_publication(
        work, encoded.result, memoryview(encoded.vectors)
    )
    epochs = {p.name: p.stat().st_ino for p in first.workspace.iterdir()}
    second = material.stage_batch_document_publication(
        work, encoded.result, memoryview(encoded.vectors)
    )
    assert second == first and second.result == encoded.result
    assert {p.name: p.stat().st_ino for p in first.workspace.iterdir()} == epochs
    assert set(epochs) == {"input.json", "result.json", "vectors.f32"}
    assert (first.workspace / "vectors.f32").read_bytes() == encoded.vectors
    assert all(p.stat().st_mode & 0o777 == 0o600 for p in first.workspace.iterdir())
    with pytest.raises(FrozenInstanceError):
        work.request = None


@pytest.mark.parametrize(
    "fault", ("hash", "writable", "partial", "launch_marker", "symlink", "root_mode", "owner")
)
def test_invalid_or_partial_cuda_material_never_repaired_or_accepted(staged, monkeypatch, fault):
    work, encoded = staged
    vectors = memoryview(encoded.vectors)
    path = material.DOCUMENT_PUBLICATION_ROOT / work.request.job_id.removeprefix("job_")
    if fault == "hash":
        vectors = memoryview(b"\0" * len(encoded.vectors))
    elif fault == "writable":
        vectors = memoryview(bytearray(encoded.vectors))
    elif fault == "root_mode":
        path.parent.chmod(0o755)
    elif fault == "owner":
        monkeypatch.setattr(material.os, "getresuid", lambda: (99999,) * 3)
    else:
        path.mkdir(mode=0o700)
        member = path / (".launch-started" if fault == "launch_marker" else "input.json")
        if fault == "symlink":
            member.symlink_to("missing")
        else:
            member.write_bytes(b"preserve-original")
            member.chmod(0o600)
    with pytest.raises(ValueError):
        material.stage_batch_document_publication(work, encoded.result, vectors)
    if fault in {"partial", "launch_marker"}:
        assert member.read_bytes() == b"preserve-original"
    if fault == "symlink":
        assert member.is_symlink()


def test_cpu_input_cannot_enter_cuda_publication_or_change_original_association(staged):
    fixture = native_fixture()
    _work, encoded = staged
    with pytest.raises(ValueError):
        material.stage_batch_document_publication(
            OwnedDocumentEmbedding(fixture.association, fixture.native_input),
            encoded.result,
            memoryview(encoded.vectors),
        )
    with pytest.raises(ValueError):
        OwnedDocumentEmbedding(fixture.association, native_fixture("c").native_input)


@pytest.mark.parametrize(
    ("states", "expected"),
    (
        (((True, False), (True, False)), DocumentExecutionState.NOT_STARTED),
        (((False, True), (False, True)), DocumentExecutionState.SUCCEEDED),
        (((True, False), (False, True)), DocumentExecutionState.UNCERTAIN),
        (((False, False), (False, False)), DocumentExecutionState.UNCERTAIN),
        ((), DocumentExecutionState.UNCERTAIN),
        (((True, False),), DocumentExecutionState.UNCERTAIN),
    ),
)
def test_cpu_liveness_does_not_fabricate_gpu_unit_observations(states, expected):
    launcher = Mock(spec=FixedNativeIndexLauncher)
    launcher.observe.return_value = tuple(
        SimpleNamespace(fresh=fresh, succeeded=succeeded) for fresh, succeeded in states
    )
    executor = cpu.FixedCpuDocumentEmbeddingExecution(launcher)
    assert executor.observe("job_" + "a" * 32) is expected
    launcher.observe.assert_called_once_with("a" * 32)
    launcher.run.assert_not_called()


@pytest.mark.parametrize("error", (None, "NATIVE_INDEX_BUSY", "NATIVE_INDEX_UNCERTAIN", "DENIED"))
def test_cpu_adapter_retains_current_source_fence_and_original_busy_error_policy(
    monkeypatch, error
):
    fixture = native_fixture()
    work = OwnedDocumentEmbedding(fixture.association, fixture.native_input)
    launcher, source = Mock(spec=FixedNativeIndexLauncher), Mock()
    source.resolve_launch.return_value = SimpleNamespace(owned_input=work.request)
    events = []

    @contextmanager
    def transaction():
        events.append("open")
        yield "actual-session"
        events.append("close")

    monkeypatch.setattr(cpu, "stage_native_index", lambda prepared: events.append("stage"))
    monkeypatch.setattr(
        cpu, "mark_native_index_launch_started", lambda prepared: events.append("mark")
    )

    def run(prepared):
        assert events == ["open", "stage", "mark", "close"]
        assert prepared.association == work.association and prepared.request == work.request
        if error:
            raise NativeIndexLaunchError(error)
        return fixture.result

    launcher.run.side_effect = run
    execute = cpu.FixedCpuDocumentEmbeddingExecution(launcher)
    if error == "DENIED":
        with pytest.raises(NativeIndexLaunchError, match="DENIED"):
            execute.execute(work, source=source, transaction=transaction)
    else:
        output = execute.execute(work, source=source, transaction=transaction)
        assert (output is None) == (error is not None)
        if output is not None:
            assert output.result == fixture.result
    source.resolve_launch.assert_called_once_with("actual-session", work.association)


def test_cpu_source_denial_and_cuda_request_never_stage_or_launch(monkeypatch):
    fixture = native_fixture()
    launcher, source = Mock(spec=FixedNativeIndexLauncher), Mock()
    stage = Mock()
    monkeypatch.setattr(cpu, "stage_native_index", stage)
    source.resolve_launch.side_effect = PermissionError("current source revoked")

    @contextmanager
    def transaction():
        yield "actual-session"

    execute = cpu.FixedCpuDocumentEmbeddingExecution(launcher)
    with pytest.raises(PermissionError):
        execute.execute(
            OwnedDocumentEmbedding(fixture.association, fixture.native_input),
            source=source,
            transaction=transaction,
        )
    with pytest.raises(ValueError):
        execute.assert_current_runtime(native_fixture(device="CUDA").request)
    stage.assert_not_called()
    launcher.run.assert_not_called()
