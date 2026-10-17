"""Synthetic readiness claims only, never a real Job, root ACK, retained lock or GPU."""

from eom_catalog_contracts.embedding_benchmark_cuda_ready import BenchmarkCudaReady
from eom_catalog_contracts.embedding_native_installation_evidence import (
    RootLocalNativeConfigurationPin,
)
from eom_identifiers import sha256_bytes

from tests.unit.embedding_device_benchmark_fixtures import worker_invocation
from tests.unit.embedding_installed_runtime_fixtures import runtime_proof
from tests.unit.inference_transfer_embedding_fixtures import seal


def benchmark_cuda_ready():
    from eom_catalog_contracts.embedding_device_benchmark import embedding_device_benchmark_bytes

    invocation = worker_invocation(2)
    configuration = RootLocalNativeConfigurationPin(
        configuration_id="embeddingnativeconfig_" + "a" * 32,
        configuration_revision_id="embeddingnativeconfigrev_" + "b" * 32,
        configuration_sha256="sha256:" + "c" * 64,
        configuration_raw_sha256="sha256:" + "d" * 64,
    )
    body = {
        "schema_version": "embedding-benchmark-cuda-ready/1.0",
        "evidence_state": "RETENTION_REQUESTED_NOT_COMPUTE_ADMITTED",
        "execution_id": invocation.execution_id,
        "job_id": invocation.job_id,
        "invocation_raw_sha256": sha256_bytes(embedding_device_benchmark_bytes(invocation)),
        "configuration": configuration.model_dump(mode="json"),
        "receipt_raw_sha256": "sha256:" + "e" * 64,
        "fdstore_name": "eom-gpu0-lease",
        "pid": 123,
        "start_time_ticks": 999,
        "worker_uid": 1234,
        "worker_gid": 1234,
        "supplementary_gids": [2468],
        "resource_fds": {
            "nvidia0_fd": 10,
            "nvidiactl_fd": 11,
            "nvidia_uvm_fd": 12,
            "nvidia_uvm_tools_fd": 13,
            "lease_fd": 14,
        },
        "expected_device_capture": runtime_proof("CUDA_INDEX_FP32").device_capture.model_dump(
            mode="json"
        ),
        "cuda_initialization_calls": 0,
        "cuda_synchronize_calls": 0,
        "model_constructor_calls": 0,
        "tokenizer_constructor_calls": 0,
        "forward_calls": 0,
    }
    return invocation, BenchmarkCudaReady.model_validate(seal(body, "ready_sha256"))
