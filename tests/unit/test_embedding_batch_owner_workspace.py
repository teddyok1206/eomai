"""Real owner-local input files in a temporary root; no NAS, source admission or unit effects."""

from __future__ import annotations

import os
import time

import pytest
from eom_catalog_service import embedding_batch_owner_workspace as workspace
from eom_orchestrator.inference_transfer_cpu_handoff import CpuHandoffIdentity
from eom_workflow.embedding_batch_owner_control import EmbeddingBatchOwnerBound

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_batch_owner_control import control_frames


@pytest.fixture
def local(tmp_path, monkeypatch):
    identity = CpuHandoffIdentity(os.getuid(), os.getgid())
    root = tmp_path / "owner"
    root.mkdir(mode=0o700)
    monkeypatch.setattr(workspace, "BATCH_OWNER_ROOT", root)
    monkeypatch.setattr(workspace, "fixed_owner_identity", lambda: identity)
    value = control_frames()
    value.root, value.identity = root, identity
    return value


def stage(value):
    return workspace.stage_owner_embedding_batch(
        value.request, value.ready, value.binding, value.batch
    )


def test_original_local_stage_is_exact_replay_and_root_read_is_read_only(local):
    first = stage(local)
    first.assert_current()
    second = stage(local)
    assert first == second
    assert first.batch == local.batch
    assert first.notice.owner_pid == os.getpid()
    assert first.notice.owner_start_ticks != 12345  # actual /proc, not the wire fixture's value
    assert workspace.read_owner_embedding_batch(local.request, first.notice) == first
    directory = local.root / local.request.allocation_attempt_id.removeprefix(
        "embeddingallocation_"
    )
    assert set(path.name for path in directory.iterdir()) == {
        "batch-input.json",
        "batch-bound.json",
    }
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in directory.iterdir())


@pytest.mark.parametrize("mutation", ("bytes", "mode", "symlink", "hardlink", "extra", "inode"))
def test_changed_input_is_never_silently_rebound_or_repaired(local, tmp_path, mutation):
    staged = stage(local)
    directory = local.root / local.request.allocation_attempt_id.removeprefix(
        "embeddingallocation_"
    )
    path = directory / "batch-input.json"
    original = path.read_bytes()
    if mutation == "bytes":
        path.write_bytes(original + b" ")
    elif mutation == "mode":
        path.chmod(0o644)
    elif mutation == "symlink":
        saved = tmp_path / "saved-input.json"
        path.rename(saved)
        path.symlink_to(saved)
    elif mutation == "hardlink":
        os.link(path, tmp_path / "linked-input.json")
    elif mutation == "extra":
        (directory / "other.json").write_bytes(b"{}")
    else:
        replacement = tmp_path / "same-bytes.json"
        replacement.write_bytes(original)
        replacement.chmod(0o600)
        replacement.replace(path)
    with pytest.raises((ValueError, RuntimeError)):
        staged.assert_current()
    if mutation != "inode":
        with pytest.raises((ValueError, RuntimeError)):
            workspace.read_owner_embedding_batch(local.request, staged.notice)


def test_partial_input_is_preserved_instead_of_truncated_on_stage(local):
    directory = local.root / local.request.allocation_attempt_id.removeprefix(
        "embeddingallocation_"
    )
    directory.mkdir(mode=0o700)
    path = directory / "batch-input.json"
    path.write_bytes(b"partial original input")
    path.chmod(0o600)
    with pytest.raises((ValueError, RuntimeError)):
        stage(local)
    assert path.read_bytes() == b"partial original input"
    assert not (directory / "batch-bound.json").exists()


@pytest.mark.parametrize(
    "field,value",
    (
        ("owner_pid", 2147483647),
        ("owner_start_ticks", 1),
        ("input_raw_sha256", "sha256:" + "f" * 64),
    ),
)
def test_wrong_owner_birth_or_expected_bytes_are_not_a_valid_local_pointer(local, field, value):
    staged = stage(local)
    notice = EmbeddingBatchOwnerBound.model_validate(
        seal(staged.notice.model_dump(mode="json") | {field: value}, "message_sha256")
    )
    with pytest.raises((ValueError, RuntimeError, OSError)):
        workspace.read_owner_embedding_batch(local.request, notice)


def test_native_child_order_and_original_job_identity_must_match_binding(local):
    staged = stage(local)
    notice_body = staged.notice.model_dump(mode="json")
    binding_body = notice_body["binding"]
    binding_body["children"].reverse()
    notice_body["binding"] = seal(binding_body, "record_sha256")
    notice = EmbeddingBatchOwnerBound.model_validate(seal(notice_body, "message_sha256"))
    with pytest.raises(ValueError):
        workspace.validate_embedding_owner_bound_input(local.request, notice, local.batch)


def test_uid_mismatch_cannot_create_or_overwrite_owner_workspace(local, monkeypatch):
    other = CpuHandoffIdentity(local.identity.owner_uid + 1, local.identity.owner_gid)
    monkeypatch.setattr(workspace, "fixed_owner_identity", lambda: other)
    with pytest.raises(ValueError):
        stage(local)
    assert list(local.root.iterdir()) == []


def test_expired_allocation_cannot_materialize_a_new_input(local):
    expired = control_frames(expires_ns=time.monotonic_ns() - 1)
    with pytest.raises(ValueError):
        workspace.stage_owner_embedding_batch(
            expired.request, expired.ready, expired.binding, expired.batch
        )
    assert list(local.root.iterdir()) == []
