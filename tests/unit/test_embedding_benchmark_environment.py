"""Synthetic ownership/process/installation claims; no protected installation or launch."""

from __future__ import annotations

import json
import os
import stat
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest
from eom_catalog_service import embedding_benchmark_cpu as cpu
from eom_catalog_service import embedding_benchmark_handoff as handoff
from eom_catalog_service.embedding_benchmark_handoff import (
    BenchmarkHandoffError,
    PreparedCpuBenchmarkEnvironment,
    prepare_benchmark_handoff,
    prepare_cpu_benchmark_environment,
)
from eom_identifiers import canonical_json_bytes, sha256_bytes

from tests.unit.embedding_benchmark_environment_fixtures import (
    EnvironmentMetadata,
    environment_metadata,
    stage_installation,
)
from tests.unit.embedding_device_benchmark_fixtures import worker_invocation
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_benchmark_handoff import synthetic_root


@pytest.fixture
def staged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, EnvironmentMetadata]:
    root = synthetic_root(tmp_path, monkeypatch)
    metadata = environment_metadata()
    config, evidence = stage_installation(tmp_path, metadata)
    monkeypatch.setattr(handoff, "_CONFIG_ROOT", config)
    monkeypatch.setattr(handoff, "_EVIDENCE_ROOT", evidence)
    monkeypatch.setattr(handoff, "_owner_start_ticks", lambda *args, **kwargs: 12345)
    prepare_benchmark_handoff(metadata.request, metadata.invocation, metadata.inputs)
    return root, metadata


def prepare(metadata: EnvironmentMetadata, **changes: object) -> PreparedCpuBenchmarkEnvironment:
    prepared = handoff._prepared_handoff(
        metadata.invocation,
        sha256_bytes(handoff.embedding_device_benchmark_bytes(metadata.invocation)),
    )
    arguments = dict(
        backend=metadata.backend, owner_pid=123, expires_ns=time.monotonic_ns() + 10 * 10**9
    )
    arguments.update(changes)
    return prepare_cpu_benchmark_environment(prepared, metadata.invocation, **arguments)  # type: ignore[arg-type]


def test_eight_exact_nonsecret_fields_roundtrip_into_existing_cpu_argument_parser(
    staged: tuple[Path, EnvironmentMetadata],
) -> None:
    root, metadata = staged
    result = prepare(metadata)
    path = root / metadata.invocation.execution_id / "launch.env"
    raw = path.read_bytes()
    fields = dict(line.split("=", 1) for line in raw.decode("ascii").splitlines())
    assert len(fields) == 8
    assert fields["EOM_BENCHMARK_OWNER_PID"] == "123"
    pins = cpu._arguments(
        (
            metadata.invocation.execution_id,
            fields["EOM_BENCHMARK_INVOCATION_RAW_SHA256"],
            fields["EOM_BENCHMARK_OWNER_PID"],
            fields["EOM_BENCHMARK_EXPIRES_NS"],
            fields["EOM_EMBEDDING_CONFIGURATION_ID"],
            fields["EOM_EMBEDDING_CONFIGURATION_REVISION_ID"],
            fields["EOM_EMBEDDING_CONFIGURATION_SHA256"],
            fields["EOM_EMBEDDING_CONFIGURATION_RAW_SHA256"],
            fields["EOM_EMBEDDING_RECEIPT_RAW_SHA256"],
        )
    )
    assert pins.backend == metadata.backend
    assert result.environment_raw_sha256 == sha256_bytes(raw)
    assert result.state == "STAGED_NOT_LAUNCHED" and result.owner_start_ticks == 12345
    assert stat.S_IMODE(path.stat().st_mode) == 0o600 and path.stat().st_nlink == 1
    inode = path.stat().st_ino
    with pytest.raises(BenchmarkHandoffError, match="ALREADY_EXISTS"):
        prepare(metadata)
    assert path.stat().st_ino == inode and path.read_bytes() == raw


