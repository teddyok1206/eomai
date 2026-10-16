"""Fixed nonprivileged two-phase CUDA installation probe; no models, launch or admission."""

from __future__ import annotations

import fcntl
import os
import re
import signal
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from eom_catalog_service.embedding_native_entrypoint import (
    discard_native_embedding_diagnostics,
    require_native_embedding_identity,
)
from eom_catalog_service.embedding_native_probe_transport import (
    capture_native_probe_descriptors,
    native_probe_file_epoch,
    read_native_probe_input,
    require_native_probe_write_denied,
    wait_native_probe_owner_ack,
    write_native_probe_report,
)

if TYPE_CHECKING:
    from eom_catalog_contracts.embedding_installed_runtime_proof import (
        EmbeddingInstalledRuntimeProof,
    )
    from eom_catalog_contracts.embedding_native_cuda_probe import (
        NativeCudaProbeInput,
        NativeCudaProbeLeaseReady,
        NativeCudaProbeResult,
    )
    from eom_catalog_contracts.embedding_native_runtime_config import (
        EmbeddingNativeRuntimeConfigV12,
    )

    from eom_catalog_service.embedding_bundle_resolver import ResolvedEmbeddingBundle
    from eom_catalog_service.embedding_cuda_probe_resource_files import (
        CapturedCudaProbeResourceFiles,
    )
    from eom_catalog_service.embedding_runtime_files import NumericalRuntimeFileSnapshots

PROFILE: Final = "CUDA_INDEX_FP32"
_CONFIG_ROOT = Path("/opt/eom/embedding-native-config")
_PROOF_ROOT = Path("/opt/eom/embedding-runtime-proofs")
_BUNDLE_ROOT = Path("/opt/eom/embedding-runtime-bundles")
_MODEL_ROOT = Path("/opt/eom/embedding-models")
_HANDOFF_ROOT = Path("/run/eom-embedding-native-cuda-probe")


@dataclass(frozen=True, slots=True)
class _PreparedCudaProbe:
    request: NativeCudaProbeInput
    request_raw: bytes
    configuration: EmbeddingNativeRuntimeConfigV12
    configuration_raw: bytes
    proof: EmbeddingInstalledRuntimeProof
    proof_raw: bytes
    files: NumericalRuntimeFileSnapshots
    bundle: ResolvedEmbeddingBundle
    resources: CapturedCudaProbeResourceFiles
    ready: NativeCudaProbeLeaseReady

    def assert_current(self) -> None:
        from eom_catalog_service.embedding_runtime_files import (
            require_cuda_loader_working_directory,
        )

        require_native_embedding_identity(PROFILE)
        require_cuda_loader_working_directory(self.files)
        self.files.assert_unchanged()
        self.bundle.assert_unchanged()
        self.resources.assert_current()


