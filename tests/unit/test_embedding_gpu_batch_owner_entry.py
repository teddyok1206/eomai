"""Protected root configuration/original controller composition, with synthetic OS/GPU ports."""

from __future__ import annotations

import json
import os
import subprocess
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.embedding_gpu_control import EmbeddingGpuAllocationRequest
from eom_catalog_service import embedding_gpu_batch_owner_entry as entry
from eom_catalog_service.embedding_batch_control_connection import BATCH_CONTROL_TEMPLATE_SHA256
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_workflow.embedding_device_routing import EmbeddingDeviceRoutingPolicy

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_batch_owner_control import control_frames
from tests.unit.test_embedding_device_routing import policy_document

ROOT = Path(__file__).resolve().parents[2]


def policy_body():
    body = policy_document("REFERENCE_QUERY")
    resources = body["cuda"]["profile"]["resource_profile"]
    body["cuda"]["profile"]["resource_profile"] = seal(
        resources
        | {
            "tasks_max": 64,
            "timeout_seconds": 180,
            "output_max_bytes": 64 * 1024**2,
        },
        "resource_profile_sha256",
    )
    return seal(body, "policy_sha256")


def request_for(policy):
    return EmbeddingGpuAllocationRequest.model_validate(
        seal(
            control_frames().request.model_dump(mode="json")
            | {"routing_policy_sha256": policy.policy_sha256},
            "message_sha256",
        )
    )


def file_seam(raw):
    def read(_path, *, sha256, maximum):
        if sha256 != sha256_bytes(raw) or len(raw) > maximum:
            raise ValueError("synthetic protected file mismatch")
        return raw

    return SimpleNamespace(read=read, assert_unchanged=Mock())


def test_root_entry_uses_installed_policy_then_original_peer_before_existing_gpu_driver(
    monkeypatch,
):
    policy = EmbeddingDeviceRoutingPolicy.model_validate(policy_body())
    request = request_for(policy)
    files = file_seam(canonical_json_bytes(policy.model_dump(mode="json")))
    monkeypatch.setenv(
        "EOM_GPU_BATCH_QUERY_POLICY_SHA256",
        sha256_bytes(canonical_json_bytes(policy.model_dump(mode="json"))),
    )
    monkeypatch.setattr(entry.os, "getresuid", lambda: (0, 0, 0))
    monkeypatch.setattr(entry.os, "getresgid", lambda: (0, 0, 0))
    staged = SimpleNamespace(request=request, assert_current=Mock())
    monkeypatch.setattr(entry, "read_embedding_batch_control", Mock(return_value=staged))
    monkeypatch.setattr(entry, "NumericalRuntimeFileSnapshots", lambda: files)
    channel = Mock(
        require_direct_peer=Mock(return_value=SimpleNamespace(pid=123, uid=111, gid=111))
    )
    monkeypatch.setattr(entry, "connect_embedding_batch_source_owner", Mock(return_value=channel))
    monkeypatch.setattr(entry, "embedding_batch_owner_start_ticks", Mock(return_value=456))
    prepared = object()
    prepare = Mock(return_value=prepared)
    monkeypatch.setattr(entry, "prepare_embedding_gpu_batch_handoff", prepare)
    captured = object()

    @contextmanager
    def capture(value):
        assert value is prepared
        yield captured

    monkeypatch.setattr(entry, "capture_embedding_gpu_batch_machine", capture)
    drive = Mock()
    monkeypatch.setattr(entry, "run_embedding_gpu_batch_with_owner", drive)
    entry.run_root_embedding_batch_control("a" * 32, controller_release="a" * 40)
    pins, original = prepare.call_args.args
    assert original == request and pins.root_pid == os.getpid()
    assert (pins.timeout_seconds, pins.vector_max_bytes, pins.total_output_max_bytes) == (
        180,
        16 * 1024**2,
        64 * 1024**2,
    )
    assert (
        pins.resource_profile_sha256 == policy.cuda.profile.resource_profile.resource_profile_sha256
    )
    drive.assert_called_once_with(captured, channel, owner_start_ticks=456)
    channel.close.assert_called_once()


