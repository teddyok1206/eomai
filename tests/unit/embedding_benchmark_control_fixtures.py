"""Synthetic original-launch metadata only; no authority, runtime or cleanup attestation."""

import os
import time

from eom_catalog_contracts.embedding_device_benchmark import embedding_device_benchmark_bytes
from eom_identifiers import sha256_bytes
from eom_workflow.embedding_benchmark_launch_control import (
    BenchmarkLaunchAssociation,
    BenchmarkLaunchCompleted,
    BenchmarkLaunchPrepared,
    BenchmarkLaunchUncertain,
)

from tests.unit.embedding_device_benchmark_fixtures import (
    owner_request,
    resources,
    staged_inputs,
    worker_invocation,
)
from tests.unit.inference_transfer_embedding_fixtures import seal


def association(ordinal=1):
    request, invocation, inputs = owner_request(), worker_invocation(ordinal), staged_inputs()
    raw_request, raw_invocation, raw_inputs = (
        embedding_device_benchmark_bytes(v) for v in (request, invocation, inputs)
    )
    return BenchmarkLaunchAssociation.model_validate(
        seal(
            dict(
                schema_version="embedding-benchmark-launch-control/1.0",
                record_type="ASSOCIATION",
                job_id=invocation.job_id,
                execution_id=invocation.execution_id,
                device=invocation.device,
                launch_ordinal=ordinal,
                invocation_sha256=invocation.invocation_sha256,
                owner_request_sha256=request.request_sha256,
                request=dict(
                    member_name="owner-request.json",
                    sha256=sha256_bytes(raw_request),
                    byte_count=len(raw_request),
                ),
                invocation=dict(
                    member_name="invocation.json",
                    sha256=sha256_bytes(raw_invocation),
                    byte_count=len(raw_invocation),
                ),
                inputs=dict(
                    member_name="benchmark-inputs.json",
                    sha256=sha256_bytes(raw_inputs),
                    byte_count=len(raw_inputs),
                ),
                owner_pid=os.getpid(),
                owner_start_ticks=1,
                expires_ns=time.monotonic_ns() + 60 * 10**9,
            ),
            "association_sha256",
        )
    )


def prepared(value):
    return BenchmarkLaunchPrepared.model_validate(
        seal(
            dict(
                schema_version="embedding-benchmark-launch-control/1.0",
                record_type="PREPARED",
                association_sha256=value.association_sha256,
                job_id=value.job_id,
                execution_id=value.execution_id,
                invocation_sha256=value.invocation_sha256,
                environment_raw_sha256="sha256:" + "a" * 64,
                controller_release="a" * 40,
                backend=dict(
                    configuration_id="embeddingnativeconfig_" + "a" * 32,
                    configuration_revision_id="embeddingnativeconfigrev_" + "b" * 32,
                    configuration_sha256="sha256:" + "c" * 64,
                    configuration_raw_sha256="sha256:" + "d" * 64,
                    receipt_raw_sha256="sha256:" + "e" * 64,
                ),
            ),
            "prepared_sha256",
        )
    )


def completed(value, before):
    return BenchmarkLaunchCompleted.model_validate(
        seal(
            dict(
                schema_version="embedding-benchmark-launch-control/1.0",
                record_type="COMPLETED",
                association_sha256=value.association_sha256,
                prepared_sha256=before.prepared_sha256,
                job_id=value.job_id,
                execution_id=value.execution_id,
                invocation_sha256=value.invocation_sha256,
                device=value.device,
                launch_ordinal=value.launch_ordinal,
                original_outcome="SUCCEEDED",
                cleanup="CONFIRMED",
                started_ns=100,
                completed_ns=200,
                resources=resources(value.launch_ordinal).model_dump(mode="json")
                if value.device == "CUDA"
                else None,
            ),
            "completion_sha256",
        )
    )


def uncertain(value):
    return BenchmarkLaunchUncertain.model_validate(
        seal(
            dict(
                schema_version="embedding-benchmark-launch-control/1.0",
                record_type="UNCERTAIN",
                association_sha256=value.association_sha256,
                job_id=value.job_id,
                execution_id=value.execution_id,
                invocation_sha256=value.invocation_sha256,
                code="BENCHMARK_ROOT_EXECUTION_UNCERTAIN",
            ),
            "uncertainty_sha256",
        )
    )
