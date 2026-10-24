"""Protected measurement-code equivalence for an existing benchmark's continuation.

Compare installed implementations, never Git or model input. Per-launch source
identities remain distinct and must still be validated by the finalizer.
"""

from __future__ import annotations

import re
from pathlib import Path

from eom_catalog_service.embedding_runtime_files import NumericalRuntimeFileSnapshots

_RELEASE_ROOT = Path("/opt/eom/embedding-owner-releases")
# The suffix scheduler and current finalizer revalidate the complete journal,
# rather than generate measurements. HTTP/login adapters are not numerical code.
# Native binaries/model/backend pins remain independently checked at each launch.
_CATALOG_MEASUREMENT_MEMBERS = (
    "embedding_benchmark_activation.py",
    "embedding_benchmark_budget_entrypoint.py",
    "embedding_benchmark_channel.py",
    "embedding_benchmark_control_channel.py",
    "embedding_benchmark_cpu.py",
    "embedding_benchmark_cpu_driver.py",
    "embedding_benchmark_cpu_reference.py",
    "embedding_benchmark_cuda.py",
    "embedding_benchmark_cuda_capture.py",
    "embedding_benchmark_cuda_driver.py",
    "embedding_benchmark_cuda_lifetime.py",
    "embedding_benchmark_cuda_observation.py",
    "embedding_benchmark_cuda_unacknowledged.py",
    "embedding_benchmark_entrypoint.py",
    "embedding_benchmark_gpu_observation.py",
    "embedding_benchmark_gpu_resource_client.py",
    "embedding_benchmark_handoff.py",
    "embedding_benchmark_host_memory.py",
    "embedding_benchmark_launch.py",
    "embedding_benchmark_launch_execution.py",
    "embedding_benchmark_launch_publication.py",
    "embedding_benchmark_launch_workspace.py",
    "embedding_benchmark_layout.py",
    "embedding_benchmark_native_connection.py",
    "embedding_benchmark_native_observation.py",
    "embedding_benchmark_numerical_assessment.py",
    "embedding_benchmark_numerical_read.py",
    "embedding_benchmark_owner_admission.py",
    "embedding_benchmark_owner_composition.py",
    "embedding_benchmark_ranking.py",
    "embedding_benchmark_resource_relay.py",
    "embedding_benchmark_root_connection.py",
    "embedding_benchmark_root_control.py",
    "embedding_benchmark_root_socket.py",
    "embedding_benchmark_sources.py",
    "embedding_benchmark_timing_evidence.py",
    "embedding_benchmark_timing_read.py",
    "embedding_benchmark_token_preparation.py",
    "embedding_benchmark_unit_control.py",
    "embedding_benchmark_unit_policy.py",
    "embedding_device_comparison.py",
    "embedding_runtime_files.py",
    "embedding_native_backend_pins.py",
    "embedding_cuda_host_closure.py",
    "embedding_runtime_prefix_closure.py",
    "gpu_unit_terminal_observation.py",
    "unit_effect_records.py",
)
_MEASUREMENT_MEMBERS = (
    *("eom_catalog_service/" + name for name in _CATALOG_MEASUREMENT_MEMBERS),
    "eom_orchestrator/embedding_device_benchmark_owner.py",
    "eom_orchestrator/inference_transfer_cpu_systemd.py",
    "eom_workflow/embedding_benchmark_launch_control.py",
    "eom_catalog_contracts/embedding_device_benchmark.py",
)


def capture_equivalent_controller_measurements(
    releases: tuple[str, ...],
) -> NumericalRuntimeFileSnapshots:
    """O(releases * fixed members), bounded reads, no persistent cache or grant.

    Keep this capture through measurement collection and recheck epochs. Different, missing
    or unprotected members fail. Producer/source, policy, runtime and all six
    original ordered receipts remain separately mandatory.
    """
    if (
        not isinstance(releases, tuple)
        or not 1 <= len(releases) <= 6
        or any(
            type(value) is not str or re.fullmatch(r"[0-9a-f]{40}", value) is None
            for value in releases
        )
    ):
        raise ValueError("BENCHMARK_CONTROLLER_MEASUREMENT_SELECTION_INVALID")
    files = NumericalRuntimeFileSnapshots(0)
    selected = sorted(set(releases))
    if len(selected) == 1:
        return files
    expected: tuple[str, ...] | None = None
    for source in selected:
        root = _RELEASE_ROOT / source / "site-packages"
        hashes = tuple(
            files.observe_protected_member_bytes(root / name, maximum=131072).sha256
            for name in _MEASUREMENT_MEMBERS
        )
        if expected is not None and hashes != expected:
            raise ValueError("BENCHMARK_CONTROLLER_MEASUREMENT_CHANGED")
        expected = hashes
    files.assert_unchanged()
    return files
