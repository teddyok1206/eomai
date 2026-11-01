"""Protected local files with synthetic query2 math; no source, claim, CPU or GPU grant."""

import os
from dataclasses import FrozenInstanceError
from types import SimpleNamespace as NS

import pytest
from eom_catalog_service.embedding_encoder_adapter import encode_public_solution_query
from eom_orchestrator.inference_transfer_cpu_handoff import CpuHandoffIdentity
from eom_workflow_runner import private_chat_query_batch_material as material
from eom_workflow_runner import query_batch_binding as bindings
from eom_workflow_runner import reference_query_batch_binding as public_bindings
from eom_workflow_runner.reference_query_batch_material import PreparedBatchReferenceQuery

from tests.unit.private_chat_batch_plan_fixtures import private_planning_case
from tests.unit.test_embedding_incremental_encoding import SyntheticNativeBackend
from tests.unit.test_private_chat_public_query_workflow import public_query_completed
from tests.unit.test_private_chat_query_basis import TEXT
from tests.unit.test_private_chat_query_workflow import completed as completed
from tests.unit.test_public_solution_reference_query_execution import public_workflow_case


def prepared(value):
    return material.PreparedBatchPrivateChatQuery(
        value.request, value.policy, value.bundle, value.launch, value.native
    )


@pytest.fixture
def staged(tmp_path, monkeypatch, completed):
    root = tmp_path / "private-publications"
    root.mkdir(mode=0o700)
    monkeypatch.setattr(material, "PRIVATE_QUERY_PUBLICATION_ROOT", root)
    monkeypatch.setattr(
        material, "fixed_owner_identity", lambda: CpuHandoffIdentity(os.getuid(), os.getgid())
    )
    value = public_query_completed(completed, device="CUDA")
    native = value.native
    backend = SyntheticNativeBackend(native.spaces.query)
    backend.batch_size, backend.threads = native.batch_size, native.threads
    encoded = encode_public_solution_query(native, backend)
    assert encoded.result == value.result
    return NS(prepared=prepared(value), encoded=encoded, value=value)


def test_private_owner_local_stage_and_exact_replay_do_not_create_a_launch_marker(staged):
    value, encoded = staged.prepared, staged.encoded
    for _ordinal in range(2):
        material.stage_private_batch_query_publication(
            value, encoded.result, memoryview(encoded.vectors)
        )
    assert {path.name for path in value.workspace.iterdir()} == {
        "input.json",
        "result.json",
        "vectors.f32",
    }
    assert (value.workspace / "vectors.f32").read_bytes() == encoded.vectors
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in value.workspace.iterdir())
    assert TEXT not in repr(value)
    with pytest.raises(FrozenInstanceError):
        value.request = None


@pytest.mark.parametrize(
    "fault", ("hash", "writable", "partial", "marker", "root_mode", "symlink", "result")
)
def test_private_stage_rejects_changed_bytes_layout_and_publication_without_repair(staged, fault):
    value, encoded = staged.prepared, staged.encoded
    vectors, result = memoryview(encoded.vectors), encoded.result
    altered = None
    if fault == "hash":
        vectors = memoryview(b"\0" * len(encoded.vectors))
    elif fault == "writable":
        vectors = memoryview(bytearray(encoded.vectors))
    elif fault == "root_mode":
        value.workspace.parent.chmod(0o755)
    elif fault == "symlink":
        root = value.workspace.parent
        moved = root.with_name("original-private-publications")
        root.rename(moved)
        root.symlink_to(moved, target_is_directory=True)
    elif fault == "result":
        result = result.model_copy(update={"result_sha256": "sha256:" + "f" * 64})
    else:
        value.workspace.mkdir(mode=0o700)
        altered = value.workspace / ("input.json" if fault == "partial" else ".launch-started")
        altered.write_bytes(b"preserve-original")
        altered.chmod(0o600)
    with pytest.raises(ValueError, match="PRIVATE_CHAT_QUERY_BATCH_MATERIAL_INVALID") as error:
        material.stage_private_batch_query_publication(value, result, vectors)
    assert TEXT not in str(error.value)
    if altered is not None:
        assert altered.read_bytes() == b"preserve-original"


def test_private_stage_requires_actual_owner_even_when_model_metadata_matches(staged, monkeypatch):
    monkeypatch.setattr(
        material, "fixed_owner_identity", lambda: CpuHandoffIdentity(os.getuid() + 1, os.getgid())
    )
    with pytest.raises(ValueError):
        material.stage_private_batch_query_publication(
            staged.prepared, staged.encoded.result, memoryview(staged.encoded.vectors)
        )
    assert not staged.prepared.workspace.exists()


def test_private_gpu_material_cannot_relax_the_original_cpu_handoff(completed):
    cpu = public_query_completed(completed)
    with pytest.raises(ValueError, match="PRIVATE_CHAT_QUERY_BATCH_MATERIAL_INVALID"):
        prepared(cpu)


def test_public_source_material_cannot_enter_the_private_stage(staged):
    query = public_workflow_case(device="CUDA")
    public = PreparedBatchReferenceQuery(
        query.request, query.policy, query.bundle, query.launch, query.native_input
    )
    with pytest.raises(ValueError):
        material.stage_private_batch_query_publication(
            public, staged.encoded.result, memoryview(staged.encoded.vectors)
        )
    assert not staged.prepared.workspace.exists()
    with pytest.raises(ValueError, match="PRIVATE_CHAT_QUERY_BATCH_MATERIAL_INVALID"):
        material.PreparedBatchPrivateChatQuery(
            query.request, query.policy, query.bundle, query.launch, query.native_input
        )


def test_public_binding_export_keeps_its_identity_and_rejects_private_parent(staged):
    assert (
        public_bindings.prepare_reference_query_batch_binding
        is bindings.prepare_reference_query_batch_binding
    )
    plan = private_planning_case()
    with pytest.raises(ValueError, match="REFERENCE_QUERY_BATCH_BINDING_INVALID"):
        public_bindings.prepare_reference_query_batch_binding(
            plan.request, plan.route, (staged.prepared,)
        )
    with pytest.raises(ValueError, match="PRIVATE_CHAT_QUERY_BATCH_BINDING_INVALID"):
        bindings.prepare_private_chat_query_batch_binding(object(), object(), staged.prepared)
