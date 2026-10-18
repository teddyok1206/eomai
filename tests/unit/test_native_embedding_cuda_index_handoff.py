"""Original CUDA handoff with synthetic root IO only; no launch or retirement proof."""

from __future__ import annotations

import ast
import json
import os
import stat
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.embedding_native_cuda_index_owner_binding import (
    native_cuda_index_owner_binding_bytes,
)
from eom_catalog_contracts.inference_transfer_embedding import IncrementalEmbeddingInput
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_orchestrator import native_embedding_cuda_index_handoff as handoff
from eom_orchestrator import native_embedding_index_handoff as cpu
from eom_orchestrator.inference_transfer_cpu_handoff import (
    CpuHandoffError,
    CpuHandoffIdentity,
    protected_cpu_handoff_directory,
)
from eom_workflow.local_embedding_encoding_job import LocalEmbeddingLaunchAssociation
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.local_embedding_admission_fixtures import native_fixture

INVALID = (ValueError, TypeError, CpuHandoffError, SchemaError)


def test_real_unprivileged_process_birth_reader_is_not_a_production_owner_grant() -> None:
    # Exercise real proc descriptors without root, service mutation or impersonation.
    # The production public API still resolves the fixed workflow owner separately.
    identity = CpuHandoffIdentity(os.geteuid(), os.getegid())
    born = handoff._owner_start_ticks(os.getpid(), identity)
    assert born > 0
    assert handoff._owner_start_ticks(os.getpid(), identity) == born


def prepared() -> handoff.PreparedNativeCudaIndex:
    fixture = native_fixture(device="CUDA")
    return handoff.PreparedNativeCudaIndex("a" * 32, fixture.association, fixture.native_input)


@pytest.fixture
def staged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> handoff.PreparedNativeCudaIndex:
    owner_root = tmp_path / "owner"
    owner_root.mkdir(mode=0o700)
    monkeypatch.setattr(handoff, "OWNER_ROOT", owner_root)
    monkeypatch.setattr(handoff, "RUNTIME_ROOT", tmp_path / "runtime")
    monkeypatch.setattr(
        handoff, "fixed_owner_identity", lambda: CpuHandoffIdentity(os.geteuid(), os.getegid())
    )
    value = prepared()
    handoff.stage_native_cuda_index(value)
    return value


def synthetic_root(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Mock, Mock]:
    """Translate only the root-file boundary; never claim privileged acceptance."""
    uid = os.geteuid()
    monkeypatch.setattr(
        handoff,
        "os",
        SimpleNamespace(
            geteuid=lambda: 0,
            **{
                name: getattr(os, name)
                for name in (
                    "fsync",
                    "open",
                    "fstat",
                    "read",
                    "stat",
                    "close",
                    "O_RDONLY",
                    "O_NOFOLLOW",
                    "O_CLOEXEC",
                    "O_NONBLOCK",
                )
            },
        ),
    )

    def directory(path: Path, **values: Any) -> Any:
        if values["uid"] == 0:
            values["uid"] = uid
        return protected_cpu_handoff_directory(path, **values)

    def create_member(
        descriptor: int, name: str, payload: bytes, *, owner_gid: int, mode: int
    ) -> None:
        assert owner_gid == os.getegid()
        fd = os.open(
            name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode, dir_fd=descriptor
        )
        try:
            os.fchmod(fd, mode)
            os.write(fd, payload)
            os.fsync(fd)
        finally:
            os.close(fd)

    def create_three(
        runtime_root: Path, execution_id: str, input_bytes: bytes, *, owner: CpuHandoffIdentity
    ) -> None:
        runtime_root.mkdir(mode=0o750, exist_ok=True)
        path = runtime_root / execution_id
        try:
            path.mkdir(mode=0o750)
        except FileExistsError:
            raise CpuHandoffError("NATIVE_CPU_HANDOFF_EXISTS") from None
        with directory(path, owner=owner, uid=0, gid=owner.owner_gid, mode=0o750) as fd:
            create_member(fd, "input.json", input_bytes, owner_gid=owner.owner_gid, mode=0o600)
            for name in ("result.json", "vectors.f32"):
                create_member(fd, name, b"", owner_gid=owner.owner_gid, mode=0o640)

    three = Mock(side_effect=create_three)
    ready = Mock(side_effect=create_member)
    monkeypatch.setattr(handoff, "protected_cpu_handoff_directory", directory)
    monkeypatch.setattr(handoff, "create_native_cpu_descriptor_handoff", three)
    monkeypatch.setattr(handoff, "create_protected_cpu_handoff_member", ready)
    return three, ready


