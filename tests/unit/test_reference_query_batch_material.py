"""Real protected temporary files with synthetic numerical bytes; no model or native launch."""

from __future__ import annotations

import os
from dataclasses import FrozenInstanceError

import pytest
from eom_catalog_service.embedding_encoder_adapter import encode_reference_query_batch
from eom_orchestrator.inference_transfer_cpu_handoff import CpuHandoffIdentity
from eom_workflow_runner import reference_query_batch_material as material

from tests.unit.test_embedding_incremental_encoding import SyntheticNativeBackend
from tests.unit.test_reference_query_execution_contracts import case


@pytest.fixture
def staged(tmp_path, monkeypatch):
    root = tmp_path / "queries"
    root.mkdir(mode=0o700)
    monkeypatch.setattr(material, "QUERY_PUBLICATION_ROOT", root)
    monkeypatch.setattr(
        material, "fixed_owner_identity", lambda: CpuHandoffIdentity(os.getuid(), os.getgid())
    )
    query = case(device="CUDA")
    prepared = material.PreparedBatchReferenceQuery(
        query.request, query.policy, query.bundle, query.launch, query.native_input
    )
    backend = SyntheticNativeBackend(query.native_input.spaces.query)
    backend.batch_size, backend.threads = query.native_input.batch_size, query.native_input.threads
    encoded = encode_reference_query_batch(query.native_input, backend)
    return prepared, encoded


def test_exact_result_materialization_and_replay_never_create_a_launch_marker(staged):
    prepared, encoded = staged
    for _ in range(2):
        material.stage_batch_query_publication(
            prepared, encoded.result, memoryview(encoded.vectors)
        )
    assert {path.name for path in prepared.workspace.iterdir()} == {
        "input.json",
        "result.json",
        "vectors.f32",
    }
    assert (prepared.workspace / "vectors.f32").read_bytes() == encoded.vectors
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in prepared.workspace.iterdir())
    with pytest.raises(FrozenInstanceError):
        prepared.request = None


@pytest.mark.parametrize("fault", ("hash", "writable", "partial", "legacy_marker", "root_mode"))
def test_invalid_or_partial_publication_is_preserved_not_repaired(staged, fault):
    prepared, encoded = staged
    vectors = memoryview(encoded.vectors)
    if fault == "hash":
        vectors = memoryview(b"\0" * len(encoded.vectors))
    elif fault == "writable":
        vectors = memoryview(bytearray(encoded.vectors))
    elif fault == "root_mode":
        prepared.workspace.parent.chmod(0o755)
    else:
        prepared.workspace.mkdir(mode=0o700)
        path = prepared.workspace / ("input.json" if fault == "partial" else ".launch-started")
        path.write_bytes(b"preserve-partial")
        path.chmod(0o600)
    with pytest.raises(ValueError):
        material.stage_batch_query_publication(prepared, encoded.result, vectors)
    if fault in {"partial", "legacy_marker"}:
        assert path.read_bytes() == b"preserve-partial"


def test_cpu_input_cannot_be_a_cuda_batch_publication_material():
    query = case(device="CPU")
    with pytest.raises(ValueError):
        material.PreparedBatchReferenceQuery(
            query.request, query.policy, query.bundle, query.launch, query.native_input
        )
