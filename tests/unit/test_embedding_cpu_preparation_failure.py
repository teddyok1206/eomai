"""Preparation-only recovery contracts; no runtime grant, model or SQL writes."""

from pathlib import Path
from unittest.mock import Mock

import pytest
from eom_identifiers import sha256_bytes
from eom_workflow.embedding_cpu_failure_recovery import (
    CpuEmbeddingFailureRecoveryCommand,
    RetiredNativeCpuIndexFailure,
)
from eom_workflow.embedding_cpu_preparation_failure import (
    CPU_PREPARATION_FAILURE_SCHEMA_SHA256,
    CpuPreparationFailureRecoveryCommand,
    KnownFailedCpuPreparationEncoding,
    RetiredNativeCpuPreparationFailure,
)
from eom_workflow.embedding_encoding_recovery import (
    encoding_failure_disposition,
    parse_supported_encoding_failure,
    parse_supported_failure_recovery,
)
from eom_workflow.local_embedding_request_v2 import supported_local_embedding_request_service
from eom_workflow_runner.local_indexing_allocated_failure_recovery import (
    AllocatedIndexingFailureRecoveryError,
    recover_retired_indexing_workflow,
)

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_cpu_failure_recovery import cpu_command, cpu_failure, cpu_root
from tests.unit.test_public_solution_native_carriers import public_native_fixture


def preparation_root(*, native_job_id="job_" + "a" * 32):
    value = cpu_root(native_job_id=native_job_id)
    value = {
        key: val
        for key, val in value.items()
        if not key.startswith("numeric_") or key == "numeric_template_sha256"
    }
    value.update(
        kind="NATIVE_CPU_INDEX_PREPARATION_FAILED",
        prepare_started_monotonic_us=1000,
        prepare_exited_monotonic_us=2000,
        prepare_result="exit-code",
        prepare_exec_main_code=1,
        prepare_exec_main_status=1,
        numeric_state="NOT_STARTED",
    )
    return seal(value, "proof_sha256")


def preparation_command():
    return seal(
        cpu_command()
        | {"schema_version": "embedding-encoding-recovery/4.0", "root": preparation_root()},
        "command_sha256",
    )


def preparation_failure():
    body = cpu_failure()
    return seal(
        body
        | {
            "schema_version": "embedding-encoding-recovery/4.0",
            "root": preparation_root(native_job_id=body["native_launch_job_id"]),
        },
        "event_sha256",
    )


def test_schema_mirror_hash_and_independent_closed_dispatch():
    root = Path(__file__).resolve().parents[2]
    name = "embedding-encoding-recovery-v4.schema.json"
    raw = (root / "schemas/workflow" / name).read_bytes()
    assert raw == (root / "packages/workflow/eom_workflow/resources" / name).read_bytes()
    assert sha256_bytes(raw) == CPU_PREPARATION_FAILURE_SCHEMA_SHA256
    assert isinstance(
        parse_supported_failure_recovery(preparation_command()),
        CpuPreparationFailureRecoveryCommand,
    )
    assert isinstance(
        parse_supported_encoding_failure(preparation_failure()), KnownFailedCpuPreparationEncoding
    )
    disposition = encoding_failure_disposition(
        parse_supported_encoding_failure(preparation_failure())
    )
    assert disposition.code == "EMBEDDING_NATIVE_PREPARATION_FAILED_RETIRED"
    with pytest.raises(ValueError):
        RetiredNativeCpuIndexFailure.model_validate(preparation_root())
    with pytest.raises(ValueError):
        CpuEmbeddingFailureRecoveryCommand.model_validate(preparation_command())


@pytest.mark.parametrize(
    "field,value",
    [
        ("prepare_result", "success"),
        ("prepare_started_monotonic_us", 0),
        ("prepare_started_monotonic_us", True),
        ("prepare_exited_monotonic_us", 1),
        ("numeric_state", "RUNNING"),
        ("stored_descriptors", 1),
        ("stored_descriptors", False),
        ("numeric_invocation_id", "1" * 32),
        ("role", "ADMIN"),
    ],
)
def test_no_invented_numeric_start_success_coercion_or_authority(field, value):
    with pytest.raises(ValueError):
        RetiredNativeCpuPreparationFailure.model_validate(
            seal(preparation_root() | {field: value}, "proof_sha256")
        )


def test_hash_mismatch_and_cross_launch_proof_are_rejected():
    with pytest.raises(ValueError):
        RetiredNativeCpuPreparationFailure.model_validate(
            preparation_root() | {"proof_sha256": "sha256:" + "0" * 64}
        )


def test_gpu_recovery_never_accepts_cpu_preparation_evidence():
    sessions = Mock()
    with pytest.raises(AllocatedIndexingFailureRecoveryError, match="CONTEXT_INVALID"):
        recover_retired_indexing_workflow(
            sessions, parse_supported_failure_recovery(preparation_command())
        )
    sessions.begin.assert_not_called()
    with pytest.raises(ValueError):
        KnownFailedCpuPreparationEncoding.model_validate(
            seal(
                preparation_failure() | {"native_launch_job_id": "job_" + "f" * 32}, "event_sha256"
            )
        )


def test_public_service_reference_is_validated_value_not_runtime_authority():
    request = public_native_fixture()["request"]
    reference = supported_local_embedding_request_service(request)
    assert reference.service_id == request.actor_context.service_id
    assert reference.service_revision_id == request.actor_context.service_revision_id
    with pytest.raises(ValueError):
        supported_local_embedding_request_service(
            request.model_copy(update={"request_sha256": "sha256:" + "0" * 64})
        )
