"""Real bounded temporary files; UID/root are explicit unit seams, not OS admission."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
from eom_catalog_service import embedding_batch_control_workspace as workspace
from eom_orchestrator.inference_transfer_cpu_handoff import CpuHandoffIdentity

from tests.unit.test_embedding_batch_owner_control import control_frames


@pytest.fixture
def control_local(tmp_path, monkeypatch):
    owner = CpuHandoffIdentity(os.getuid(), os.getgid())
    # AF_UNIX sun_path is bounded independently of pytest's long test names.
    with tempfile.TemporaryDirectory(prefix="eom-bc-") as directory:
        root = Path(directory)
        monkeypatch.setattr(workspace, "BATCH_CONTROL_ROOT", root)
        monkeypatch.setattr(workspace, "fixed_owner_identity", lambda: owner)
        yield control_frames().request


def root_read(request, monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(os, "getresuid", lambda: (0, 0, 0))
        patch.setattr(os, "getresgid", lambda: (0, 0, 0))
        return workspace.read_embedding_batch_control(
            request.allocation_attempt_id.removeprefix("embeddingallocation_")
        )


def test_exact_metadata_replay_dispatch_once_and_root_read_only_original(
    control_local, monkeypatch
):
    first = workspace.stage_embedding_batch_control(control_local)
    assert workspace.stage_embedding_batch_control(control_local) == first
    with pytest.raises((ValueError, RuntimeError)):
        root_read(control_local, monkeypatch)
    workspace.claim_embedding_batch_control_dispatch(first)
    assert root_read(control_local, monkeypatch) == first
    with pytest.raises(RuntimeError, match="ALREADY_ATTEMPTED"):
        workspace.claim_embedding_batch_control_dispatch(first)
    assert set(path.name for path in first.path.iterdir()) == {
        "allocation.json",
        ".launch-started",
        ".dispatch-attempted",
    }
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in first.path.iterdir())
    assert b'"text"' not in (first.path / "allocation.json").read_bytes()


@pytest.mark.parametrize("fault", ("bytes", "mode", "symlink", "hardlink", "inode", "extra"))
def test_changed_or_partial_metadata_is_never_repaired(control_local, tmp_path, fault):
    staged = workspace.stage_embedding_batch_control(control_local)
    path = staged.path / "allocation.json"
    original = path.read_bytes()
    if fault == "bytes":
        path.write_bytes(b"partial")
    elif fault == "mode":
        path.chmod(0o644)
    elif fault == "symlink":
        saved = tmp_path / "original"
        path.rename(saved)
        path.symlink_to(saved)
    elif fault == "hardlink":
        os.link(path, tmp_path / "second")
    elif fault == "inode":
        replacement = tmp_path / "replacement"
        replacement.write_bytes(original)
        replacement.chmod(0o600)
        replacement.replace(path)
    else:
        (staged.path / "unknown").write_bytes(b"preserve")
    with pytest.raises((ValueError, RuntimeError)):
        staged.assert_current()
    if fault == "bytes":
        with pytest.raises((ValueError, RuntimeError)):
            workspace.stage_embedding_batch_control(control_local)
        assert path.read_bytes() == b"partial"


@pytest.mark.parametrize(
    "attempt", ("", "../x", "x" * 32, "a" * 33, "/tmp/foo", "a" * 32 + ".socket")
)
def test_arbitrary_paths_or_units_are_not_control_identities(attempt):
    with pytest.raises(ValueError):
        workspace.embedding_batch_control_unit(attempt)


def test_wrong_uid_and_expired_request_do_not_create_a_workspace(control_local, monkeypatch):
    monkeypatch.setattr(
        workspace, "fixed_owner_identity", lambda: CpuHandoffIdentity(os.getuid() + 1, os.getgid())
    )
    with pytest.raises(ValueError):
        workspace.stage_embedding_batch_control(control_local)
    assert list(workspace.BATCH_CONTROL_ROOT.iterdir()) == []
    monkeypatch.setattr(
        workspace, "fixed_owner_identity", lambda: CpuHandoffIdentity(os.getuid(), os.getgid())
    )
    from eom_catalog_contracts.embedding_gpu_control import EmbeddingGpuAllocationRequest

    from tests.unit.inference_transfer_embedding_fixtures import seal

    expired = EmbeddingGpuAllocationRequest.model_validate(
        seal(control_local.model_dump(mode="json") | {"expires_monotonic_ns": 1}, "message_sha256")
    )
    with pytest.raises(ValueError):
        workspace.stage_embedding_batch_control(expired)
    assert list(workspace.BATCH_CONTROL_ROOT.iterdir()) == []


def test_root_read_requires_the_named_original_attempt(control_local, monkeypatch):
    staged = workspace.stage_embedding_batch_control(control_local)
    workspace.claim_embedding_batch_control_dispatch(staged)
    wrong = workspace.BATCH_CONTROL_ROOT / ("b" * 32)
    wrong.mkdir(mode=0o700)
    for member in staged.path.iterdir():
        copied = wrong / member.name
        copied.write_bytes(member.read_bytes())
        copied.chmod(0o600)
    with monkeypatch.context() as patch:
        patch.setattr(os, "getresuid", lambda: (0, 0, 0))
        patch.setattr(os, "getresgid", lambda: (0, 0, 0))
        with pytest.raises(ValueError):
            workspace.read_embedding_batch_control("b" * 32)