def test_distinct_device_boundaries_share_exact_original_validation() -> None:
    cuda = prepared()
    assert cpu.validate_native_index_original_input(cuda.association, cuda.request) == (
        cuda.association,
        cuda.request,
    )
    assert cuda.request.batch_size == cuda.request.threads == 4
    assert cuda.workspace == cpu.OWNER_ROOT / cuda.execution_id
    assert Path("/run/eom-native-embedding-cuda-index") == handoff.RUNTIME_ROOT
    assert handoff.RUNTIME_ROOT != cpu.RUNTIME_ROOT
    assert cuda.association.owned_input.sha256 == sha256_bytes(
        canonical_json_bytes(cuda.request.model_dump(mode="json"))
    )
    assert (
        len(
            {
                cuda.association.association_sha256,
                cuda.association.owned_input.sha256,
                cuda.request.request_sha256,
                cuda.request.input_set_sha256,
            }
        )
        == 4
    )
    with pytest.raises(cpu.NativeIndexHandoffError, match="ASSOCIATION_INPUT_MISMATCH"):
        cpu.PreparedNativeIndex(cuda.execution_id, cuda.association, cuda.request)
    fixture = native_fixture()
    assert cpu.PreparedNativeIndex("b" * 32, fixture.association, fixture.native_input)
    with pytest.raises(handoff.NativeCudaIndexHandoffError, match="DEVICE_INVALID"):
        handoff.PreparedNativeCudaIndex("b" * 32, fixture.association, fixture.native_input)


@pytest.mark.parametrize("value", ("", "../a", "A" * 32, "a" * 31, "a" * 33, True))
def test_execution_id_cannot_select_arbitrary_workspace(value: Any) -> None:
    original = prepared()
    with pytest.raises(ValueError, match="EXECUTION_ID_INVALID"):
        handoff.PreparedNativeCudaIndex(value, original.association, original.request)


@pytest.mark.parametrize("field", ("job_id", "batch_size", "threads", "request_sha256"))
def test_other_request_cannot_reuse_original_association(field: str) -> None:
    original = prepared()
    body = original.request.model_dump(mode="json")
    body[field] = {
        "job_id": "job_" + "f" * 32,
        "batch_size": 8,
        "threads": 8,
        "request_sha256": "sha256:" + "e" * 64,
    }[field]
    if field != "request_sha256":
        body = seal(body, "request_sha256")
    with pytest.raises(INVALID):
        request = IncrementalEmbeddingInput.model_validate(body)
        handoff.PreparedNativeCudaIndex(original.execution_id, original.association, request)


@pytest.mark.parametrize("field", ("owned_input", "owned_input_request_sha256", "intent"))
def test_other_rehashed_association_cannot_reuse_original_request(field: str) -> None:
    original = prepared()
    body = original.association.model_dump(mode="json")
    if field == "owned_input":
        body[field]["sha256"] = "sha256:" + "e" * 64
    elif field == "intent":
        body[field]["native_launch_job_id"] = "job_" + "f" * 32
        body[field] = seal(body[field], "intent_sha256")
    else:
        body[field] = "sha256:" + "e" * 64
    association = LocalEmbeddingLaunchAssociation.model_validate(seal(body, "association_sha256"))
    with pytest.raises(cpu.NativeIndexHandoffError, match="ASSOCIATION_INPUT_MISMATCH"):
        handoff.PreparedNativeCudaIndex(original.execution_id, association, original.request)


