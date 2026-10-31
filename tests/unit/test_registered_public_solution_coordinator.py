"""Exact fixed-stage continuation metadata; no claims, model or live persistence."""

from functools import lru_cache
from pathlib import Path

import pytest
from eom_identifiers import sha256_bytes
from eom_workflow.native_embedding_coordinator import (
    NativeArtifactProducerIdentity,
    NativeCoordinatorAllocation,
)
from eom_workflow.native_embedding_coordinator_v3 import (
    parse_native_embedding_coordinator_checkpoint_v3,
)
from eom_workflow.native_embedding_coordinator_v4 import (
    NativeCoordinatorCompletedV4,
    NativeCoordinatorIndexPreparedV4,
    NativeCoordinatorRegisteredV4,
    native_coordinator_checkpoint_v4,
    parse_native_embedding_coordinator_checkpoint_v4,
    validate_native_coordinator_history_v4,
)
from eom_workflow.schemas import load_local_embedding_admission_schema
from jsonschema import Draft202012Validator

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.inference_transfer_fixtures import NOW
from tests.unit.test_registered_public_solution_completion import completion_case


@lru_cache(maxsize=1)
def history():
    value = completion_case()
    command, output = value.command, value.output
    allocation = NativeCoordinatorAllocation(
        index_producer=NativeArtifactProducerIdentity(
            job_id="job_" + "c" * 32,
            artifact_id=command.index_manifest.artifact_id,
            artifact_revision_id=command.index_manifest.artifact_revision_id,
        ),
        receipt_producer=NativeArtifactProducerIdentity(
            job_id=output.receipt_owner_job_id,
            artifact_id=output.receipt.artifact_id,
            artifact_revision_id=output.receipt.artifact_revision_id,
        ),
        created_at=NOW,
        source_commit="a" * 40,
    )
    payloads = (
        ("ALLOCATION", allocation),
        (
            "INDEX_PREPARED",
            NativeCoordinatorIndexPreparedV4(registration_command=command, index_created_at=NOW),
        ),
        (
            "REGISTERED",
            NativeCoordinatorRegisteredV4(
                registration_result=value.result,
                registration_observed_at=value.receipt.registration_observed_at,
            ),
        ),
        ("COMPLETED", NativeCoordinatorCompletedV4(output=output)),
    )
    return tuple(
        native_coordinator_checkpoint_v4(value.case.intent, phase, payload)
        for phase, payload in payloads
    )


def test_fixed_continuation_accepts_every_prefix_and_exact_original_producers():
    records = history()
    intent = completion_case().case.intent
    for length in range(5):
        validate_native_coordinator_history_v4(records[:length], intent)
    for record in records:
        assert (
            parse_native_embedding_coordinator_checkpoint_v4(record.model_dump(mode="json"))
            == record
        )
    with pytest.raises(ValueError):
        parse_native_embedding_coordinator_checkpoint_v3(records[0].model_dump(mode="json"))


@pytest.mark.parametrize(
    "fault",
    [
        "skip",
        "duplicate",
        "reversed",
        "foreign_intent",
        "wrong_producer",
        "wrong_result",
        "wrong_phase",
        "float",
        "extra",
    ],
)
def test_history4_rejects_mixed_or_forged_records_even_when_rehashed(fault):
    records = list(history())
    intent = completion_case().case.intent
    if fault == "skip":
        records.pop(1)
    elif fault == "duplicate":
        records[1] = records[0]
    elif fault == "reversed":
        records.reverse()
    else:
        index = 3 if fault == "wrong_producer" else 2
        body = records[index].model_dump(mode="json")
        if fault == "foreign_intent":
            body["intent_sha256"] = "sha256:" + "0" * 64
        elif fault == "wrong_producer":
            output = body["payload"]["output"]
            output["receipt"]["artifact_revision_id"] = "rev_" + "f" * 32
            body["payload"]["output"] = seal(output, "output_sha256")
        elif fault == "wrong_result":
            result = body["payload"]["registration_result"]
            result["operation_key"] = "different-registration"
            body["payload"]["registration_result"] = seal(result, "result_sha256")
        elif fault == "wrong_phase":
            body["record_type"] = "INDEX_PREPARED"
        elif fault == "float":
            body["payload"]["registration_result"]["current_lock_version"] = 2.0
        else:
            body["authorization"] = "ADMIN"
        with pytest.raises(ValueError):
            records[index] = parse_native_embedding_coordinator_checkpoint_v4(
                body if fault == "float" else seal(body, "checkpoint_sha256")
            )
            validate_native_coordinator_history_v4(tuple(records), intent)
        return
    with pytest.raises(ValueError):
        validate_native_coordinator_history_v4(tuple(records), intent)


def test_coordinator_schema_packaged_2020_12_and_previous_schema_unchanged():
    root = Path(__file__).resolve().parents[2]
    name = "native-embedding-coordinator-v4.schema.json"
    assert (root / "schemas/workflow" / name).read_bytes() == (
        root / "packages/workflow/eom_workflow/resources" / name
    ).read_bytes()
    Draft202012Validator.check_schema(
        load_local_embedding_admission_schema("registered-public-coordinator")
    )
    assert sha256_bytes(
        (root / "schemas/workflow/native-embedding-coordinator-v3.schema.json").read_bytes()
    ) == ("sha256:5da92e6ddbaf39f8f4c9aee371be929f58f68a6919015da7a01e48d2d225d2a0")