def _load_probe_metadata(
    request: NativeCudaProbeInput,
) -> tuple[
    NumericalRuntimeFileSnapshots,
    EmbeddingNativeRuntimeConfigV12,
    bytes,
    EmbeddingInstalledRuntimeProof,
    bytes,
    ResolvedEmbeddingBundle,
]:
    import json

    from eom_catalog_contracts.embedding_installed_runtime_proof import (
        MAX_INSTALLED_RUNTIME_PROOF_BYTES,
        parse_installed_runtime_proof,
    )
    from eom_catalog_contracts.embedding_native_cuda_probe import (
        validate_native_cuda_probe_configuration,
    )
    from eom_catalog_contracts.embedding_native_runtime_config import (
        MAX_NATIVE_RUNTIME_CONFIG_BYTES,
        EmbeddingNativeRuntimeConfigV12,
        parse_installed_embedding_native_runtime_config_bytes,
    )

    from eom_catalog_service.embedding_bundle_resolver import (
        ConfiguredEmbeddingBundle,
        resolve_configured_embedding_bundle,
    )
    from eom_catalog_service.embedding_runtime_files import (
        NumericalRuntimeFileSnapshots,
        require_cuda_loader_working_directory,
    )

    files = NumericalRuntimeFileSnapshots(0)
    pin = request.configuration
    config_raw = files.read(
        _CONFIG_ROOT / pin.configuration_id / pin.configuration_revision_id / "config.json",
        sha256=pin.configuration_raw_sha256,
        maximum=MAX_NATIVE_RUNTIME_CONFIG_BYTES,
    )
    configuration = parse_installed_embedding_native_runtime_config_bytes(config_raw)
    if not isinstance(configuration, EmbeddingNativeRuntimeConfigV12):
        raise ValueError("NATIVE_CUDA_PROBE_CONFIGURATION_INVALID")
    require_cuda_loader_working_directory(files)
    proof_pin = request.installed_proof
    proof_raw = files.read(
        _PROOF_ROOT / proof_pin.proof_id / proof_pin.proof_revision_id / "proof.json",
        sha256=proof_pin.proof_raw_sha256,
        maximum=MAX_INSTALLED_RUNTIME_PROOF_BYTES,
    )
    proof = parse_installed_runtime_proof(json.loads(proof_raw))
    bundle = resolve_configured_embedding_bundle(
        ConfiguredEmbeddingBundle(_BUNDLE_ROOT, _MODEL_ROOT, configuration.bundle),
        observe_member_identity=files.observe_protected_member_identity,
    )
    validate_native_cuda_probe_configuration(
        request,
        configuration=configuration,
        configuration_raw=config_raw,
        bundle=bundle.bundle,
        bundle_raw=bundle.manifest.raw,
        proof=proof,
        proof_raw=proof_raw,
    )
    files.assert_unchanged()
    bundle.assert_unchanged()
    return files, configuration, config_raw, proof, proof_raw, bundle


def _probe_denials(bundle: ResolvedEmbeddingBundle) -> dict[str, str]:
    from eom_catalog_service.inference_transfer_cpu_verifier import (
        DENIED_FILES,
        DENIED_SOCKETS,
        denied_file,
        denied_socket,
        verify_no_network,
    )

    verify_no_network()
    reads = (
        *(
            ("legacy_handoff" if name == "handoff_workspace" else name, path)
            for name, path in DENIED_FILES
            if name != "gpu"
        ),
        ("legacy_repository", Path("/home/eom/EOMIS")),
        ("probe_workspace", _HANDOFF_ROOT),
    )
    denials = {name: denied_file(path) for name, path in reads}
    denials.update((name, denied_socket(path)) for name, path in DENIED_SOCKETS)
    require_native_probe_write_denied(PROFILE, Path(__file__).absolute())
    denials["prefix_write"] = "DENIED"
    spec = bundle.bundle.payload_model_spec
    for path in (
        bundle.payload.root / "manifest.json",
        *(bundle.payload.root / member.member_path for member in spec.files),
    ):
        require_native_probe_write_denied(PROFILE, path)
    denials["model_write"] = "DENIED"
    return denials


