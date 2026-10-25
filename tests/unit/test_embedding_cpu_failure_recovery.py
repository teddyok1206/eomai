"""CPU recovery value/schema negatives; no actual PID1, DB, model or maintenance."""

from pathlib import Path

import pytest
from eom_identifiers import sha256_bytes
from eom_workflow.embedding_cpu_failure_recovery import (
    CPU_FAILURE_RECOVERY_SCHEMA_SHA256,
    CpuEmbeddingFailureRecoveryCommand,
    KnownFailedCpuEmbeddingEncoding,
    RetiredNativeCpuIndexFailure,
)

from tests.unit.embedding_encoding_reservation_fixtures import reservation_fixture
from tests.unit.inference_transfer_embedding_fixtures import seal


def cpu_root(*, native_job_id="job_" + "a" * 32):
    return seal(
        dict(
            kind="NATIVE_CPU_INDEX_FAILED",
            native_launch_job_id=native_job_id,
            boot_id="12345678-1234-1234-1234-123456789abc",
            prepare_invocation_id="1" * 32,
            numeric_invocation_id="2" * 32,
            prepare_template_sha256="sha256:" + "1" * 64,
            numeric_template_sha256="sha256:" + "2" * 64,
            numeric_started_monotonic_us=1000,
            numeric_exited_monotonic_us=2000,
            numeric_result="timeout",
            numeric_exec_main_code=2,
            numeric_exec_main_status=15,
            original_outcome="FAILED",
            stored_descriptors=0,
        ),
        "proof_sha256",
    )


def cpu_command():
    return seal(
        dict(
            schema_version="embedding-encoding-recovery/3.0",
            record_type="RECOVER",
            workflow_id="workflow_" + "a" * 32,
            workflow_request_sha256="sha256:" + "a" * 64,
            command_id="wfcmd_" + "b" * 32,
            lease_generation=1,
            native_intent_sha256="sha256:" + "b" * 64,
            current_service=dict(
                service_id="localindexservice_" + "a" * 32,
                service_revision_id="localindexservicerev_" + "b" * 32,
                service_identity_sha256="sha256:" + "c" * 64,
            ),
            root=cpu_root(),
        ),
        "command_sha256",
    )


def cpu_failure():
    fixture = reservation_fixture("a")
    native_id = fixture.association.intent.native_launch_job_id
    return seal(
        dict(
            schema_version="embedding-encoding-recovery/3.0",
            record_type="FAILURE",
            owned_job=fixture.association.owned_jobs[0].model_dump(mode="json"),
            native_launch_job_id=native_id,
            root=cpu_root(native_job_id=native_id),
        ),
        "event_sha256",
    )


def test_schema_mirror_hash_and_valid_command_failure_families():
    root = Path(__file__).resolve().parents[2]
    name = "embedding-encoding-recovery-v3.schema.json"
    raw = (root / "schemas/workflow" / name).read_bytes()
    assert raw == (root / "packages/workflow/eom_workflow/resources" / name).read_bytes()
    assert sha256_bytes(raw) == CPU_FAILURE_RECOVERY_SCHEMA_SHA256
    assert (
        CpuEmbeddingFailureRecoveryCommand.model_validate(cpu_command()).root.numeric_result
        == "timeout"
    )
    assert KnownFailedCpuEmbeddingEncoding.model_validate(cpu_failure()).record_type == "FAILURE"


@pytest.mark.parametrize(
    "fault",
    ("success", "bool", "float", "reverse", "same_invocation", "extra", "hash", "path"),
)
def test_root_values_never_coerce_or_accept_invented_success_or_locations(fault):
    value = cpu_root()
    if fault == "success":
        value["numeric_result"] = "success"
    elif fault == "bool":
        value["stored_descriptors"] = False
    elif fault == "float":
        value["numeric_started_monotonic_us"] = 1000.0
    elif fault == "reverse":
        value["numeric_exited_monotonic_us"] = 1
    elif fault == "same_invocation":
        value["numeric_invocation_id"] = value["prepare_invocation_id"]
    elif fault == "path":
        value["unit_path"] = "/tmp/arbitrary.service"
    elif fault == "extra":
        value["role"] = "ADMIN"
    if fault == "float":
        # Canonical JSON deliberately rejects floats before a hash can be sealed.
        with pytest.raises(ValueError):
            RetiredNativeCpuIndexFailure.model_validate(value)
        return
    value = seal(value, "proof_sha256")
    if fault == "hash":
        value["proof_sha256"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError):
        RetiredNativeCpuIndexFailure.model_validate(value)


@pytest.mark.parametrize("fault", ("bool", "unknown", "extra", "role", "hash"))
def test_current_service_and_later_command_are_not_caller_authority(fault):
    value = cpu_command()
    if fault == "bool":
        value["lease_generation"] = True
    elif fault == "unknown":
        value["schema_version"] = "embedding-encoding-recovery/99.0"
    elif fault == "extra":
        value["current_service"]["permission"] = "ADMIN"
    elif fault == "role":
        value["actor_type"] = "database_owner"
    value = seal(value, "command_sha256")
    if fault == "hash":
        value["command_sha256"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError):
        CpuEmbeddingFailureRecoveryCommand.model_validate(value)


@pytest.mark.parametrize("fault", ("native_job", "hash", "unknown"))
def test_failure_keeps_original_encoding_and_native_proof_identity(fault):
    value = cpu_failure()
    if fault == "native_job":
        value["native_launch_job_id"] = "job_" + "f" * 32
    elif fault == "unknown":
        value["schema_version"] = "embedding-encoding-recovery/99.0"
    value = seal(value, "event_sha256")
    if fault == "hash":
        value["event_sha256"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError):
        KnownFailedCpuEmbeddingEncoding.model_validate(value)