@pytest.mark.parametrize("field", ("request", "association", "nested_runtime"))
def test_copied_model_extras_cannot_disappear_during_validation(field: str) -> None:
    original = prepared()
    association, request = original.association, original.request
    if field == "association":
        association = association.model_copy(update={"root_ack": True})
    elif field == "nested_runtime":
        runtime = request.space.runtime.model_copy(update={"source_grant": True})
        request = request.model_copy(
            update={"space": request.space.model_copy(update={"runtime": runtime})}
        )
    else:
        request = request.model_copy(update={"root_ack": True})
    with pytest.raises(ValueError, match="undeclared fields"):
        handoff.PreparedNativeCudaIndex(original.execution_id, association, request)


def test_ordered_original_rows_and_space_cannot_be_substituted() -> None:
    original = prepared()
    reversed_rows = original.request.model_dump(mode="json")
    reversed_rows["rows"].reverse()
    with pytest.raises(INVALID):
        request = IncrementalEmbeddingInput.model_validate(seal(reversed_rows, "request_sha256"))
        handoff.PreparedNativeCudaIndex(original.execution_id, original.association, request)
    other = native_fixture("c", "d", device="CUDA")
    with pytest.raises(cpu.NativeIndexHandoffError, match="ASSOCIATION_INPUT_MISMATCH"):
        handoff.PreparedNativeCudaIndex(
            original.execution_id, original.association, other.native_input
        )
    cpu_fixture = native_fixture()
    with pytest.raises(cpu.NativeIndexHandoffError, match="ASSOCIATION_INPUT_MISMATCH"):
        handoff.PreparedNativeCudaIndex(
            original.execution_id, original.association, cpu_fixture.native_input
        )


def test_exact_staging_and_separate_marker_replay(staged: handoff.PreparedNativeCudaIndex) -> None:
    original = {
        name: (staged.workspace / name).stat().st_ino for name in ("input.json", "association.json")
    }
    assert handoff.read_prepared_native_cuda_index(staged.execution_id) == staged
    handoff.stage_native_cuda_index(staged)
    assert {name: (staged.workspace / name).stat().st_ino for name in original} == original
    assert not (staged.workspace / ".launch-started").exists()
    handoff.mark_native_cuda_index_launch_started(staged)
    handoff.mark_native_cuda_index_launch_started(staged)
    assert (
        staged.workspace / ".launch-started"
    ).read_bytes() == staged.association.association_sha256.encode("ascii")
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in staged.workspace.iterdir())
    assert not handoff.RUNTIME_ROOT.exists()


def test_changed_valid_staged_pair_cannot_mark_original_launch(
    staged: handoff.PreparedNativeCudaIndex,
) -> None:
    other = native_fixture("c", "d", device="CUDA")
    for name, model in (
        ("input.json", other.native_input),
        ("association.json", other.association),
    ):
        (staged.workspace / name).write_bytes(canonical_json_bytes(model.model_dump(mode="json")))
    with pytest.raises(handoff.NativeCudaIndexHandoffError, match="STAGED_INPUT_CHANGED"):
        handoff.mark_native_cuda_index_launch_started(staged)
    assert not (staged.workspace / ".launch-started").exists()
    assert not handoff.RUNTIME_ROOT.exists()


@pytest.mark.parametrize("member", ("input.json", "association.json"))
@pytest.mark.parametrize("fault", ("changed", "noncanonical", "symlink", "mode", "hardlink"))
def test_invalid_original_staging_never_reaches_runtime(
    staged: handoff.PreparedNativeCudaIndex,
    monkeypatch: pytest.MonkeyPatch,
    member: str,
    fault: str,
) -> None:
    path = staged.workspace / member
    if fault == "changed":
        path.write_bytes(b"{}")
    elif fault == "noncanonical":
        path.write_bytes(path.read_bytes() + b"\n")
    elif fault == "symlink":
        path.rename(path.with_suffix(".original"))
        path.symlink_to(path.with_suffix(".original"))
    elif fault == "hardlink":
        os.link(path, path.with_suffix(".linked"))
    else:
        path.chmod(0o640)
    with pytest.raises(INVALID):
        handoff.read_prepared_native_cuda_index(staged.execution_id)
    three, ready = synthetic_root(monkeypatch)
    with pytest.raises(INVALID):
        handoff.prepare_native_cuda_index_handoff(staged.execution_id)
    three.assert_not_called()
    ready.assert_not_called()