@pytest.mark.parametrize(
    "fault",
    ("hash", "policy", "configuration", "tasks", "timeout", "output", "threads", "missing_pin"),
)
def test_root_policy_or_resource_mismatch_is_not_gpu_busy_or_cpu_fallback(monkeypatch, fault):
    body = policy_body()
    policy = EmbeddingDeviceRoutingPolicy.model_validate(body)
    request = request_for(policy)
    if fault in {"tasks", "timeout", "output", "threads"}:
        field, value = {
            "tasks": ("tasks_max", 32),
            "timeout": ("timeout_seconds", 120),
            "output": ("output_max_bytes", 16 * 1024**2),
            "threads": ("threads", 2),
        }[fault]
        for device in ("cpu", "cuda") if fault == "threads" else ("cuda",):
            body[device]["profile"]["resource_profile"] = seal(
                body[device]["profile"]["resource_profile"] | {field: value},
                "resource_profile_sha256",
            )
        policy = EmbeddingDeviceRoutingPolicy.model_validate(seal(body, "policy_sha256"))
        request = request_for(policy)
    elif fault == "policy":
        request = EmbeddingGpuAllocationRequest.model_validate(
            seal(
                request.model_dump(mode="json") | {"routing_policy_sha256": "sha256:" + "f" * 64},
                "message_sha256",
            )
        )
    elif fault == "configuration":
        changed = request.model_dump(mode="json")
        changed["configuration"]["configuration_sha256"] = "sha256:" + "f" * 64
        request = EmbeddingGpuAllocationRequest.model_validate(seal(changed, "message_sha256"))
    raw = canonical_json_bytes(policy.model_dump(mode="json"))
    if fault == "missing_pin":
        monkeypatch.delenv("EOM_GPU_BATCH_QUERY_POLICY_SHA256", raising=False)
    else:
        monkeypatch.setenv(
            "EOM_GPU_BATCH_QUERY_POLICY_SHA256",
            "sha256:" + "f" * 64 if fault == "hash" else sha256_bytes(raw),
        )
    with pytest.raises(ValueError):
        entry._policy(file_seam(raw), request)


def test_fixed_unit_hash_bootstrap_and_secret_boundaries():
    unit = (ROOT / "infra/systemd/eom-embedding-native-gpu-batch-owner@.service").read_bytes()
    assert sha256_bytes(unit) == "sha256:" + BATCH_CONTROL_TEMPLATE_SHA256
    source = unit.decode()
    for expected in (
        "GPU_BATCH %i",
        "StartLimitBurst=1",
        "Restart=no",
        "SupplementaryGroups=eom-workflow-runner",
        "InaccessiblePaths=/etc/eom",
        "CAP_DAC_READ_SEARCH",
    ):
        assert expected in source
    assert "CAP_DAC_OVERRIDE" not in source
    bootstrap = (
        ROOT / "services/catalog_service/eom_catalog_service/embedding_owner_bootstrap.py"
    ).read_text()
    assert (
        'sys.argv[1] == "GPU_BATCH"' in bootstrap and "embedding_gpu_batch_owner_entry" in bootstrap
    )
    assert entry.main() == 1  # Source execution is not a protected installed release.


def test_polkit_evaluates_only_fixed_owner_start_and_never_native_worker_control():
    # Node already belongs to the GUI toolchain; no production dependency is added.
    script = ROOT / "infra/polkit/49-eom-embedding-gpu-batch.rules"
    cases = []
    owner = "eom-embedding-native-gpu-batch-owner@" + "a" * 32 + ".service"
    for user in ("eom-workflow-runner", "eom", "eom-worker-01", "eom-embedding-cuda"):
        for verb in ("start", "stop", "restart"):
            cases.append(
                [
                    user,
                    verb,
                    owner,
                    "YES" if (user, verb) == ("eom-workflow-runner", "start") else "NO",
                ]
            )
    for suffix in ("service", "socket"):
        cases.append(
            [
                "eom-workflow-runner",
                "start",
                "eom-embedding-native-gpu-batch@" + "a" * 32 + "." + suffix,
                "NO",
            ]
        )
    program = """
let rule;
global.polkit={Result:{YES:'YES',NO:'NO',NOT_HANDLED:'NOT_HANDLED'},addRule:f=>rule=f};
eval(require('fs').readFileSync(process.argv[1],'utf8'));
for(const [user,verb,unit,want] of JSON.parse(process.argv[2])) {
  const got=rule({id:'org.freedesktop.systemd1.manage-units',
                  lookup:k=>({unit,verb})[k]}, {user});
  if(got!==want) process.exit(1);
}
"""
    result = subprocess.run(
        ("/usr/bin/node", "-e", program, str(script), json.dumps(cases)),
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