def test_current_cpu_v11_configuration_stages_without_legacy_conversion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from eom_catalog_contracts.embedding_native_runtime_config import (
        installed_embedding_native_runtime_config_bytes,
    )
    from eom_catalog_service.embedding_native_cpu_backend import NativeCpuBackendPins

    from tests.unit.embedding_native_runtime_config_v11_fixtures import native_config_metadata_v11

    root = synthetic_root(tmp_path, monkeypatch)
    metadata = environment_metadata()
    configuration, _, _ = native_config_metadata_v11()
    configuration_raw = installed_embedding_native_runtime_config_bytes(configuration)
    receipt_body = json.loads(metadata.receipt_raw)
    receipt_body["configuration"] = {
        "configuration_id": configuration.configuration_id,
        "configuration_revision_id": configuration.configuration_revision_id,
        "configuration_sha256": configuration.config_sha256,
        "configuration_raw_sha256": sha256_bytes(configuration_raw),
    }
    receipt_raw = canonical_json_bytes(seal(receipt_body, "receipt_sha256"))
    metadata = replace(
        metadata,
        configuration_raw=configuration_raw,
        receipt_raw=receipt_raw,
        backend=NativeCpuBackendPins(
            configuration.configuration_id,
            configuration.configuration_revision_id,
            configuration.config_sha256,
            sha256_bytes(configuration_raw),
            sha256_bytes(receipt_raw),
        ),
    )
    config, evidence = stage_installation(tmp_path, metadata)
    monkeypatch.setattr(handoff, "_CONFIG_ROOT", config)
    monkeypatch.setattr(handoff, "_EVIDENCE_ROOT", evidence)
    monkeypatch.setattr(handoff, "_owner_start_ticks", lambda *args, **kwargs: 12345)
    prepare_benchmark_handoff(metadata.request, metadata.invocation, metadata.inputs)
    result = prepare(metadata)
    assert result.state == "STAGED_NOT_LAUNCHED"
    assert (
        configuration.configuration_revision_id.encode()
        in (root / metadata.invocation.execution_id / "launch.env").read_bytes()
    )


@pytest.mark.parametrize("fault", ("receipt", "config", "schema", "staged_input", "output"))
def test_changed_pointer_bytes_or_used_output_prevent_environment_creation(
    staged: tuple[Path, EnvironmentMetadata],
    fault: str,
) -> None:
    root, metadata = staged
    if fault == "receipt":
        path = (
            handoff._EVIDENCE_ROOT
            / metadata.backend.configuration_id
            / metadata.backend.configuration_revision_id
            / "receipt.json"
        )
    elif fault == "config":
        path = (
            handoff._CONFIG_ROOT
            / metadata.backend.configuration_id
            / metadata.backend.configuration_revision_id
            / "config.json"
        )
    elif fault == "schema":
        path = handoff._EVIDENCE_ROOT / "schemas/admission-receipt-v1.schema.json"
    elif fault == "staged_input":
        path = root / metadata.invocation.execution_id / "invocation.json"
    else:
        path = root / metadata.invocation.execution_id / "outputs/cold-documents.f32"
    path.write_bytes(b"changed")
    with pytest.raises(ValueError):
        prepare(metadata)
    assert not (root / metadata.invocation.execution_id / "launch.env").exists()


@pytest.mark.parametrize(
    "changes",
    (
        {"owner_pid": True},
        {"owner_pid": 0},
        {"owner_pid": 2**31},
        {"expires_ns": True},
        {"expires_ns": 1},
        {"expires_ns": 2**63},
    ),
)
def test_invalid_pid_deadline_and_implicit_values_never_stage(
    staged: tuple[Path, EnvironmentMetadata],
    changes: dict[str, object],
) -> None:
    root, metadata = staged
    with pytest.raises(ValueError):
        prepare(metadata, **changes)
    assert not (root / metadata.invocation.execution_id / "launch.env").exists()


def test_concurrent_environment_prepare_has_one_winner(
    staged: tuple[Path, EnvironmentMetadata],
) -> None:
    _, metadata = staged

    def invoke(_: int) -> str:
        try:
            return prepare(metadata).state
        except BenchmarkHandoffError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = sorted(executor.map(invoke, range(2)))
    assert results == ["BENCHMARK_ENVIRONMENT_ALREADY_EXISTS", "STAGED_NOT_LAUNCHED"]


def test_forged_prepared_identity_is_not_a_grant(staged: tuple[Path, EnvironmentMetadata]) -> None:
    root, metadata = staged
    prepared = handoff._prepared_handoff(
        metadata.invocation,
        sha256_bytes(handoff.embedding_device_benchmark_bytes(metadata.invocation)),
    )
    with pytest.raises(ValueError):
        prepare_cpu_benchmark_environment(
            replace(prepared, job_id="job_" + "0" * 32),
            metadata.invocation,
            backend=metadata.backend,
            owner_pid=123,
            expires_ns=time.monotonic_ns() + 10**9,
        )
    assert not (root / metadata.invocation.execution_id / "launch.env").exists()