def test_conflicting_staging_is_preserved(staged: handoff.PreparedNativeCudaIndex) -> None:
    path = staged.workspace / "input.json"
    path.write_bytes(b"{")
    with pytest.raises(ValueError, match="MEMBER_CONFLICT"):
        handoff.stage_native_cuda_index(staged)
    assert path.read_bytes() == b"{"


def test_other_owner_and_nonroot_prepare_are_denied_before_io(
    staged: handoff.PreparedNativeCudaIndex, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert os.geteuid() != 0
    with pytest.raises(ValueError, match="ROOT_REQUIRED"):
        handoff.prepare_native_cuda_index_handoff(staged.execution_id)
    monkeypatch.setattr(handoff, "os", SimpleNamespace(geteuid=lambda: os.geteuid() + 1))
    with pytest.raises(ValueError, match="OWNER_REQUIRED"):
        handoff.stage_native_cuda_index(staged)
    with pytest.raises(ValueError, match="OWNER_REQUIRED"):
        handoff.mark_native_cuda_index_launch_started(staged)
    with pytest.raises(ValueError, match="OWNER_OR_ROOT_REQUIRED"):
        handoff.read_prepared_native_cuda_index(staged.execution_id)


@pytest.mark.parametrize("marker", (None, b"sha256:" + b"f" * 64))
def test_root_prepare_requires_exact_existing_launch_marker(
    staged: handoff.PreparedNativeCudaIndex, monkeypatch: pytest.MonkeyPatch, marker: bytes | None
) -> None:
    if marker is not None:
        (staged.workspace / ".launch-started").write_bytes(marker)
        (staged.workspace / ".launch-started").chmod(0o600)
    three, ready = synthetic_root(monkeypatch)
    with pytest.raises(INVALID):
        handoff.prepare_native_cuda_index_handoff(staged.execution_id)
    three.assert_not_called()
    ready.assert_not_called()


def test_root_runtime_has_exact_original_and_three_empty_channels(
    staged: handoff.PreparedNativeCudaIndex, monkeypatch: pytest.MonkeyPatch
) -> None:
    handoff.mark_native_cuda_index_launch_started(staged)
    original = (staged.workspace / "input.json").read_bytes()
    three, ready = synthetic_root(monkeypatch)
    handoff.prepare_native_cuda_index_handoff(staged.execution_id)
    three.assert_called_once_with(
        handoff.RUNTIME_ROOT,
        staged.execution_id,
        original,
        owner=CpuHandoffIdentity(os.geteuid(), os.getegid()),
    )
    assert ready.call_args.args[1:] == ("ready.json", b"")
    assert ready.call_args.kwargs == {"owner_gid": os.getegid(), "mode": 0o640}
    runtime = handoff.RUNTIME_ROOT / staged.execution_id
    assert {path.name for path in runtime.iterdir()} == {
        "input.json",
        "result.json",
        "vectors.f32",
        "ready.json",
    }
    assert (runtime / "input.json").read_bytes() == original
    for name in ("result.json", "vectors.f32", "ready.json"):
        path = runtime / name
        assert path.read_bytes() == b""
        assert path.stat().st_nlink == 1
        assert stat.S_IMODE(path.stat().st_mode) == 0o640
    assert stat.S_IMODE((runtime / "input.json").stat().st_mode) == 0o600
    with pytest.raises(ValueError, match="HANDOFF_EXISTS"):
        handoff.prepare_native_cuda_index_handoff(staged.execution_id)
    assert (runtime / "input.json").read_bytes() == original
    assert not (staged.workspace / ".dispatch-attempted").exists()


def test_partial_ready_creation_is_not_repaired_or_retried(
    staged: handoff.PreparedNativeCudaIndex, monkeypatch: pytest.MonkeyPatch
) -> None:
    handoff.mark_native_cuda_index_launch_started(staged)
    _, ready = synthetic_root(monkeypatch)
    ready.side_effect = CpuHandoffError("NATIVE_CPU_HANDOFF_WRITE_FAILED")
    with pytest.raises(ValueError, match="HANDOFF_WRITE_FAILED"):
        handoff.prepare_native_cuda_index_handoff(staged.execution_id)
    runtime = handoff.RUNTIME_ROOT / staged.execution_id
    assert {path.name for path in runtime.iterdir()} == {"input.json", "result.json", "vectors.f32"}
    with pytest.raises(ValueError, match="HANDOFF_EXISTS"):
        handoff.prepare_native_cuda_index_handoff(staged.execution_id)
    ready.assert_called_once()


def test_module_has_no_completion_launch_or_sibling_private_dependency() -> None:
    assert not any("materialize" in name or "completion" in name for name in vars(handoff))
    tree = ast.parse(Path(handoff.__file__).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert not any(alias.name.startswith("_") for alias in node.names)
            assert node.module is not None
            assert not any(
                name in node.module
                for name in ("benchmark", "executor", "systemd", "backend", "sqlalchemy")
            )


def test_binding_uses_actual_owner_and_existing_association_marker(
    staged: handoff.PreparedNativeCudaIndex,
) -> None:
    handoff.mark_native_cuda_index_launch_started(staged)
    binding = handoff.read_native_cuda_index_owner_binding(staged.execution_id)
    assert binding.owner_pid == os.getpid()
    assert binding.owner_start_ticks > 0
    assert binding.execution_id == staged.execution_id
    assert binding.launch_association_sha256 == staged.association.association_sha256
    assert (
        staged.workspace / "owner-binding.json"
    ).read_bytes() == native_cuda_index_owner_binding_bytes(binding)
    assert (
        staged.workspace / ".launch-started"
    ).read_bytes() == staged.association.association_sha256.encode("ascii")
    handoff.require_native_cuda_index_owner_current(binding)


@pytest.mark.parametrize("field", ("execution_id", "launch_association_sha256"))
def test_rehashed_other_binding_is_not_original_staged_linkage(
    staged: handoff.PreparedNativeCudaIndex, field: str
) -> None:
    handoff.mark_native_cuda_index_launch_started(staged)
    path = staged.workspace / "owner-binding.json"
    body = json.loads(path.read_bytes())
    body[field] = "c" * 32 if field == "execution_id" else "sha256:" + "c" * 64
    body["binding_sha256"] = content_sha256(
        {k: v for k, v in body.items() if k != "binding_sha256"}
    )
    path.write_bytes(canonical_json_bytes(body))
    with pytest.raises(ValueError, match="OWNER_BINDING_MISMATCH"):
        handoff.read_native_cuda_index_owner_binding(staged.execution_id)


@pytest.mark.parametrize("fault", ("mode", "symlink", "hardlink", "tamper", "missing"))
def test_untrusted_binding_never_reaches_root_creation(
    staged: handoff.PreparedNativeCudaIndex, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    handoff.mark_native_cuda_index_launch_started(staged)
    path = staged.workspace / "owner-binding.json"
    if fault == "mode":
        path.chmod(0o640)
    elif fault == "symlink":
        path.rename(path.with_suffix(".original"))
        path.symlink_to(path.with_suffix(".original"))
    elif fault == "hardlink":
        os.link(path, path.with_suffix(".linked"))
    elif fault == "tamper":
        body = json.loads(path.read_bytes())
        body["owner_start_ticks"] += 1
        path.write_bytes(canonical_json_bytes(body))
    else:
        path.unlink()
    three, ready = synthetic_root(monkeypatch)
    with pytest.raises(INVALID):
        handoff.prepare_native_cuda_index_handoff(staged.execution_id)
    three.assert_not_called()
    ready.assert_not_called()


def test_replacement_owner_cannot_overwrite_original_binding(
    staged: handoff.PreparedNativeCudaIndex, monkeypatch: pytest.MonkeyPatch
) -> None:
    handoff.mark_native_cuda_index_launch_started(staged)
    path = staged.workspace / "owner-binding.json"
    first, marker = path.read_bytes(), (staged.workspace / ".launch-started").read_bytes()
    binding = handoff.read_native_cuda_index_owner_binding(staged.execution_id)
    monkeypatch.setattr(
        handoff, "os", SimpleNamespace(geteuid=os.geteuid, getpid=lambda: os.getpid() + 1)
    )
    monkeypatch.setattr(handoff, "_owner_start_ticks", lambda *_: binding.owner_start_ticks)
    with pytest.raises(ValueError, match="MEMBER_CONFLICT"):
        handoff.mark_native_cuda_index_launch_started(staged)
    assert path.read_bytes() == first
    assert (staged.workspace / ".launch-started").read_bytes() == marker


def test_cleanup_read_survives_owner_death_but_prepare_checks_live_birth(
    staged: handoff.PreparedNativeCudaIndex, monkeypatch: pytest.MonkeyPatch
) -> None:
    handoff.mark_native_cuda_index_launch_started(staged)
    binding = handoff.read_native_cuda_index_owner_binding(staged.execution_id)
    three, ready = synthetic_root(monkeypatch)
    monkeypatch.setattr(
        handoff, "_owner_start_ticks", Mock(side_effect=FileNotFoundError("synthetic owner died"))
    )
    assert handoff.read_native_cuda_index_owner_binding(staged.execution_id) == binding
    with pytest.raises(FileNotFoundError):
        handoff.prepare_native_cuda_index_handoff(staged.execution_id)
    three.assert_not_called()
    ready.assert_not_called()
    monkeypatch.setattr(handoff, "_owner_start_ticks", lambda *_: binding.owner_start_ticks + 1)
    with pytest.raises(ValueError, match="OWNER_CHANGED"):
        handoff.prepare_native_cuda_index_handoff(staged.execution_id)
    three.assert_not_called()


@pytest.mark.parametrize(
    "fault", (None, "uid", "gid", "duplicate_uid", "birth", "pid", "stale_binding")
)
def test_public_current_owner_check_has_one_strict_kernel_rule(
    staged: handoff.PreparedNativeCudaIndex, monkeypatch: pytest.MonkeyPatch, fault: str | None
) -> None:
    handoff.mark_native_cuda_index_launch_started(staged)
    binding = handoff.read_native_cuda_index_owner_binding(staged.execution_id)
    calls = []

    def read(pid: int, name: str, owner: CpuHandoffIdentity) -> bytes:
        assert pid == binding.owner_pid and owner.owner_uid == os.geteuid()
        calls.append(name)
        if name == "status":
            uid = os.geteuid() + (fault == "uid")
            gid = os.getegid() + (fault == "gid")
            value = f"Uid:\t{uid} {uid} {uid} {uid}\nGid:\t{gid} {gid} {gid} {gid}\n".encode()
            return value + (
                f"Uid:\t{uid} {uid} {uid} {uid}\n".encode() if fault == "duplicate_uid" else b""
            )
        ticks = binding.owner_start_ticks + (
            fault == "stale_binding" or (fault == "birth" and len(calls) > 1)
        )
        pid = binding.owner_pid + (fault == "pid")
        return f"{pid} (synthetic owner)) S {'0 ' * 18}{ticks}\n".encode()

    monkeypatch.setattr(handoff, "_read_owner_process_member", read)
    if fault is None:
        handoff.require_native_cuda_index_owner_current(binding)
        assert calls == ["stat", "status", "stat"]
    else:
        with pytest.raises(ValueError):
            handoff.require_native_cuda_index_owner_current(binding)


def test_cpu_marker_bytes_and_files_remain_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "cpu-owner"
    root.mkdir(mode=0o700)
    monkeypatch.setattr(cpu, "OWNER_ROOT", root)
    monkeypatch.setattr(
        cpu, "fixed_owner_identity", lambda: CpuHandoffIdentity(os.geteuid(), os.getegid())
    )
    fixture = native_fixture()
    value = cpu.PreparedNativeIndex("b" * 32, fixture.association, fixture.native_input)
    cpu.stage_native_index(value)
    cpu.mark_native_index_launch_started(value)
    assert (
        value.workspace / ".launch-started"
    ).read_bytes() == value.association.association_sha256.encode("ascii")
    assert {path.name for path in value.workspace.iterdir()} == {
        "input.json",
        "association.json",
        ".launch-started",
    }
