"""Unprivileged temporary files and explicit fake root boundary; not an OS gate."""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from eom_identifiers import canonical_json_bytes
from eom_orchestrator import inference_transfer_cpu_handoff as handoff
from eom_orchestrator.inference_transfer_experiment_ports import LocalExperimentInput
from eom_orchestrator.inference_transfer_experiment_workspace import (
    ExperimentWorkspaceError,
    ProtectedExperimentWorkspace,
)
from jsonschema.exceptions import ValidationError as SchemaValidationError

from tests.unit.inference_transfer_experiment_fixtures import experiment_request
from tests.unit.inference_transfer_fixtures import NOW

EXECUTION = "embeddingexecution_" + "a" * 32


def owner() -> handoff.CpuHandoffIdentity:
    return handoff.CpuHandoffIdentity(os.geteuid(), os.getegid())


def member(path: Path, payload: bytes, *, mode: int = 0o600) -> None:
    path.write_bytes(payload)
    path.chmod(mode)


@pytest.mark.parametrize(
    "identity", [None, "", "a" * 32, "../secret", EXECUTION.upper(), EXECUTION + ".service"]
)
def test_execution_identity_cannot_select_arbitrary_path_or_unit(identity: Any) -> None:
    with pytest.raises(handoff.CpuHandoffError, match="EXECUTION_ID_INVALID"):
        handoff.validate_cpu_execution_id(identity)


def test_non_root_cannot_prepare(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(handoff.os, "geteuid", lambda: 1001)
    with pytest.raises(handoff.CpuHandoffError, match="ROOT_REQUIRED"):
        handoff.prepare_cpu_handoff(EXECUTION)


def test_request_requires_exact_canonical_bytes_and_declared_budget() -> None:
    request = experiment_request()
    payload = canonical_json_bytes(request.model_dump(mode="json"))
    assert handoff._request(payload) == request
    with pytest.raises(handoff.CpuHandoffError, match="REQUEST_INVALID"):
        handoff._request(payload + b"\n")
    with pytest.raises(handoff.CpuHandoffError, match="REQUEST_INVALID"):
        handoff._request(b'{"schema_version":"forged",' + payload[1:])
    with pytest.raises(handoff.CpuHandoffError, match="REQUEST_INVALID"):
        handoff._request(
            canonical_json_bytes(
                experiment_request(maximum_input_bytes=1024).model_dump(mode="json")
            )
        )


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "mode", "size", "uid"])
def test_root_reader_rejects_untrusted_member_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    target = tmp_path / "request.json"
    member(target, b"synthetic data")
    if kind == "symlink":
        target = tmp_path / "link.json"
        target.symlink_to(tmp_path / "request.json")
    elif kind == "hardlink":
        os.link(target, tmp_path / "link.json")
    elif kind == "mode":
        target.chmod(0o644)
    elif kind == "size":
        monkeypatch.setattr(handoff, "MAX_EXPERIMENT_MEMBER_BYTES", 1)
    descriptor = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(handoff.CpuHandoffError, match="MEMBER_INVALID"):
            handoff._read_member(
                descriptor, target.name, uid=os.geteuid() + (kind == "uid"), mode=0o600
            )
    finally:
        os.close(descriptor)


def test_reader_checks_named_inode_after_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "request.json"
    member(target, b"synthetic data")
    original = os.read
    swapped = False

    def replace_name(fd: int, size: int) -> bytes:
        nonlocal swapped
        value = original(fd, size)
        if value and not swapped:
            swapped = True
            target.rename(tmp_path / "old.json")
            member(target, value)
        return value

    monkeypatch.setattr(handoff.os, "read", replace_name)
    descriptor = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(handoff.CpuHandoffError, match="MEMBER_CHANGED"):
            handoff._read_member(descriptor, target.name, uid=os.geteuid(), mode=0o600)
    finally:
        os.close(descriptor)


