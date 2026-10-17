"""Synthetic protected CUDA metadata and local IO, never root/native/model admission."""

import json
import stat
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest
from eom_catalog_contracts.embedding_device_benchmark import (
    BenchmarkOwnerRequest,
    BenchmarkWorkerInvocation,
)
from eom_catalog_service import embedding_benchmark_handoff as handoff
from eom_catalog_service import embedding_native_installation_admission as admission
from eom_catalog_service.embedding_native_backend_pins import NativeEmbeddingBackendPins
from eom_identifiers import canonical_json_bytes, sha256_bytes
from jsonschema import ValidationError as SchemaError

from tests.unit.embedding_benchmark_environment_fixtures import (
    EnvironmentMetadata,
    environment_metadata,
    stage_installation,
)
from tests.unit.embedding_device_benchmark_fixtures import (
    owner_request,
    staged_inputs,
    worker_invocation,
)
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_benchmark_handoff import synthetic_root
from tests.unit.test_embedding_cuda_installation_evidence import DRAFT as DRAFT_V2
from tests.unit.test_embedding_cuda_installation_evidence import metadata as metadata_v2
from tests.unit.test_embedding_cuda_nvml_admission import DRAFT as DRAFT_V21
from tests.unit.test_embedding_cuda_nvml_admission import metadata as metadata_v21


def cuda_metadata(version):
    facts = metadata_v2() if version == "2.0" else metadata_v21()
    config = facts["config"]
    body = owner_request().model_dump(mode="json")
    body["cuda"]["bundle"] = config.bundle.model_dump(mode="json")
    body["cuda"]["installed_proof"] = config.installed_proof.model_dump(mode="json")
    request = BenchmarkOwnerRequest.model_validate(seal(body, "request_sha256"))
    body = worker_invocation(2).model_dump(mode="json")
    body.update(
        runtime=request.cuda.model_dump(mode="json"), owner_request_sha256=request.request_sha256
    )
    invocation = BenchmarkWorkerInvocation.model_validate(seal(body, "invocation_sha256"))
    return EnvironmentMetadata(
        request,
        invocation,
        staged_inputs(),
        NativeEmbeddingBackendPins(
            config.configuration_id,
            config.configuration_revision_id,
            config.config_sha256,
            sha256_bytes(facts["config_raw"]),
            sha256_bytes(facts["receipt_raw"]),
        ),
        facts["config_raw"],
        facts["receipt_raw"],
        (DRAFT_V2 if version == "2.0" else DRAFT_V21).read_bytes(),
        "admission-receipt-v2.schema.json"
        if version == "2.0"
        else "admission-receipt-v2.1.schema.json",
    )


def stage(tmp_path, monkeypatch, metadata):
    root = synthetic_root(tmp_path, monkeypatch)
    config, evidence = stage_installation(tmp_path, metadata)
    monkeypatch.setattr(handoff, "_CONFIG_ROOT", config)
    monkeypatch.setattr(handoff, "_EVIDENCE_ROOT", evidence)
    monkeypatch.setattr(admission, "_EVIDENCE_ROOT", evidence)
    monkeypatch.setattr(handoff, "_owner_start_ticks", lambda *_a, **_kw: 12345)
    prepared = handoff.prepare_benchmark_handoff(
        metadata.request, metadata.invocation, metadata.inputs
    )
    return root, prepared


def prepare(prepared, metadata):
    return handoff.prepare_benchmark_environment(
        prepared,
        metadata.invocation,
        backend=metadata.backend,
        owner_pid=123,
        expires_ns=time.monotonic_ns() + 10 * 10**9,
    )


@pytest.mark.parametrize("version", ("2.0", "2.1"))
def test_both_cuda_receipt_versions_prepare_same_exact_nonsecret_fields_once(
    tmp_path, monkeypatch, version
):
    metadata = cuda_metadata(version)
    root, staged = stage(tmp_path, monkeypatch, metadata)
    result = prepare(staged, metadata)
    execution = root / metadata.invocation.execution_id
    path = execution / "launch.env"
    raw = path.read_bytes()
    fields = dict(line.split("=", 1) for line in raw.decode("ascii").splitlines())
    assert len(fields) == 8 and fields["EOM_BENCHMARK_OWNER_PID"] == "123"
    assert (
        fields["EOM_EMBEDDING_CONFIGURATION_RAW_SHA256"]
        == metadata.backend.configuration_raw_sha256
    )
    assert fields["EOM_EMBEDDING_RECEIPT_RAW_SHA256"] == metadata.backend.receipt_raw_sha256
    assert result.state == "STAGED_NOT_LAUNCHED" and result.owner_start_ticks == 12345
    assert result.environment_raw_sha256 == sha256_bytes(raw)
    assert type(result) is handoff.PreparedBenchmarkEnvironment
    assert handoff.PreparedCpuBenchmarkEnvironment is handoff.PreparedBenchmarkEnvironment
    assert stat.S_IMODE(path.stat().st_mode) == 0o600 and path.stat().st_nlink == 1
    assert (execution / "cuda-ready.json").stat().st_size == 0
    assert len(tuple((execution / "outputs").iterdir())) == 16
    inode = path.stat().st_ino
    with pytest.raises(handoff.BenchmarkHandoffError, match="ALREADY_EXISTS"):
        prepare(staged, metadata)
    assert path.stat().st_ino == inode and path.read_bytes() == raw


