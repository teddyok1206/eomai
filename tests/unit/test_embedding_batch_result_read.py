"""Real local bytes/framing with explicit synthetic root/IAM seams; not live DAC or GPU."""

from __future__ import annotations

import os
from dataclasses import replace
from types import SimpleNamespace

import pytest
from eom_catalog_service import embedding_batch_owner_workspace as workspace
from eom_catalog_service.embedding_batch_owner_channel import EmbeddingBatchOwnerChannel
from eom_catalog_service.embedding_benchmark_channel import BenchmarkUnixPeer
from eom_orchestrator.inference_transfer_cpu_handoff import CpuHandoffError, CpuHandoffIdentity
from eom_workflow.embedding_batch_owner_control import EmbeddingBatchRootCompleted
from eom_workflow_runner import embedding_batch_result_read as reader
from eom_workflow_runner.embedding_batch_source_authorization import (
    CatalogEmbeddingBatchSourceAuthorization,
)

from tests.unit.embedding_batch_execution_fixtures import execution_case
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_batch_owner_channel import checked_once, endpoints, raw_send


@pytest.fixture
def local(tmp_path, monkeypatch):
    value = execution_case()
    owner = CpuHandoffIdentity(os.getuid(), os.getgid())
    owner_root, output_root = tmp_path / "owner", tmp_path / "root-output"
    owner_root.mkdir(mode=0o700)
    output_root.mkdir(mode=0o700)
    for module in (workspace, reader):
        monkeypatch.setattr(module, "fixed_owner_identity", lambda: owner)
    monkeypatch.setattr(workspace, "BATCH_OWNER_ROOT", owner_root)
    monkeypatch.setattr(reader, "GPU_BATCH_RUNTIME_ROOT", output_root)
    # Explicit unit-only root filesystem/peer seam. All inode, mode, hash, binary
    # and framing checks remain real; privileged UID/DAC tests are separate.
    original_directory = reader.protected_cpu_handoff_directory
    original_member = reader.read_protected_cpu_handoff_member
    monkeypatch.setattr(
        reader,
        "protected_cpu_handoff_directory",
        lambda path, **kw: original_directory(path, **(kw | {"uid": owner.owner_uid})),
    )
    monkeypatch.setattr(
        reader,
        "read_protected_cpu_handoff_member",
        lambda directory, name, **kw: original_member(
            directory, name, **(kw | {"uid": owner.owner_uid})
        ),
    )
    direct_peer = EmbeddingBatchOwnerChannel.require_direct_peer

    def root_peer(channel):
        actual = direct_peer(channel)
        return BenchmarkUnixPeer(actual.pid, 0, 0)

    monkeypatch.setattr(EmbeddingBatchOwnerChannel, "require_direct_peer", root_peer)
    staged = workspace.stage_owner_embedding_batch(
        value.frames.request, value.frames.ready, value.frames.binding, value.batch
    )
    value.frames.bound = staged.notice
    value.completed = EmbeddingBatchRootCompleted.model_validate(
        seal(
            value.completed.model_dump(mode="json")
            | {
                "bound_message_sha256": staged.notice.message_sha256,
            },
            "message_sha256",
        )
    )
    value.frames.completed = value.completed
    output = output_root / value.completed.allocation_attempt_id.removeprefix(
        "embeddingallocation_"
    )
    output.mkdir(mode=0o750)
    for name, raw in (("result.json", value.raw), ("vectors.f32", value.vectors)):
        path = output / name
        path.write_bytes(raw)
        path.chmod(0o640)
    authorization = object.__new__(CatalogEmbeddingBatchSourceAuthorization)
    authorization._batch = value.batch
    calls = []
    state = SimpleNamespace(deny_at=None, false=False)

    def authorize(self):
        assert self is authorization
        calls.append("source")
        if len(calls) == state.deny_at:
            raise PermissionError("synthetic current source revocation")
        return False if state.false else None

    monkeypatch.setattr(CatalogEmbeddingBatchSourceAuthorization, "authorize_batch", authorize)
    value.staged, value.output = staged, output
    value.authorization, value.calls, value.state = authorization, calls, state
    return value


def received_owner(local):
    """Use the real channel DFA through a completed frame; do not fabricate its phase."""
    return endpoints(value=local.frames)