@contextmanager
def _prepare_cuda_probe(request: NativeCudaProbeInput, raw: bytes) -> Iterator[_PreparedCudaProbe]:
    from eom_catalog_contracts.embedding_installed_runtime_proof import CudaRuntimeDeviceCapture
    from eom_catalog_contracts.embedding_native_cuda_probe import (
        NativeCudaProbeLeaseReady,
        parse_native_cuda_probe_input,
        validate_native_cuda_probe_ready_references,
    )
    from eom_gpu_lease import acquire_shared_gpu_lease, request_unit_gpu_lease_retention
    from eom_identifiers import sha256_bytes

    from eom_catalog_service.embedding_cuda_probe_resource_files import (
        capture_cuda_probe_resource_files,
    )

    require_native_embedding_identity(PROFILE)
    if parse_native_cuda_probe_input(raw) != request:
        raise ValueError("NATIVE_CUDA_PROBE_INPUT_CHANGED")
    files, config, config_raw, proof, proof_raw, bundle = _load_probe_metadata(request)
    if not isinstance(proof.device_capture, CudaRuntimeDeviceCapture):
        raise ValueError("NATIVE_CUDA_PROBE_DEVICE_INVALID")
    lease = acquire_shared_gpu_lease()
    try:
        with capture_cuda_probe_resource_files(proof.device_capture, lease) as resources:
            request_unit_gpu_lease_retention(lease)
            resources.assert_current()
            metadata = resources.shared_gpu_lease
            ready = NativeCudaProbeLeaseReady.model_validate(
                {
                    "schema_version": "embedding-native-cuda-probe-lease-ready/1.0",
                    "evidence_state": "RETENTION_REQUESTED_NOT_CUDA_ADMITTED",
                    "execution_id": request.execution_id,
                    "input_raw_sha256": sha256_bytes(raw),
                    "configuration": request.configuration.model_dump(mode="json"),
                    "fdstore_name": "eom-gpu0-lease",
                    "pid": metadata.holder_pid,
                    "start_time_ticks": metadata.holder_start_time_ticks,
                    "worker_uid": os.geteuid(),
                    "worker_gid": os.getegid(),
                    "supplementary_gids": sorted(set(os.getgroups()) - {os.getegid()}),
                    "payload_file_set_sha256": request.payload.file_set_sha256,
                    "resource_fds": resources.resource_descriptors.model_dump(mode="json"),
                    "expected_device_capture": proof.device_capture.model_dump(mode="json"),
                    "cuda_initialization_calls": 0,
                    "cuda_synchronize_calls": 0,
                    "model_constructor_calls": 0,
                    "tokenizer_constructor_calls": 0,
                    "forward_calls": 0,
                }
            )
            validate_native_cuda_probe_ready_references(
                request,
                raw,
                ready,
                configuration=config,
                configuration_raw=config_raw,
                bundle=bundle.bundle,
                bundle_raw=bundle.manifest.raw,
                proof=proof,
                proof_raw=proof_raw,
            )
            prepared = _PreparedCudaProbe(
                request, raw, config, config_raw, proof, proof_raw, files, bundle, resources, ready
            )
            prepared.assert_current()
            try:
                yield prepared
            finally:
                prepared.assert_current()
    finally:
        # This closes only our original; any PID1 copy survives failure and exit.
        lease.close()


def _observe_after_ready_ack(prepared: _PreparedCudaProbe) -> NativeCudaProbeResult:
    from eom_catalog_contracts.embedding_native_cuda_probe import (
        NativeCudaProbeResult,
        validate_native_cuda_probe_progression,
        validate_native_cuda_probe_references,
    )

    from eom_catalog_service.embedding_cuda_probe_resource_files import (
        open_cuda_probe_device_access,
    )
    from eom_catalog_service.embedding_installed_runtime_observer import (
        ConfiguredInstalledRuntimeProof,
        ProtectedInstalledEmbeddingRuntimeObserver,
    )
    from eom_catalog_service.embedding_offline_backend import observe_native_runtime_without_model

    prepared.assert_current()
    denials = _probe_denials(prepared.bundle)
    with open_cuda_probe_device_access(prepared.resources) as ownership:
        observer = ProtectedInstalledEmbeddingRuntimeObserver(
            ConfiguredInstalledRuntimeProof(prepared.request.installed_proof),
            cuda_ownership=ownership,
        )
        runtime = observe_native_runtime_without_model(
            profile=PROFILE,
            runtime_observer=observer,
            cuda_ownership=ownership,
        )
        ready = prepared.ready
        result = NativeCudaProbeResult.model_validate(
            {
                **{
                    name: getattr(ready, name)
                    for name in (
                        "execution_id",
                        "input_raw_sha256",
                        "pid",
                        "start_time_ticks",
                        "worker_uid",
                        "worker_gid",
                        "supplementary_gids",
                        "payload_file_set_sha256",
                        "resource_fds",
                    )
                },
                "schema_version": "embedding-native-cuda-probe-result/1.0",
                "evidence_state": "OBSERVED_NOT_ADMITTED",
                "recipe": "NATIVE_CUDA_FIXED_UNIT_NO_MODEL_NO_FORWARD_NEGATIVES/1.0",
                "checked_model_members": len(prepared.bundle.bundle.payload_model_spec.files) + 1,
                "denials": denials,
                "numerical_runtime": runtime.model_dump(mode="json"),
                "device_capture": ready.expected_device_capture.model_dump(mode="json"),
                "cuda_initialization_calls": 1,
                "cuda_synchronize_calls": 1,
                "model_constructor_calls": 0,
                "tokenizer_constructor_calls": 0,
                "forward_calls": 0,
            }
        )
        validate_native_cuda_probe_progression(
            prepared.request, prepared.request_raw, ready, result
        )
        validate_native_cuda_probe_references(
            prepared.request,
            prepared.request_raw,
            result,
            configuration=prepared.configuration,
            configuration_raw=prepared.configuration_raw,
            bundle=prepared.bundle.bundle,
            bundle_raw=prepared.bundle.manifest.raw,
            proof=prepared.proof,
            proof_raw=prepared.proof_raw,
        )
        prepared.assert_current()
        return result