def test_directory_checks_private_mode_symlink_and_named_identity(tmp_path: Path) -> None:
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    with handoff._directory(private, owner=owner(), uid=os.geteuid(), mode=0o700):
        pass
    private.chmod(0o777)
    with (
        pytest.raises(handoff.CpuHandoffError, match="DIRECTORY_INVALID"),
        handoff._directory(private, owner=owner(), uid=os.geteuid(), mode=0o700),
    ):
        pass
    private.chmod(0o700)
    link = tmp_path / "link"
    link.symlink_to(private, target_is_directory=True)
    with (
        pytest.raises(handoff.CpuHandoffError, match="DIRECTORY_INVALID"),
        handoff._directory(link, owner=owner(), uid=os.geteuid(), mode=0o700),
    ):
        pass
    with (
        pytest.raises(handoff.CpuHandoffError, match="DIRECTORY_CHANGED"),
        handoff._directory(private, owner=owner(), uid=os.geteuid(), mode=0o700),
    ):
        private.rename(tmp_path / "old")
        private.mkdir(mode=0o700)


@pytest.mark.skipif(os.geteuid() == 0, reason="kernel read denial requires an unprivileged caller")
def test_traversal_only_ancestor_does_not_require_directory_listing(tmp_path: Path) -> None:
    ancestor = tmp_path / "traversal-only"
    ancestor.mkdir(mode=0o700)
    leaf = ancestor / "leaf"
    leaf.mkdir(mode=0o700)
    member(leaf / "value", b"synthetic", mode=0o600)
    ancestor.chmod(0o111)
    try:
        with pytest.raises(PermissionError):
            os.open(ancestor, os.O_RDONLY | os.O_DIRECTORY)
        with handoff._directory(leaf, owner=owner(), uid=os.geteuid(), mode=0o700) as directory:
            descriptor = os.open("value", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
            try:
                assert os.read(descriptor, 32) == b"synthetic"
            finally:
                os.close(descriptor)
            assert sorted(os.listdir(directory)) == ["value"]
            os.fsync(directory)
        assert ancestor.stat().st_mode & 0o777 == 0o111
    finally:
        ancestor.chmod(0o700)


def test_traversal_only_ancestor_symlink_is_still_rejected(tmp_path: Path) -> None:
    ancestor = tmp_path / "ancestor"
    ancestor.mkdir(mode=0o700)
    leaf = ancestor / "leaf"
    leaf.mkdir(mode=0o700)
    alias = tmp_path / "alias"
    alias.symlink_to(ancestor, target_is_directory=True)
    with (
        pytest.raises(handoff.CpuHandoffError, match="DIRECTORY_INVALID"),
        handoff._directory(alias / "leaf", owner=owner(), uid=os.geteuid(), mode=0o700),
    ):
        pass


def test_retained_ancestor_inode_still_rejects_name_replacement(tmp_path: Path) -> None:
    ancestor = tmp_path / "ancestor"
    ancestor.mkdir(mode=0o700)
    leaf = ancestor / "leaf"
    leaf.mkdir(mode=0o700)
    with (
        pytest.raises(handoff.CpuHandoffError, match="DIRECTORY_CHANGED"),
        handoff._directory(leaf, owner=owner(), uid=os.geteuid(), mode=0o700),
    ):
        ancestor.rename(tmp_path / "old-ancestor")
        ancestor.mkdir(mode=0o700)


def test_path_only_open_does_not_admit_writable_ancestors(tmp_path: Path) -> None:
    ancestor = tmp_path / "writable-ancestor"
    ancestor.mkdir(mode=0o777)
    ancestor.chmod(0o777)
    leaf = ancestor / "leaf"
    leaf.mkdir(mode=0o700)
    with (
        pytest.raises(handoff.CpuHandoffError, match="DIRECTORY_INVALID"),
        handoff._directory(leaf, owner=owner(), uid=os.geteuid(), mode=0o700),
    ):
        pass


def fake_root_boundary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[Path, Path, LocalExperimentInput]:
    """Collapse root/owner UID only for file-copy logic; real privilege is NOT tested."""
    owner_root, runtime_root = tmp_path / "owner", tmp_path / "runtime"
    owner_root.mkdir(mode=0o700)
    runtime_root.mkdir(mode=0o750)
    request = experiment_request()
    prepared = ProtectedExperimentWorkspace(owner_root).prepare(
        request, execution_id=EXECUTION, created_at=NOW
    )
    ProtectedExperimentWorkspace(owner_root).claim(prepared, request)
    original = handoff._directory
    current_uid = os.geteuid()

    @contextmanager
    def directory(path: Path, **kwargs: Any) -> Iterator[int]:
        # Host ancestors remain real UID 0. Body owns synthetic current-user files.
        handoff._ROOT_UID = 0
        try:
            with original(path, **kwargs) as descriptor:
                handoff._ROOT_UID = current_uid
                try:
                    yield descriptor
                finally:
                    handoff._ROOT_UID = 0
        finally:
            handoff._ROOT_UID = current_uid

    monkeypatch.setattr(handoff, "OWNER_ROOT", owner_root)
    monkeypatch.setattr(handoff, "RUNTIME_ROOT", runtime_root)
    monkeypatch.setattr(handoff, "_ROOT_UID", current_uid)
    monkeypatch.setattr(handoff, "fixed_owner_identity", owner)
    monkeypatch.setattr(handoff, "_directory", directory)
    return owner_root, runtime_root, prepared


def test_fake_root_stages_exclusively_and_owner_materializes_private_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner_root, runtime_root, prepared = fake_root_boundary(monkeypatch, tmp_path)
    handoff.prepare_cpu_handoff(EXECUTION)
    staged = runtime_root / EXECUTION
    assert staged.stat().st_mode & 0o777 == 0o750
    assert (staged / "input.json").read_bytes() == (
        prepared.workspace / "request.json"
    ).read_bytes()
    assert (staged / "input.json").stat().st_mode & 0o777 == 0o600
    assert (staged / "output.json").stat().st_mode & 0o777 == 0o640
    with pytest.raises(handoff.CpuHandoffError, match="HANDOFF_EXISTS"):
        handoff.prepare_cpu_handoff(EXECUTION)
    # Transport only: schema/result closure is owned by the existing application.
    (staged / "output.json").write_bytes(b"synthetic result")
    handoff.materialize_cpu_output(prepared)
    assert (owner_root / EXECUTION / "result.json").read_bytes() == b"synthetic result"
    assert (owner_root / EXECUTION / "result.json").stat().st_mode & 0o777 == 0o600
    with pytest.raises(ExperimentWorkspaceError):
        handoff.materialize_cpu_output(prepared)


@pytest.mark.parametrize("kind", ["missing_marker", "marker_payload", "wrong_request"])
def test_fake_root_admits_only_reserved_exact_canonical_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    _owner_root, runtime_root, prepared = fake_root_boundary(monkeypatch, tmp_path)
    marker = prepared.workspace / ".launch-started"
    if kind == "missing_marker":
        marker.unlink()
    elif kind == "marker_payload":
        marker.write_bytes(b"not an empty reservation")
    else:
        (prepared.workspace / "request.json").write_bytes(b'{"sensitive":"test-content"}')
    with pytest.raises((handoff.CpuHandoffError, SchemaValidationError)):
        handoff.prepare_cpu_handoff(EXECUTION)
    assert list(runtime_root.iterdir()) == []


def test_root_entry_redacts_schema_payload_and_traceback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def bad_schema(_identity: str) -> None:
        raise SchemaValidationError("sensitive-test-content must not enter stderr")

    monkeypatch.setattr(handoff, "prepare_cpu_handoff", bad_schema)
    monkeypatch.setattr(sys, "argv", ["prepare", "--execution-id", EXECUTION])
    with pytest.raises(SystemExit) as observed:
        handoff.main()
    assert observed.value.code == 1
    assert capsys.readouterr() == ("", "")
