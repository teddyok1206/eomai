"""Real temporary private files/shared flock; synthetic model and OS observations only."""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from eom_catalog_service import embedding_native_cpu as leaf
from eom_catalog_service.embedding_encoder_adapter import encode_private_chat_query
from eom_identifiers import canonical_json_bytes, sha256_bytes, sha256_file
from eom_orchestrator import native_embedding_cpu_execution as cpu
from eom_orchestrator import native_private_chat_query_handoff as handoff
from eom_orchestrator import native_private_chat_query_systemd as launcher
from eom_orchestrator.inference_transfer_cpu_handoff import (
    CpuHandoffError,
    CpuHandoffIdentity,
    protected_cpu_handoff_directory,
    read_protected_cpu_handoff_member,
)
from eom_workflow.private_chat_query_execution import (
    PrivateChatQueryExecutionPolicy,
    PrivateChatQueryWorkflowRequest,
)
from eom_workflow.private_chat_query_publication import PrivateChatQueryLaunchAssociation

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_native_cpu import PINS
from tests.unit.test_embedding_private_chat_query import backend
from tests.unit.test_inference_transfer_cpu_systemd import observation
from tests.unit.test_native_embedding_query_handoff import prepared as reference_prepared
from tests.unit.test_private_chat_query_basis import TEXT
from tests.unit.test_private_chat_query_publication import launch_case

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def prepared():
    request, policy, bundle, native, launch = launch_case()
    resources = reference_prepared().workflow_request.resource_profile
    policy = PrivateChatQueryExecutionPolicy.model_validate(
        seal(
            policy.model_dump(mode="json")
            | {"resource_profile": resources.model_dump(mode="json")},
            "policy_sha256",
        )
    )
    request = PrivateChatQueryWorkflowRequest.model_validate(
        seal(
            request.model_dump(mode="json")
            | {
                "resource_profile": resources.model_dump(mode="json"),
                "native_execution_policy": request.native_execution_policy.model_dump(mode="json")
                | {"sha256": sha256_bytes(canonical_json_bytes(policy))},
                "native_execution_policy_sha256": policy.policy_sha256,
            },
            "request_sha256",
        )
    )
    launch = PrivateChatQueryLaunchAssociation.model_validate(
        seal(
            launch.model_dump(mode="json")
            | {
                "workflow_request_sha256": request.request_sha256,
                "resource_profile_sha256": resources.resource_profile_sha256,
            },
            "association_sha256",
        )
    )
    return handoff.PreparedNativePrivateChatQuery(
        native.job_id.removeprefix("job_"), request, policy, bundle, launch, native
    )


@pytest.fixture
def staged(tmp_path, monkeypatch, prepared):
    owner = tmp_path / "private-owner"
    owner.mkdir(mode=0o700)
    monkeypatch.setattr(handoff, "OWNER_ROOT", owner)
    monkeypatch.setattr(handoff, "RUNTIME_ROOT", tmp_path / "private-runtime")
    monkeypatch.setattr(
        handoff, "fixed_owner_identity", lambda: CpuHandoffIdentity(os.geteuid(), os.getegid())
    )
    handoff.require_native_private_query_owner_root()
    handoff.stage_native_private_chat_query(prepared)
    return prepared


def test_exact_five_controls_and_marking_replay_keep_private_question_local(staged):
    assert {path.name for path in staged.workspace.iterdir()} == {
        "workflow.json",
        "policy.json",
        "bundle.json",
        "association.json",
        "input.json",
    }
    before = {p.name: p.stat().st_ino for p in staged.workspace.iterdir()}
    handoff.stage_native_private_chat_query(staged)
    assert before == {p.name: p.stat().st_ino for p in staged.workspace.iterdir()}
    for name, raw in staged.owner_members():
        assert (canonical_json_bytes(TEXT) in raw) == (name == "input.json")
        assert (staged.workspace / name).read_bytes() == raw
    handoff.mark_native_private_query_launch_started(staged)
    handoff.mark_native_private_query_launch_started(staged)
    assert (staged.workspace / ".launch-started").read_bytes() == (
        staged.association.association_sha256.encode("ascii")
    )


