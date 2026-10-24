"""Pure successor launch pins and unit source; no launch, privilege or model calls."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from eom_catalog_service.embedding_gpu_batch_launch import (
    NativeEmbeddingGpuBatchLaunchPins,
    native_embedding_gpu_batch_environment,
    native_embedding_gpu_batch_launch_arguments,
    native_embedding_gpu_batch_unit,
    parse_native_embedding_gpu_batch_environment,
    parse_native_embedding_gpu_batch_launch,
)
from eom_catalog_service.embedding_native_backend_pins import NativeEmbeddingBackendPins

ROOT = Path(__file__).resolve().parents[2]


def launch_pins():
    sha = "sha256:" + "a" * 64
    return NativeEmbeddingGpuBatchLaunchPins(
        "a" * 32,
        sha,
        123,
        sha,
        180,
        16 * 1024**2,
        64 * 1024**2,
        NativeEmbeddingBackendPins(
            "embeddingnativeconfig_" + "a" * 32,
            "embeddingnativeconfigrev_" + "b" * 32,
            sha,
            sha,
            sha,
        ),
    )


def test_canonical_launch_round_trip_has_exact_immutable_attempt_and_backend_pins():
    pins = launch_pins()
    arguments = native_embedding_gpu_batch_launch_arguments(pins)
    assert len(arguments) == 12 and parse_native_embedding_gpu_batch_launch(arguments) == pins
    raw = native_embedding_gpu_batch_environment(pins)
    assert len(raw.splitlines()) == 11
    assert parse_native_embedding_gpu_batch_environment(raw, attempt_hex=pins.attempt_hex) == pins
    assert (
        native_embedding_gpu_batch_unit(pins.attempt_hex)
        == "eom-embedding-native-gpu-batch@" + "a" * 32 + ".service"
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("attempt_hex", "../other"),
        ("attempt_hex", "A" * 32),
        ("allocation_raw_sha256", "latest"),
        ("resource_profile_sha256", "${SHELL}"),
        ("root_pid", True),
        ("root_pid", 0),
        ("root_pid", 2**31),
        ("timeout_seconds", 181),
        ("timeout_seconds", "180"),
        ("timeout_seconds", 0),
        ("vector_max_bytes", 3),
        ("vector_max_bytes", 16 * 1024**2 + 1),
        ("total_output_max_bytes", 64 * 1024**2 + 1),
        ("total_output_max_bytes", 16 * 1024**2),
        ("backend", object()),
    ],
)
def test_launch_values_cannot_inject_paths_flags_or_unbounded_resources(field, value):
    with pytest.raises(ValueError):
        native_embedding_gpu_batch_launch_arguments(replace(launch_pins(), **{field: value}))


@pytest.mark.parametrize(
    "fault", ["list", "extra", "missing", "leading_zero", "flag", "float", "nonstring"]
)
def test_closed_argv_rejects_implicit_casts_and_arbitrary_arguments(fault):
    args = list(native_embedding_gpu_batch_launch_arguments(launch_pins()))
    if fault == "list":
        value = args
    else:
        if fault == "extra":
            args.append("--model=/tmp/other")
        elif fault == "missing":
            args.pop()
        elif fault == "leading_zero":
            args[2] = "0123"
        elif fault == "flag":
            args[0] = "--all"
        elif fault == "float":
            args[4] = "180.0"
        else:
            args[2] = 123
        value = tuple(args)
    with pytest.raises(ValueError):
        parse_native_embedding_gpu_batch_launch(value)


@pytest.mark.parametrize(
    "fault", ["str", "extra", "duplicate", "reorder", "crlf", "quote", "space", "unterminated"]
)
def test_environment_has_one_exact_nonsecret_serialization(fault):
    pins = launch_pins()
    raw = native_embedding_gpu_batch_environment(pins)
    if fault == "str":
        raw = raw.decode()
    elif fault == "extra":
        raw += b"SHELL=/bin/sh\n"
    elif fault == "duplicate":
        raw += raw.splitlines(keepends=True)[0]
    elif fault == "reorder":
        raw = b"".join(reversed(raw.splitlines(keepends=True)))
    elif fault == "crlf":
        raw = raw.replace(b"\n", b"\r\n")
    elif fault == "quote":
        raw = raw.replace(b"=123\n", b'="123"\n')
    elif fault == "space":
        raw = b" " + raw
    else:
        raw = raw[:-1]
    with pytest.raises(ValueError):
        parse_native_embedding_gpu_batch_environment(raw, attempt_hex=pins.attempt_hex)


def test_native_unit_keeps_late_bound_input_root_metadata_and_no_worker_path_access():
    service = (ROOT / "infra/systemd/eom-embedding-native-gpu-batch@.service").read_text()
    socket = (ROOT / "infra/systemd/eom-embedding-native-gpu-batch@.socket").read_text()
    for required in (
        "User=eom-embedding-cuda",
        "Group=eom-embedding-cuda",
        "SupplementaryGroups=eom-gpu-lease",
        "Type=oneshot",
        "RemainAfterExit=yes",
        "NotifyAccess=main",
        "FileDescriptorStorePreserve=yes",
        "TimeoutStartSec=180",
        "Restart=no",
        "KillMode=control-group",
        "PrivateNetwork=yes",
        "NoNewPrivileges=yes",
        "ProtectProc=invisible",
        "CapabilityBoundingSet=\n",
        "InaccessiblePaths=/run/eom-native-embedding-gpu-batch",
        " -I -B -m eom_catalog_service.embedding_gpu_batch_entry %i ",
        "StandardInput=file:/run/eom-native-embedding-gpu-batch/%i/input.json",
    ):
        assert required in service
    for required in (
        "SocketUser=root",
        "SocketGroup=root",
        "SocketMode=0600",
        "PassCredentials=yes",
        "Accept=no",
        "Backlog=1",
        "FileDescriptorName=gpu-batch-control",
    ):
        assert required in socket
    assert "Environment=PYTHONPATH=" not in service and "User=root" not in service
    assert "OpenFile=" not in service  # Bound once by root with an absolute instance path.
    # Other owners' ephemeral workspaces need not exist for this independent unit.
    # Existing paths stay inaccessible; no unrelated service is installed or started.
    for line in service.splitlines():
        if line.startswith("InaccessiblePaths="):
            for path in line.partition("=")[2].split():
                if path.lstrip("-").startswith("/run/eom-"):
                    assert path == "/run/eom-native-embedding-gpu-batch" or path.startswith(
                        "-/run/"
                    )
    assert "--model" not in service and "ReadWritePaths=/mnt/nas" not in service
