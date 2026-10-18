"""Pure launch serialization and fixed unit closure; no root/model/systemd effects."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from eom_catalog_service.embedding_native_backend_pins import NativeEmbeddingBackendPins
from eom_catalog_service.embedding_native_cuda_index_entry import (
    NativeCudaIndexLaunchPins,
    parse_native_cuda_index_launch_pins,
)
from eom_catalog_service.embedding_native_cuda_index_launch import (
    CUDA_INDEX_ENTRY,
    CUDA_INDEX_ENTRY_SHA256,
    CUDA_INDEX_RUNTIME_ROOT,
    CUDA_INDEX_TEMPLATE,
    CUDA_INDEX_TEMPLATE_SHA256,
    native_cuda_index_backend_environment_bytes,
    native_cuda_index_launch_arguments,
    native_cuda_index_launch_environment_bytes,
    native_cuda_index_unit,
    parse_native_cuda_index_launch_environment,
)
from eom_identifiers import sha256_bytes

ROOT = Path(__file__).resolve().parents[2]


def test_static_backend_environment_contains_no_execution_fields(pins):
    backend = NativeEmbeddingBackendPins(
        pins.configuration_id,
        pins.configuration_revision_id,
        pins.configuration_sha256,
        pins.configuration_raw_sha256,
        pins.receipt_raw_sha256,
    )
    raw = native_cuda_index_backend_environment_bytes(backend)
    assert len(raw.splitlines()) == 5
    assert b"EOM_CUDA_INDEX_" not in raw
    assert native_cuda_index_launch_environment_bytes(pins).endswith(raw)
    with pytest.raises(ValueError, match="BACKEND_ENVIRONMENT_INVALID"):
        native_cuda_index_backend_environment_bytes(pins)


@pytest.fixture
def pins() -> NativeCudaIndexLaunchPins:
    return NativeCudaIndexLaunchPins(
        "a" * 32,
        "job_" + "b" * 32,
        "sha256:" + "c" * 64,
        "sha256:" + "d" * 64,
        123456789,
        "embeddingnativeconfig_" + "e" * 32,
        "embeddingnativeconfigrev_" + "f" * 32,
        "sha256:" + "1" * 64,
        "sha256:" + "2" * 64,
        "sha256:" + "3" * 64,
    )


def test_closed_arguments_and_canonical_environment_round_trip(pins):
    arguments = native_cuda_index_launch_arguments(pins)
    assert arguments[:2] == ("INDEX", pins.execution_id)
    assert parse_native_cuda_index_launch_pins(arguments) == pins
    raw = native_cuda_index_launch_environment_bytes(pins)
    assert raw.startswith(b"EOM_CUDA_INDEX_JOB_ID=job_") and raw.endswith(b"\n")
    assert len(raw.splitlines()) == 9
    assert parse_native_cuda_index_launch_environment(raw, execution_id=pins.execution_id) == pins
    assert native_cuda_index_unit(pins.execution_id) == (
        "eom-embedding-native-cuda-index@" + pins.execution_id + ".service"
    )


@pytest.mark.parametrize(
    "field,value",
    (
        ("execution_id", "--all"),
        ("execution_id", "a" * 32 + "\n"),
        ("job_id", "job_" + "b" * 32 + "\nUSER=root"),
        ("association_sha256", "latest"),
        ("input_raw_sha256", "sha256:" + "D" * 64),
        ("expires_ns", True),
        ("expires_ns", "123456789"),
        ("expires_ns", 0),
        ("expires_ns", 2**63),
        ("configuration_id", "/tmp/model"),
        ("configuration_revision_id", "latest"),
        ("configuration_sha256", "bad"),
        ("configuration_raw_sha256", "bad"),
        ("receipt_raw_sha256", "${SHELL}"),
    ),
)
def test_values_are_not_shell_paths_authority_or_implicit_latest(pins, field, value):
    with pytest.raises(ValueError):
        native_cuda_index_launch_environment_bytes(replace(pins, **{field: value}))


@pytest.mark.parametrize("identity", (None, "--all", "../root", "a" * 31, "A" * 32))
def test_unit_identity_is_closed_before_any_external_operation(identity):
    with pytest.raises(ValueError, match="NATIVE_CUDA_INDEX_LAUNCH_INVALID"):
        native_cuda_index_unit(identity)


@pytest.mark.parametrize("value", (None, {}, "pins"))
def test_wrong_pin_type_cannot_render_environment(value):
    with pytest.raises(ValueError, match="NATIVE_CUDA_INDEX_LAUNCH_INVALID"):
        native_cuda_index_launch_arguments(value)


@pytest.mark.parametrize(
    "fault",
    (
        "type",
        "empty",
        "oversized",
        "nonascii",
        "unterminated",
        "blank",
        "extra",
        "duplicate",
        "reordered",
        "quoted",
        "comment",
        "crlf",
        "nul",
        "shell",
    ),
)
def test_environment_requires_the_one_exact_canonical_nonsecret_form(pins, fault):
    raw = native_cuda_index_launch_environment_bytes(pins)
    if fault == "type":
        raw = raw.decode("ascii")
    elif fault == "empty":
        raw = b""
    elif fault == "oversized":
        raw = b"x" * 4097
    elif fault == "nonascii":
        raw += b"\xff"
    elif fault == "unterminated":
        raw = raw[:-1]
    elif fault == "blank":
        raw += b"\n"
    elif fault == "extra":
        raw += b"USER=root\n"
    elif fault == "duplicate":
        raw = raw.replace(b"EOM_CUDA_INDEX_INPUT_RAW_SHA256", b"EOM_CUDA_INDEX_ASSOCIATION_SHA256")
    elif fault == "reordered":
        lines = raw.splitlines(keepends=True)
        lines[0], lines[1] = lines[1], lines[0]
        raw = b"".join(lines)
    elif fault == "quoted":
        raw = raw.replace(b"=job_", b'="job_')
    elif fault == "comment":
        raw = b"# comment\n" + raw
    elif fault == "crlf":
        raw = raw.replace(b"\n", b"\r\n")
    elif fault == "nul":
        raw = raw.replace(b"=job_", b"=\x00job_")
    else:
        raw = raw.replace(b"=job_", b"=${SHELL}job_")
    with pytest.raises(ValueError, match="NATIVE_CUDA_INDEX_LAUNCH_ENVIRONMENT_INVALID"):
        parse_native_cuda_index_launch_environment(raw, execution_id=pins.execution_id)


def test_exact_unit_and_external_entry_bytes_are_independently_pinned():
    path = ROOT / "infra/systemd" / CUDA_INDEX_TEMPLATE
    assert sha256_bytes(path.read_bytes()) == CUDA_INDEX_TEMPLATE_SHA256
    source = (
        ROOT / "services/catalog_service/eom_catalog_service/embedding_native_cuda_index_entry.py"
    )
    assert sha256_bytes(source.read_bytes()) == CUDA_INDEX_ENTRY_SHA256
    unit = path.read_text()
    assert f"EnvironmentFile={CUDA_INDEX_RUNTIME_ROOT}/%i/launch.env\n" in unit
    assert f"OpenFile={CUDA_INDEX_RUNTIME_ROOT}/%i/ready.json:cuda-index-ready\n" in unit
    assert f"-I -B {CUDA_INDEX_ENTRY} INDEX %i " in unit
    assert "BenchmarkWorkerInvocation" not in unit and "Sockets=" not in unit
    assert "Slice=system.slice\n" in unit and "CollectMode=inactive\n" in unit
    for key, member in (
        ("StandardInput", "input.json"),
        ("StandardOutput", "result.json"),
        ("StandardError", "vectors.f32"),
    ):
        assert f"{key}=file:{CUDA_INDEX_RUNTIME_ROOT}/%i/{member}\n" in unit
    for required in (
        "User=eom-embedding-cuda\n",
        "Group=eom-embedding-cuda\n",
        "SupplementaryGroups=eom-gpu-lease\n",
        "NoNewPrivileges=yes\n",
        "PrivateNetwork=yes\n",
        "ProtectSystem=strict\n",
        "CapabilityBoundingSet=\n",
        "AmbientCapabilities=\n",
        "NotifyAccess=main\n",
        "FileDescriptorStoreMax=1\n",
        "FileDescriptorStorePreserve=yes\n",
        "TimeoutStartSec=180\n",
        "Restart=no\n",
        "MemoryMax=6G\n",
        "CPUQuota=400%\n",
        "TasksMax=64\n",
        "LimitCORE=0\n",
    ):
        assert required in unit