def _no_early_exit_ack() -> None:
    if signal.SIGUSR2 in signal.sigpending():
        raise ValueError("NATIVE_CUDA_PROBE_EARLY_EXIT_ACK")


def run_native_cuda_probe(
    execution_id: str, *, input_fd: int, ready_fd: int, result_fd: int
) -> None:
    require_native_embedding_identity(PROFILE)
    if re.fullmatch(r"[0-9a-f]{32}", execution_id) is None:
        raise ValueError("NATIVE_CUDA_PROBE_EXECUTION_INVALID")
    signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGUSR1, signal.SIGUSR2})
    initial, (ready_epoch, result_epoch) = capture_native_probe_descriptors(
        PROFILE, input_fd, (ready_fd, result_fd)
    )
    raw = read_native_probe_input(PROFILE, input_fd, initial)
    from eom_catalog_contracts.embedding_native_cuda_probe import parse_native_cuda_probe_input
    from eom_identifiers import canonical_json_bytes

    request = parse_native_cuda_probe_input(raw)
    if request.execution_id != execution_id:
        raise ValueError("NATIVE_CUDA_PROBE_EXECUTION_MISMATCH")
    with _prepare_cuda_probe(request, raw) as prepared:
        write_native_probe_report(
            PROFILE, ready_fd, canonical_json_bytes(prepared.ready), ready_epoch
        )
        _no_early_exit_ack()
        wait_native_probe_owner_ack(PROFILE, signal.SIGUSR1)
        _no_early_exit_ack()
        if native_probe_file_epoch(os.fstat(input_fd)) != native_probe_file_epoch(initial):
            raise ValueError("NATIVE_CUDA_PROBE_INPUT_CHANGED")
        prepared.assert_current()
        result = _observe_after_ready_ack(prepared)
        _no_early_exit_ack()
        write_native_probe_report(PROFILE, result_fd, canonical_json_bytes(result), result_epoch)
        wait_native_probe_owner_ack(PROFILE, signal.SIGUSR2)
        prepared.assert_current()
        if native_probe_file_epoch(os.fstat(input_fd)) != native_probe_file_epoch(initial):
            raise ValueError("NATIVE_CUDA_PROBE_INPUT_CHANGED")


def main() -> int:
    owned: list[int] = []
    try:
        if len(sys.argv) != 2:
            return 2
        result_fd = fcntl.fcntl(1, fcntl.F_DUPFD_CLOEXEC, 3)
        owned.append(result_fd)
        ready_fd = fcntl.fcntl(2, fcntl.F_DUPFD_CLOEXEC, 3)
        owned.append(ready_fd)
        with discard_native_embedding_diagnostics():
            run_native_cuda_probe(sys.argv[1], input_fd=0, ready_fd=ready_fd, result_fd=result_fd)
        return 0
    except Exception:
        return 1
    finally:
        failed = False
        for descriptor in reversed(owned):
            try:
                os.close(descriptor)
            except OSError:
                failed = True
        if failed:
            raise ValueError("NATIVE_CUDA_PROBE_DESCRIPTOR_CLEANUP_UNCERTAIN")


if __name__ == "__main__":
    raise SystemExit(main())