def test_late_process_change_preserves_private_file_but_returns_no_launch_receipt(
    staged: tuple[Path, EnvironmentMetadata],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, metadata = staged
    values = iter((12345, 12345, 12346))
    monkeypatch.setattr(handoff, "_owner_start_ticks", lambda *args, **kwargs: next(values))
    with pytest.raises(ValueError):
        prepare(metadata)
    path = root / metadata.invocation.execution_id / "launch.env"
    assert path.is_file() and stat.S_IMODE(path.stat().st_mode) == 0o600


def test_process_reader_rejects_another_identity_without_reading_environment() -> None:
    ticks = handoff._owner_start_ticks(os.getpid(), uid=os.getuid(), gid=os.getgid())
    assert ticks > 0
    with pytest.raises(ValueError):
        handoff._owner_start_ticks(os.getpid(), uid=os.getuid() + 1, gid=os.getgid())


def test_cuda_invocation_is_not_silently_prepared_as_cpu(
    staged: tuple[Path, EnvironmentMetadata],
) -> None:
    root, metadata = staged
    invocation = worker_invocation(2)
    prepared = handoff._prepared_handoff(
        invocation, sha256_bytes(handoff.embedding_device_benchmark_bytes(invocation))
    )
    with pytest.raises(ValueError):
        prepare_cpu_benchmark_environment(
            prepared,
            invocation,
            backend=metadata.backend,
            owner_pid=123,
            expires_ns=time.monotonic_ns() + 10**9,
        )
    assert not (root / metadata.invocation.execution_id / "launch.env").exists()


def test_rehashed_configuration_and_receipt_cannot_select_another_runtime(
    staged: tuple[Path, EnvironmentMetadata],
) -> None:
    root, metadata = staged
    config_path = (
        handoff._CONFIG_ROOT
        / metadata.backend.configuration_id
        / metadata.backend.configuration_revision_id
        / "config.json"
    )
    receipt_path = (
        handoff._EVIDENCE_ROOT
        / metadata.backend.configuration_id
        / metadata.backend.configuration_revision_id
        / "receipt.json"
    )
    config = json.loads(metadata.configuration_raw)
    config["runtime_sha256"] = "sha256:" + "0" * 64
    config = seal(config, "config_sha256")
    config_raw = canonical_json_bytes(config)
    receipt = json.loads(metadata.receipt_raw)
    receipt["configuration"]["configuration_sha256"] = config["config_sha256"]
    receipt["configuration"]["configuration_raw_sha256"] = sha256_bytes(config_raw)
    receipt["runtime_sha256"] = config["runtime_sha256"]
    receipt["unit_probe"]["observed_runtime_sha256"] = config["runtime_sha256"]
    receipt_raw = canonical_json_bytes(seal(receipt, "receipt_sha256"))
    config_path.write_bytes(config_raw)
    receipt_path.write_bytes(receipt_raw)
    backend = replace(
        metadata.backend,
        configuration_sha256=config["config_sha256"],
        configuration_raw_sha256=sha256_bytes(config_raw),
        receipt_raw_sha256=sha256_bytes(receipt_raw),
    )
    with pytest.raises(BenchmarkHandoffError, match="IDENTITY_INVALID"):
        prepare(metadata, backend=backend)
    assert not (root / metadata.invocation.execution_id / "launch.env").exists()


def test_write_failure_preserves_original_candidate_and_cannot_renew_it(
    staged: tuple[Path, EnvironmentMetadata],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, metadata = staged
    original = handoff._new_member

    def fail(parent: int, name: str, payload: bytes, uid: int, gid: int, mode: int) -> None:
        original(parent, name, payload, uid, gid, mode)
        raise OSError("synthetic post-write fsync uncertainty")

    monkeypatch.setattr(handoff, "_new_member", fail)
    with pytest.raises(BenchmarkHandoffError, match="PREPARE_FAILED"):
        prepare(metadata)
    path = root / metadata.invocation.execution_id / "launch.env"
    inode, raw = path.stat().st_ino, path.read_bytes()
    with pytest.raises(BenchmarkHandoffError, match="ALREADY_EXISTS"):
        prepare(metadata)
    assert path.stat().st_ino == inode and path.read_bytes() == raw
