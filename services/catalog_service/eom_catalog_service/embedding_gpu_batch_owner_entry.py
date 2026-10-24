"""Fixed protected root-service entry: existing physical controller through actual owner IPC."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from eom_catalog_contracts.embedding_gpu_control import (
    EmbeddingGpuAllocationRequest,
    embedding_gpu_control_bytes,
)
from eom_catalog_contracts.embedding_native_installation_evidence import (
    parse_rootlocal_evidence_document,
)
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_workflow.embedding_device_routing import (
    MAX_EMBEDDING_DEVICE_ROUTING_BYTES,
    EmbeddingDeviceRoutingPolicy,
)
from eom_workflow.native_embedding_backend_selection import NativeCudaBackendSelection

from eom_catalog_service.embedding_batch_control_connection import (
    connect_embedding_batch_source_owner,
)
from eom_catalog_service.embedding_batch_control_workspace import read_embedding_batch_control
from eom_catalog_service.embedding_batch_owner_identity import embedding_batch_owner_start_ticks
from eom_catalog_service.embedding_batch_owner_proxy import run_embedding_gpu_batch_with_owner
from eom_catalog_service.embedding_gpu_batch_handoff import prepare_embedding_gpu_batch_handoff
from eom_catalog_service.embedding_gpu_batch_launch import (
    NativeEmbeddingGpuBatchLaunchPins,
    native_embedding_gpu_batch_unit,
)
from eom_catalog_service.embedding_gpu_batch_observation import capture_embedding_gpu_batch_machine
from eom_catalog_service.embedding_native_backend_pins import NativeEmbeddingBackendPins
from eom_catalog_service.embedding_runtime_files import NumericalRuntimeFileSnapshots

_POLICIES = {
    "INDEX": (
        Path("/opt/eom/embedding-batch-policies/index.json"),
        "EOM_GPU_BATCH_INDEX_POLICY_SHA256",
    ),
    "REFERENCE_QUERY": (
        Path("/opt/eom/embedding-batch-policies/query.json"),
        "EOM_GPU_BATCH_QUERY_POLICY_SHA256",
    ),
}


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("EMBEDDING_GPU_BATCH_OWNER_ENTRY_INVALID")


def _policy(
    files: NumericalRuntimeFileSnapshots, request: EmbeddingGpuAllocationRequest
) -> EmbeddingDeviceRoutingPolicy:
    _require(request.purpose in _POLICIES)
    path, variable = _POLICIES[request.purpose]
    expected = os.environ.get(variable, "")
    _require(re.fullmatch(r"sha256:[0-9a-f]{64}", expected, re.ASCII) is not None)
    raw = files.read(path, sha256=expected, maximum=MAX_EMBEDDING_DEVICE_ROUTING_BYTES)
    policy = EmbeddingDeviceRoutingPolicy.model_validate(
        parse_rootlocal_evidence_document(raw, MAX_EMBEDDING_DEVICE_ROUTING_BYTES)
    )
    _require(
        canonical_json_bytes(policy.model_dump(mode="json")) == raw
        and policy.purpose == request.purpose
        and policy.policy_sha256 == request.routing_policy_sha256
        and type(policy.cuda.backend.backend) is NativeCudaBackendSelection
        and policy.cuda.backend.backend.configuration == request.configuration
        and policy.cuda.backend.backend.receipt_raw_sha256 == request.receipt_raw_sha256
    )
    resources = policy.cuda.profile.resource_profile
    # Actual fixed native unit ceilings, not a permissive user-supplied profile.
    _require(
        resources.device == "CUDA"
        and resources.threads == 4
        and resources.memory_max_bytes >= 6 * 1024**3
        and resources.cpu_quota_percent >= 400
        and resources.tasks_max >= 64
        and resources.timeout_seconds >= 180
        and resources.output_max_bytes >= 64 * 1024**2
        and resources.maximum_active_launches == 1
        and resources.physical_gpu_lease == "SHARED_GPU0"
        and resources.network == "DISABLED"
    )
    files.assert_unchanged()
    return policy


def run_root_embedding_batch_control(attempt_hex: str, *, controller_release: str) -> None:
    """Called by the protected fixed unit; no direct DB/NAS/source authority is acquired."""
    _require(os.getresuid() == (0, 0, 0) and os.getresgid() == (0, 0, 0))
    native_embedding_gpu_batch_unit(attempt_hex)
    _require(re.fullmatch(r"[0-9a-f]{40}", controller_release, re.ASCII) is not None)
    staged = read_embedding_batch_control(attempt_hex)
    files = NumericalRuntimeFileSnapshots()
    policy = _policy(files, staged.request)
    pins = NativeEmbeddingGpuBatchLaunchPins(
        attempt_hex,
        sha256_bytes(embedding_gpu_control_bytes(staged.request)),
        os.getpid(),
        policy.cuda.profile.resource_profile.resource_profile_sha256,
        180,
        16 * 1024**2,
        64 * 1024**2,
        NativeEmbeddingBackendPins(
            staged.request.configuration.configuration_id,
            staged.request.configuration.configuration_revision_id,
            staged.request.configuration.configuration_sha256,
            staged.request.configuration.configuration_raw_sha256,
            staged.request.receipt_raw_sha256,
        ),
    )
    channel = connect_embedding_batch_source_owner(staged, controller_release=controller_release)
    try:
        peer = channel.require_direct_peer()
        birth = embedding_batch_owner_start_ticks(peer.pid, uid=peer.uid, gid=peer.gid)
        files.assert_unchanged()
        staged.assert_current()
        prepared = prepare_embedding_gpu_batch_handoff(pins, staged.request)
        with capture_embedding_gpu_batch_machine(prepared) as captured:
            files.assert_unchanged()
            run_embedding_gpu_batch_with_owner(captured, channel, owner_start_ticks=birth)
            files.assert_unchanged()
    finally:
        channel.close()


def main() -> int:
    try:
        _require(sys.flags.isolated == 1 and sys.dont_write_bytecode and len(sys.argv) == 2)
        release = Path(__file__).parent.parent.parent
        bootstrap = Path(sys.argv[0])
        _require(
            release.parent == Path("/opt/eom/embedding-owner-releases")
            and re.fullmatch(r"[0-9a-f]{40}", release.name, re.ASCII) is not None
            and bootstrap == release / "prepare_native_index.py"
        )
        run_root_embedding_batch_control(sys.argv[1], controller_release=release.name)
        return 0
    except Exception:
        return 1  # Protected unit emits no credentials, input, paths or arbitrary exception text.


if __name__ == "__main__":
    raise SystemExit(main())