@pytest.mark.parametrize(
    "member", ["workflow.json", "policy.json", "bundle.json", "association.json", "input.json"]
)
@pytest.mark.parametrize("fault", ["bytes", "symlink", "mode"])
def test_changed_local_control_cannot_be_overwritten_or_marked(staged, member, fault):
    path = staged.workspace / member
    if fault == "bytes":
        path.write_bytes(b'{"private":"must not escape"}')
    elif fault == "mode":
        path.chmod(0o644)
    else:
        path.unlink()
        path.symlink_to(staged.workspace / "missing")
    with pytest.raises((ValueError, CpuHandoffError)):
        handoff.stage_native_private_chat_query(staged)
    with pytest.raises(handoff.NativePrivateQueryHandoffError) as error:
        handoff.mark_native_private_query_launch_started(staged)
    assert "must not escape" not in str(error.value) and TEXT not in str(error.value)
    assert not (staged.workspace / ".launch-started").exists()


@pytest.mark.parametrize("fault", ["id", "reference", "resource", "native_bool"])
def test_prepared_revalidates_copied_values_and_cannot_borrow_reference_purpose(prepared, fault):
    values = {}
    if fault == "id":
        values["execution_id"] = "f" * 32
    elif fault == "reference":
        values["workflow_request"] = reference_prepared().workflow_request
    elif fault == "resource":
        values["workflow_request"] = prepared.workflow_request.model_copy(
            update={
                "resource_profile": prepared.workflow_request.resource_profile.model_copy(
                    update={"threads": 3}
                )
            }
        )
    else:
        values["request"] = prepared.request.model_copy(update={"threads": True})
    with pytest.raises(
        handoff.NativePrivateQueryHandoffError, match=r"^NATIVE_PRIVATE_QUERY_INPUT_INVALID$"
    ):
        replace(prepared, **values)


def test_nonroot_refused_before_private_read_or_runtime_creation(staged, monkeypatch):
    monkeypatch.setattr(handoff.os, "geteuid", lambda: 12345)
    with pytest.raises(handoff.NativePrivateQueryHandoffError, match="ROOT_REQUIRED"):
        handoff.prepare_native_private_query_handoff(staged.execution_id)
    assert not handoff.RUNTIME_ROOT.exists()