@pytest.mark.parametrize("version", ("2.0", "2.1"))
@pytest.mark.parametrize(
    "fault",
    (
        "configuration",
        "bundle",
        "proof",
        "runtime",
        "host",
        "version",
        "cpu_receipt",
        "schema",
        "raw",
    ),
)
def test_rehashed_mixed_or_missing_metadata_never_creates_launch_environment(
    tmp_path, monkeypatch, version, fault
):
    metadata = cuda_metadata(version)
    body = json.loads(metadata.receipt_raw)
    if fault == "configuration":
        body["configuration"]["configuration_sha256"] = "sha256:" + "a" * 64
    elif fault == "bundle":
        body["bundle"]["bundle_revision_id"] = "embeddingbundlerev_" + "a" * 32
    elif fault == "proof":
        body["installed_proof"]["proof_revision_id"] = "embeddingruntimeproofrev_" + "a" * 32
    elif fault == "runtime":
        body["runtime_sha256"] = "sha256:" + "a" * 64
    elif fault == "host":
        body["cuda_host_extension"]["configuration_revision_id"] = (
            "embeddingcudahostrev_" + "a" * 32
        )
    elif fault == "version":
        body["schema_version"] = "embedding-native-admission-receipt/2.99"
    raw = canonical_json_bytes(seal(body, "receipt_sha256"))
    if fault == "cpu_receipt":
        raw = environment_metadata().receipt_raw
    metadata = replace(
        metadata,
        receipt_raw=raw,
        backend=replace(metadata.backend, receipt_raw_sha256=sha256_bytes(raw)),
    )
    if fault == "schema":
        metadata = replace(metadata, receipt_schema=environment_metadata().receipt_schema)
    root, prepared = stage(tmp_path, monkeypatch, metadata)
    execution = root / metadata.invocation.execution_id
    if fault == "raw":
        (
            admission._EVIDENCE_ROOT
            / metadata.backend.configuration_id
            / metadata.backend.configuration_revision_id
            / "receipt.json"
        ).write_bytes(b"{}")
    with pytest.raises((ValueError, SchemaError)):
        prepare(prepared, metadata)
    assert not (execution / "launch.env").exists()
    assert (execution / "cuda-ready.json").stat().st_size == 0


def test_cpu_compatibility_entry_refuses_cuda_without_new_file(tmp_path, monkeypatch):
    metadata = cuda_metadata("2.1")
    root, prepared = stage(tmp_path, monkeypatch, metadata)
    with pytest.raises(handoff.BenchmarkHandoffError):
        handoff.prepare_cpu_benchmark_environment(
            prepared,
            metadata.invocation,
            backend=metadata.backend,
            owner_pid=123,
            expires_ns=time.monotonic_ns() + 10**9,
        )
    assert not (root / metadata.invocation.execution_id / "launch.env").exists()


@pytest.mark.parametrize("when", ("before", "after"))
def test_current_owner_exit_preserves_staging_without_renewal(tmp_path, monkeypatch, when):
    metadata = cuda_metadata("2.1")
    root, prepared = stage(tmp_path, monkeypatch, metadata)
    calls = []

    def owner(*_args, **_kwargs):
        calls.append(True)
        return 999 if len(calls) == (2 if when == "before" else 3) else 12345

    monkeypatch.setattr(handoff, "_owner_start_ticks", owner)
    with pytest.raises(handoff.BenchmarkHandoffError):
        prepare(prepared, metadata)
    path = root / metadata.invocation.execution_id / "launch.env"
    assert path.exists() == (when == "after")
    if path.exists():
        raw = path.read_bytes()
        monkeypatch.setattr(handoff, "_owner_start_ticks", lambda *_a, **_kw: 12345)
        with pytest.raises(handoff.BenchmarkHandoffError, match="ALREADY_EXISTS"):
            prepare(prepared, metadata)
        assert path.read_bytes() == raw


@pytest.mark.parametrize("version", ("2.0", "2.1"))
def test_two_cuda_preparers_cannot_overwrite_or_renew_one_environment(
    tmp_path, monkeypatch, version
):
    metadata = cuda_metadata(version)
    root, prepared = stage(tmp_path, monkeypatch, metadata)

    def submit():
        try:
            return prepare(prepared, metadata).state
        except handoff.BenchmarkHandoffError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(lambda _n: submit(), range(2)))
    assert sorted(results) == ["BENCHMARK_ENVIRONMENT_ALREADY_EXISTS", "STAGED_NOT_LAUNCHED"]
    path = root / metadata.invocation.execution_id / "launch.env"
    assert path.stat().st_nlink == 1 and stat.S_IMODE(path.stat().st_mode) == 0o600
    assert len(path.read_bytes().splitlines()) == 8
