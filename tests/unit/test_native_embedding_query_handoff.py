"""Actual private temporary files, synthetic root ownership/model; not OS/runtime admission."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from eom_catalog_service.embedding_encoder_adapter import encode_reference_query_batch
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator import native_embedding_query_handoff as handoff
from eom_orchestrator.inference_transfer_cpu_handoff import (
    CpuHandoffError,
    CpuHandoffIdentity,
    protected_cpu_handoff_directory,
    read_protected_cpu_handoff_member,
)
from eom_workflow.local_embedding_execution_policy import LocalEmbeddingResourceProfile
from eom_workflow.reference_query_execution import (
    parse_reference_query_execution_policy,
    parse_reference_query_launch_association,
    parse_reference_query_workflow_request,
)
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_incremental_encoding import SyntheticNativeBackend
from tests.unit.test_reference_query_execution_contracts import case


def prepared() -> handoff.PreparedNativeQuery:
    base = case()
    resources = LocalEmbeddingResourceProfile.model_validate(
        seal(
            base.policy.resource_profile.model_dump(mode="json")
            | {"timeout_seconds": 180, "tasks_max": 64, "output_max_bytes": 64 * 1024**2},
            "resource_profile_sha256",
        )
    )
    policy = parse_reference_query_execution_policy(
        seal(
            base.policy.model_dump(mode="json")
            | {"resource_profile": resources.model_dump(mode="json")},
            "policy_sha256",
        )
    )
    pointer = base.request.native_execution_policy.model_dump(mode="json") | {
        "sha256": sha256_bytes(canonical_json_bytes(policy.model_dump(mode="json")))
    }
    request = parse_reference_query_workflow_request(
        seal(
            base.request.model_dump(mode="json")
            | {
                "resource_profile": resources.model_dump(mode="json"),
                "native_execution_policy": pointer,
                "native_execution_policy_sha256": policy.policy_sha256,
            },
            "request_sha256",
        )
    )
    association = parse_reference_query_launch_association(
        seal(
            base.launch.model_dump(mode="json")
            | {
                "workflow_request_sha256": request.request_sha256,
                "resource_profile_sha256": resources.resource_profile_sha256,
            },
            "association_sha256",
        )
    )
    return handoff.PreparedNativeQuery(
        base.native_input.job_id.removeprefix("job_"),
        request,
        policy,
        base.bundle,
        association,
        base.native_input,
    )


@pytest.mark.parametrize("layout", ("valid", "missing", "file", "symlink", "writable"))
def test_owner_root_preflight_uses_real_layout_without_creation_or_repair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, layout: str
) -> None:
    root = tmp_path / "query"
    if layout == "file":
        root.write_bytes(b"not a directory")
    elif layout == "symlink":
        target = tmp_path / "other"
        target.mkdir(mode=0o700)
        root.symlink_to(target, target_is_directory=True)
    elif layout != "missing":
        root.mkdir(mode=0o700)
        if layout == "writable":
            root.chmod(0o770)
    monkeypatch.setattr(handoff, "OWNER_ROOT", root)
    monkeypatch.setattr(
        handoff, "fixed_owner_identity", lambda: CpuHandoffIdentity(os.geteuid(), os.getegid())
    )
    before = root.lstat() if layout != "missing" else None
    if layout == "valid":
        handoff.require_native_query_owner_root()
        assert tuple(root.iterdir()) == ()
    else:
        with pytest.raises(handoff.NativeQueryHandoffError) as raised:
            handoff.require_native_query_owner_root()
        assert raised.value.code == "NATIVE_QUERY_OWNER_LAYOUT_INVALID"
        assert str(root) not in str(raised.value)
    assert (root.lstat() if layout != "missing" else None) == before
    if layout == "missing":
        assert not root.exists()


@pytest.fixture
def staged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> handoff.PreparedNativeQuery:
    owner = tmp_path / "owner"
    owner.mkdir(mode=0o700)
    monkeypatch.setattr(handoff, "OWNER_ROOT", owner)
    monkeypatch.setattr(handoff, "RUNTIME_ROOT", tmp_path / "runtime")
    monkeypatch.setattr(
        handoff, "fixed_owner_identity", lambda: CpuHandoffIdentity(os.geteuid(), os.getegid())
    )
    result = prepared()
    handoff.stage_native_query(result)
    return result


def synthetic_output(value: handoff.PreparedNativeQuery, monkeypatch: pytest.MonkeyPatch) -> bytes:
    actual_uid = os.geteuid()

    def directory(path: Path, **values: Any) -> Any:
        if values["uid"] == 0:
            values["uid"] = actual_uid
        return protected_cpu_handoff_directory(path, **values)

    def read(fd: int, name: str, **values: Any) -> bytes:
        if values["uid"] == 0:
            values["uid"] = actual_uid
        return read_protected_cpu_handoff_member(fd, name, **values)

    monkeypatch.setattr(handoff, "protected_cpu_handoff_directory", directory)
    monkeypatch.setattr(handoff, "read_protected_cpu_handoff_member", read)
    handoff.RUNTIME_ROOT.mkdir(mode=0o700)
    output = handoff.RUNTIME_ROOT / value.execution_id
    output.mkdir(mode=0o750)
    output.chmod(0o750)
    backend = SyntheticNativeBackend(value.request.spaces.query)
    backend.batch_size = backend.threads = 4
    encoded = encode_reference_query_batch(value.request, backend)
    assert backend.calls == [(tuple(row.text for row in value.request.rows), "QUERY")]
    for name, raw in (
        ("result.json", canonical_json_bytes(encoded.result.model_dump(mode="json"))),
        ("vectors.f32", encoded.vectors),
    ):
        member = output / name
        member.write_bytes(raw)
        member.chmod(0o640)
    return encoded.vectors


def test_five_typed_controls_staged_exactly_but_no_launch_or_actor_sent_to_worker(
    staged: handoff.PreparedNativeQuery,
) -> None:
    expected = {"workflow.json", "policy.json", "bundle.json", "association.json", "input.json"}
    assert {p.name for p in staged.workspace.iterdir()} == expected
    raw = (staged.workspace / "input.json").read_bytes()
    assert (
        b"operator_id" not in raw and b"lease_token" not in raw and b"policy_revision_id" not in raw
    )
    inode = (staged.workspace / "input.json").stat().st_ino
    handoff.stage_native_query(staged)
    assert (staged.workspace / "input.json").stat().st_ino == inode
    handoff.mark_native_query_launch_started(staged)
    handoff.mark_native_query_launch_started(staged)
    assert (
        staged.workspace / ".launch-started"
    ).read_bytes() == staged.association.association_sha256.encode("ascii")


@pytest.mark.parametrize(
    "member", ("workflow.json", "policy.json", "bundle.json", "association.json", "input.json")
)
def test_partial_or_changed_control_is_never_overwritten_or_admitted(
    staged: handoff.PreparedNativeQuery,
    member: str,
) -> None:
    (staged.workspace / member).write_bytes(b"{")
    with pytest.raises((ValueError, CpuHandoffError), match="MEMBER_CONFLICT"):
        handoff.stage_native_query(staged)
    with pytest.raises((ValueError, CpuHandoffError)):
        handoff.mark_native_query_launch_started(staged)
    assert (staged.workspace / member).read_bytes() == b"{"


def test_nonroot_cannot_prepare_or_make_a_runtime_handoff(
    staged: handoff.PreparedNativeQuery,
) -> None:
    assert os.geteuid() != 0
    with pytest.raises(handoff.NativeQueryHandoffError, match="ROOT_REQUIRED"):
        handoff.prepare_native_query_handoff(staged.execution_id)
    assert not handoff.RUNTIME_ROOT.exists()


def test_exact_query_result_copies_once_and_replay_reuses_same_bytes(
    staged: handoff.PreparedNativeQuery,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binary = synthetic_output(staged, monkeypatch)
    first = handoff.materialize_native_query_output(staged)
    inode = (staged.workspace / "vectors.f32").stat().st_ino
    assert handoff.materialize_native_query_output(staged) == first
    assert (staged.workspace / "vectors.f32").stat().st_ino == inode
    assert (staged.workspace / "vectors.f32").read_bytes() == binary
    assert (
        first.shard.space.purpose == "QUERY"
        and first.request_sha256 == staged.request.request_sha256
    )


@pytest.mark.parametrize("fault", ("hash", "mode", "symlink", "oversize", "input", "policy"))
def test_corruption_and_changed_sources_never_materialize_success(
    staged: handoff.PreparedNativeQuery,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    synthetic_output(staged, monkeypatch)
    member = handoff.RUNTIME_ROOT / staged.execution_id / "vectors.f32"
    if fault == "hash":
        member.write_bytes(b"\x00" * member.stat().st_size)
    elif fault == "mode":
        member.chmod(0o644)
    elif fault == "symlink":
        member.rename(member.with_name("original.f32"))
        member.symlink_to(member.with_name("original.f32"))
    elif fault == "oversize":
        member.write_bytes(member.read_bytes() + b"\x00" * 4)
    else:
        (staged.workspace / ("input.json" if fault == "input" else "policy.json")).write_bytes(
            b"{}"
        )
    with pytest.raises((ValueError, CpuHandoffError, SchemaError)):
        handoff.materialize_native_query_output(staged)
    assert not (staged.workspace / "result.json").exists()


@pytest.mark.parametrize("value", ("../x", "x" * 32, "a" * 31, "a" * 33, True))
def test_execution_suffix_is_not_an_arbitrary_path(value: Any) -> None:
    with pytest.raises(ValueError):
        handoff.validate_native_query_execution_id(value)


def test_installed_resource_profile_must_match_the_fixed_unit_not_a_partial_recipe() -> None:
    base = case()
    with pytest.raises(ValueError, match="RESOURCE_PROFILE_INVALID"):
        handoff.PreparedNativeQuery(
            base.native_input.job_id.removeprefix("job_"),
            base.request,
            base.policy,
            base.bundle,
            base.launch,
            base.native_input,
        )
    valid = prepared()
    with pytest.raises(ValueError, match="ASSOCIATION_INPUT_MISMATCH"):
        handoff.PreparedNativeQuery(
            "f" * 32,
            valid.workflow_request,
            valid.policy,
            valid.bundle,
            valid.association,
            valid.request,
        )