def test_root_handoff_requires_original_mark_and_only_transfers_native_input(staged, monkeypatch):
    actual = os.geteuid()
    identity = CpuHandoffIdentity(actual, os.getegid())
    monkeypatch.setattr(handoff, "fixed_owner_identity", lambda: identity)
    monkeypatch.setattr(handoff.os, "geteuid", lambda: 0)
    calls = []
    monkeypatch.setattr(
        handoff,
        "create_native_cpu_descriptor_handoff",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    with pytest.raises((ValueError, CpuHandoffError)):
        handoff.prepare_native_private_query_handoff(staged.execution_id)
    assert calls == []
    # Root handoff consumes an owner-written marker; this test does not impersonate
    # an OS owner or perform chown/model work. The descriptor port is synthetic.
    marker = staged.workspace / ".launch-started"
    marker.write_bytes(staged.association.association_sha256.encode("ascii"))
    marker.chmod(0o600)
    handoff.prepare_native_private_query_handoff(staged.execution_id)
    assert calls == [
        (
            (handoff.RUNTIME_ROOT, staged.execution_id, canonical_json_bytes(staged.request)),
            {"owner": identity},
        )
    ]


def runtime_output(staged, monkeypatch):
    uid = os.geteuid()

    def directory(path, **values):
        if values["uid"] == 0:
            values["uid"] = uid
        return protected_cpu_handoff_directory(path, **values)

    def read(fd, name, **values):
        if values["uid"] == 0:
            values["uid"] = uid
        return read_protected_cpu_handoff_member(fd, name, **values)

    monkeypatch.setattr(handoff, "protected_cpu_handoff_directory", directory)
    monkeypatch.setattr(handoff, "read_protected_cpu_handoff_member", read)
    handoff.RUNTIME_ROOT.mkdir(mode=0o700)
    root = handoff.RUNTIME_ROOT / staged.execution_id
    root.mkdir(mode=0o750)
    root.chmod(0o750)
    encoded = encode_private_chat_query(staged.request, backend(staged.request))
    for name, raw in (
        ("result.json", canonical_json_bytes(encoded.result)),
        ("vectors.f32", encoded.vectors),
    ):
        path = root / name
        path.write_bytes(raw)
        path.chmod(0o640)
    return root, encoded


def test_exact_private_result_hash_finite_l2_row_and_local_publication_inputs(staged, monkeypatch):
    _, encoded = runtime_output(staged, monkeypatch)
    result = handoff.materialize_native_private_query_output(staged)
    assert result == encoded.result
    assert (staged.workspace / "result.json").read_bytes() == canonical_json_bytes(result)
    assert (staged.workspace / "vectors.f32").read_bytes() == encoded.vectors
    assert (staged.workspace / "result.json").stat().st_mode & 0o777 == 0o600
    handoff.materialize_native_private_query_output(staged)


def test_private_handoff_result_uses_existing_artifact_owner_without_committing_input(
    staged, monkeypatch
):
    from eom_orchestrator.embedding_artifact_store import EmbeddingArtifactStore
    from eom_orchestrator.file_set_control_artifacts import ControlFileSetIdentity

    from tests.unit.test_private_chat_query_publication import IdentifiedPublisher

    _, encoded = runtime_output(staged, monkeypatch)
    handoff.materialize_native_private_query_output(staged)
    publisher = IdentifiedPublisher()
    store = EmbeddingArtifactStore(publisher, source_commit="a" * 40)
    kwargs = {
        "workflow_request": staged.workflow_request,
        "policy": staged.policy,
        "bundle": staged.bundle,
        "launch": staged.association,
        "request": staged.request,
        "workspace": staged.workspace,
        "created_at": staged.association.launched_at,
        "identity": ControlFileSetIdentity(
            "job_" + "9" * 32, "artifact_" + "a" * 32, "rev_" + "b" * 32
        ),
        "expected_result_sha256": encoded.result.result_sha256,
    }
    first = store.publish_private_chat_query(**kwargs)
    assert store.publish_private_chat_query(**kwargs) == first
    assert len(publisher.saved) == 1
    members = publisher.calls[0]["members"]
    assert tuple(m.file_name for m in members) == (
        "intent.json",
        "result.json",
        "shard.json",
        "vectors.f32",
    )
    assert all(canonical_json_bytes(TEXT) not in member.source.read_bytes() for member in members)


@pytest.mark.parametrize("fault", ["json", "noncanonical", "job", "vectors", "extra_row"])
def test_changed_result_is_never_materialized_for_commit(staged, monkeypatch, fault):
    root, encoded = runtime_output(staged, monkeypatch)
    if fault in {"vectors", "extra_row"}:
        (root / "vectors.f32").write_bytes(
            b"\x00" * len(encoded.vectors) if fault == "vectors" else encoded.vectors * 2
        )
    elif fault == "noncanonical":
        (root / "result.json").write_bytes(canonical_json_bytes(encoded.result) + b"\n")
    elif fault == "job":
        result = seal(
            encoded.result.model_dump(mode="json") | {"job_id": "job_" + "f" * 32}, "result_sha256"
        )
        (root / "result.json").write_bytes(canonical_json_bytes(result))
    else:
        (root / "result.json").write_bytes(b'{"private":"must not escape"}')
    with pytest.raises((ValueError, CpuHandoffError)) as error:
        handoff.materialize_native_private_query_output(staged)
    assert TEXT not in str(error.value) and "must not escape" not in str(error.value)
    assert not (staged.workspace / "result.json").exists()
    assert not (staged.workspace / "vectors.f32").exists()


@pytest.mark.parametrize("replay", [False, True])
def test_shared_lifecycle_one_private_start_or_exact_terminal_read(
    staged, tmp_path, monkeypatch, replay
):
    monkeypatch.setattr(cpu, "CAPACITY_ROOT", handoff.OWNER_ROOT)
    monkeypatch.setattr(cpu, "fixed_owner_identity", handoff.fixed_owner_identity)
    monkeypatch.setattr(launcher, "fixed_owner_identity", handoff.fixed_owner_identity)
    monkeypatch.setattr(cpu, "require_no_active_native_cpu_execution", lambda: None)
    monkeypatch.setattr(cpu, "require_empty_native_cpu_cgroup", lambda *_: None)
    monkeypatch.setattr(
        launcher.FixedNativePrivateQueryLauncher, "assert_current_runtime", lambda *_: None
    )
    success = observation("success"), observation("success", main=True)
    reads = iter(
        [success, success]
        if replay
        else [(observation("fresh"), observation("fresh", main=True)), success, success]
    )
    monkeypatch.setattr(
        launcher.FixedNativePrivateQueryLauncher, "_observe", lambda *_: next(reads)
    )
    handoff.mark_native_private_query_launch_started(staged)
    _, encoded = runtime_output(staged, monkeypatch)
    calls = []
    monkeypatch.setattr(
        cpu.subprocess,
        "run",
        lambda args, **kw: calls.append(args) or subprocess.CompletedProcess(args, 0, b"", b""),
    )
    owner = launcher.FixedNativePrivateQueryLauncher("a" * 64, "b" * 64, lambda: None)
    assert owner.run(staged) == encoded.result
    assert calls == (
        []
        if replay
        else [
            (
                "/usr/bin/systemctl",
                "--no-ask-password",
                "start",
                f"eom-embedding-native-cpu-private-chat-query@{staged.execution_id}.service",
            )
        ]
    )
    assert (staged.workspace / ".dispatch-attempted").exists() is (not replay)


@pytest.mark.parametrize("state", ["running", "failed", "timeout"])
def test_private_uncertain_or_failed_original_handle_never_starts(
    prepared, tmp_path, monkeypatch, state
):
    tmp_path.chmod(0o700)
    monkeypatch.setattr(cpu, "CAPACITY_ROOT", tmp_path)
    monkeypatch.setattr(
        cpu, "fixed_owner_identity", lambda: CpuHandoffIdentity(os.geteuid(), os.getegid())
    )
    monkeypatch.setattr(
        launcher.FixedNativePrivateQueryLauncher, "assert_current_runtime", lambda *_: None
    )
    monkeypatch.setattr(cpu, "require_empty_native_cpu_cgroup", lambda *_: None)
    pair = observation("success"), observation(state, main=True)
    monkeypatch.setattr(launcher.FixedNativePrivateQueryLauncher, "_observe", lambda *_: pair)
    monkeypatch.setattr(cpu.subprocess, "run", lambda *_a, **_k: pytest.fail("must not start"))
    with pytest.raises(
        launcher.NativePrivateQueryLaunchError,
        match="KNOWN_FAILED" if state == "failed" else "UNCERTAIN",
    ):
        launcher.FixedNativePrivateQueryLauncher("a" * 64, "b" * 64, lambda: None).run(prepared)


def test_fixed_templates_and_private_leaf_keep_external_authority_out(monkeypatch):
    for name, digest in (
        (launcher.PREPARE_TEMPLATE, launcher.PREPARE_TEMPLATE_SHA256),
        (launcher.QUERY_TEMPLATE, launcher.QUERY_TEMPLATE_SHA256),
    ):
        assert sha256_file(ROOT / "infra/systemd" / name) == "sha256:" + digest
    source = (ROOT / "infra/systemd" / launcher.QUERY_TEMPLATE).read_text()
    assert "embedding_native_cpu PRIVATE_CHAT_QUERY " in source
    for required in (
        "PrivateNetwork=yes",
        "PrivateDevices=yes",
        "ProtectSystem=strict",
        "Restart=no",
        "MemoryMax=6G",
        "StandardError=file:/run/eom-embedding-native-private-chat-query/%i/vectors.f32",
    ):
        assert required in source
    assert "ReadWritePaths" not in source and "SupplementaryGroups" not in source
    selected, pins = leaf._owner_arguments(("PRIVATE_CHAT_QUERY", *PINS))
    assert selected == "PRIVATE_CHAT_QUERY" and pins.configuration_id == PINS[0]
    calls = []
    monkeypatch.setattr(
        leaf, "run_native_embedding_private_chat_query", lambda **kwargs: calls.append(kwargs)
    )
    monkeypatch.setattr(
        leaf,
        "run_native_embedding_reference_query",
        lambda **kw: pytest.fail("reference substitute"),
    )
    monkeypatch.setattr(
        leaf, "run_native_embedding_index", lambda **kw: pytest.fail("index substitute")
    )
    monkeypatch.setattr(sys, "argv", ["fixed-private-unit", "PRIVATE_CHAT_QUERY", *PINS])
    assert leaf.main() == 0 and len(calls) == 1 and calls[0]["profile"] == "CPU_INDEX_FP32"


@pytest.mark.parametrize(
    "name",
    [
        "eom-embedding-native-cpu-private-chat-query@" + "a" * 32 + ".service",
        "eom-embedding-native-private-chat-query-prepare@" + "b" * 32 + ".service",
    ],
)
def test_shared_capacity_discovers_private_active_or_orphan_units(monkeypatch, name):
    assert cpu._UNIT.fullmatch(name) is not None

    def active(args, **kw):
        assert any("private-chat-query" in arg for arg in args)
        return subprocess.CompletedProcess(
            args, 0, (name + " loaded activating start\n").encode(), b""
        )

    monkeypatch.setattr(cpu.subprocess, "run", active)
    with pytest.raises(cpu.NativeCpuExecutionError, match="NATIVE_CPU_BUSY"):
        cpu.require_no_active_native_cpu_execution()


@pytest.mark.parametrize("layout", ["missing", "file", "symlink", "writable"])
def test_private_owner_preflight_never_creates_or_repairs_layout(tmp_path, monkeypatch, layout):
    root = tmp_path / "private-owner"
    if layout == "file":
        root.write_bytes(b"not a directory")
    elif layout == "symlink":
        root.symlink_to(tmp_path / "absent", target_is_directory=True)
    elif layout == "writable":
        root.mkdir(mode=0o770)
        root.chmod(0o770)
    monkeypatch.setattr(handoff, "OWNER_ROOT", root)
    monkeypatch.setattr(
        handoff, "fixed_owner_identity", lambda: CpuHandoffIdentity(os.geteuid(), os.getegid())
    )
    before = root.lstat() if layout != "missing" else None
    with pytest.raises(handoff.NativePrivateQueryHandoffError, match="OWNER_LAYOUT_INVALID"):
        handoff.require_native_private_query_owner_root()
    assert (root.lstat() if layout != "missing" else None) == before
    assert layout != "missing" or not root.exists()


def test_private_staging_denies_a_foreign_effective_owner_before_any_creation(
    tmp_path, monkeypatch, prepared
):
    monkeypatch.setattr(handoff, "OWNER_ROOT", tmp_path / "absent")
    monkeypatch.setattr(
        handoff, "fixed_owner_identity", lambda: CpuHandoffIdentity(os.geteuid() + 1, os.getegid())
    )
    with pytest.raises(handoff.NativePrivateQueryHandoffError, match="OWNER_REQUIRED"):
        handoff.stage_native_private_chat_query(prepared)
    assert not handoff.OWNER_ROOT.exists()


def test_private_runtime_checks_distinct_purpose_environment_before_observation(monkeypatch):
    checked = []
    monkeypatch.setattr(
        launcher, "require_fixed_cpu_unit_template", lambda *args: checked.append(args)
    )

    def environment(path, digest):
        checked.append((path, digest))
        if path.name == "embedding-native-private-chat-query-owner.env":
            raise ValueError("synthetic private purpose is not installed")

    monkeypatch.setattr(launcher, "require_native_cpu_environment_file", environment)
    monkeypatch.setattr(
        launcher.FixedNativePrivateQueryLauncher, "_observe", lambda *_: pytest.fail("not admitted")
    )
    owner = launcher.FixedNativePrivateQueryLauncher(
        "a" * 64, "b" * 64, lambda: pytest.fail("not admitted")
    )
    with pytest.raises(ValueError, match="private purpose is not installed"):
        owner.observe("7" * 32)
    assert checked == [
        (launcher.PREPARE_TEMPLATE, launcher.PREPARE_TEMPLATE_SHA256),
        (launcher.QUERY_TEMPLATE, launcher.QUERY_TEMPLATE_SHA256),
        (Path("/etc/eom/embedding-native-cpu.env"), "a" * 64),
        (Path("/etc/eom/embedding-native-private-chat-query-owner.env"), "b" * 64),
    ]


@pytest.mark.parametrize("failure", ["timeout", "new_invocation", "consumed_dispatch"])
def test_timeout_identity_drift_and_consumed_dispatch_never_authorize_another_start(
    staged, monkeypatch, failure
):
    monkeypatch.setattr(cpu, "CAPACITY_ROOT", handoff.OWNER_ROOT)
    monkeypatch.setattr(cpu, "fixed_owner_identity", handoff.fixed_owner_identity)
    monkeypatch.setattr(launcher, "fixed_owner_identity", handoff.fixed_owner_identity)
    monkeypatch.setattr(cpu, "require_no_active_native_cpu_execution", lambda: None)
    monkeypatch.setattr(cpu, "require_empty_native_cpu_cgroup", lambda *_: None)
    monkeypatch.setattr(
        launcher.FixedNativePrivateQueryLauncher, "assert_current_runtime", lambda *_: None
    )
    handoff.mark_native_private_query_launch_started(staged)
    _, encoded = runtime_output(staged, monkeypatch)
    fresh = observation("fresh"), observation("fresh", main=True)
    success = observation("success"), observation("success", main=True)
    changed = success[0], replace(success[1], invocation_id="f" * 32)
    if failure == "consumed_dispatch":
        # A reboot/fresh systemd record does not erase the original durable start.
        from eom_orchestrator.inference_transfer_cpu_handoff import claim_native_cpu_dispatch

        claim_native_cpu_dispatch(
            staged.workspace,
            staged.association.association_sha256,
            owner=handoff.fixed_owner_identity(),
        )
    reads = iter([fresh, success, changed if failure == "new_invocation" else success])
    monkeypatch.setattr(
        launcher.FixedNativePrivateQueryLauncher, "_observe", lambda *_: next(reads)
    )
    starts = []

    def start(args, **kw):
        starts.append(args)
        if failure == "timeout":
            raise subprocess.TimeoutExpired(args, 210)
        return subprocess.CompletedProcess(args, 0, b"", b"")

    monkeypatch.setattr(cpu.subprocess, "run", start)
    owner = launcher.FixedNativePrivateQueryLauncher("a" * 64, "b" * 64, lambda: None)
    if failure == "timeout":
        assert owner.run(staged) == encoded.result
    else:
        with pytest.raises(launcher.NativePrivateQueryLaunchError, match="UNCERTAIN"):
            owner.run(staged)
    assert len(starts) == (0 if failure == "consumed_dispatch" else 1)