def receive(root, owner, local, connection):
    checked_once(root, owner, local.frames)
    raw_send(connection, local.completed)
    assert owner.authorize_next(lambda *_: None) == local.completed


def read(owner, local):
    return reader.read_verified_embedding_batch_result(
        owner, local.frames.ready, local.staged, authorization=local.authorization
    )


def test_owner_checks_original_output_and_shares_one_readonly_binary_buffer(local):
    with received_owner(local) as (root, owner, _, _, left, _):
        receive(root, owner, local, left)
        verified = read(owner, local)
        assert verified.result == local.result and local.calls == ["source", "source"]
        assert all(view.readonly for view in verified.child_vectors)
        assert len({id(view.obj) for view in verified.child_vectors}) == 1
        assert b"".join(verified.child_vectors) == local.vectors
        owner.acknowledge_completion(lambda _: verified.assert_current())
        owner.close()
        receipt = verified.receipt("job_" + "9" * 32, owner)
        assert receipt.bound == local.staged.notice
        assert receipt.children == local.receipt.children
        assert receipt.completed == local.completed
        # Read/receipt do not replace or mutate original evidence files.
        assert (local.output / "result.json").read_bytes() == local.raw


@pytest.mark.parametrize(
    "fault", ("raw_hash", "vector_hash", "mode", "symlink", "hardlink", "missing")
)
def test_invalid_output_never_returns_a_receipt_or_repairs_local_files(local, tmp_path, fault):
    name = "vectors.f32" if fault == "vector_hash" else "result.json"
    path = local.output / name
    original = path.read_bytes()
    if fault in ("raw_hash", "vector_hash"):
        path.write_bytes(bytes(len(original)))
    elif fault == "mode":
        path.chmod(0o644)
    elif fault == "symlink":
        saved = tmp_path / "original.json"
        path.rename(saved)
        path.symlink_to(saved)
    elif fault == "hardlink":
        os.link(path, tmp_path / "linked.json")
    else:
        path.unlink()
    with received_owner(local) as (root, owner, _, _, left, _):
        receive(root, owner, local, left)
        with pytest.raises((ValueError, OSError, CpuHandoffError)):
            read(owner, local)
    if fault == "missing":
        assert not path.exists()
    elif fault in ("raw_hash", "vector_hash"):
        assert path.read_bytes() == bytes(len(original))


@pytest.mark.parametrize("deny_at", (1, 2))
def test_current_source_is_checked_before_and_after_binary_materialization(local, deny_at):
    local.state.deny_at = deny_at
    with received_owner(local) as (root, owner, _, _, left, _):
        receive(root, owner, local, left)
        with pytest.raises(PermissionError):
            read(owner, local)
    assert len(local.calls) == deny_at
    assert (local.output / "result.json").read_bytes() == local.raw


def test_false_source_fence_is_not_permission(local):
    local.state.false = True
    with received_owner(local) as (root, owner, _, _, left, _):
        receive(root, owner, local, left)
        with pytest.raises(ValueError):
            read(owner, local)


@pytest.mark.parametrize("member", ("result.json", "vectors.f32"))
def test_same_bytes_replacement_is_stale_not_a_new_implicit_output(local, tmp_path, member):
    with received_owner(local) as (root, owner, _, _, left, _):
        receive(root, owner, local, left)
        verified = read(owner, local)
        path = local.output / member
        replacement = tmp_path / "replacement"
        replacement.write_bytes(path.read_bytes())
        replacement.chmod(0o640)
        replacement.replace(path)
        with pytest.raises(ValueError):
            verified.assert_current()
        with pytest.raises(ValueError):
            verified.receipt("job_" + "9" * 32, owner)


def test_no_completion_or_wrong_original_batch_is_not_read_authority(local):
    with received_owner(local) as (_root, owner, *_), pytest.raises(ValueError):
        read(owner, local)
    with received_owner(local) as (root, owner, _, _, left, _):
        receive(root, owner, local, left)
        wrong = replace(
            local.staged,
            batch=local.batch.model_copy(update={"request_sha256": "sha256:" + "f" * 64}),
        )
        with pytest.raises(ValueError):
            reader.read_verified_embedding_batch_result(
                owner, local.frames.ready, wrong, authorization=local.authorization
            )
