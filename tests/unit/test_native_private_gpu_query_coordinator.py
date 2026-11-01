"""Original private GPU checkpoint metadata/store only; no actual receipt/source/GPU proof."""

from pathlib import Path

import pytest
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator.native_private_chat_query_coordinator import NativePrivateChatQueryCoordinator
from eom_orchestrator.native_query_job_allocation import create_native_query_launch
from eom_workflow.native_private_chat_query_coordinator import (
    NativePrivateChatQueryCheckpointV21,
    NativePrivateQueryBatchExecuted,
    native_private_chat_gpu_query_checkpoint,
    native_private_chat_public_query_checkpoint,
    parse_native_private_chat_query_checkpoint_v2,
    parse_native_private_chat_query_checkpoint_v21,
    parse_supported_native_private_chat_query_checkpoint,
    private_chat_public_query_checkpoint_receipt,
    validate_native_private_chat_query_history,
)
from eom_workflow.native_reference_query_coordinator import NativeQueryBatchExecuted
from eom_workflow.schemas import NATIVE_PRIVATE_CHAT_QUERY_COORDINATOR_V21_SCHEMA_RESOURCE
from jsonschema import Draft202012Validator

from tests.unit import test_native_private_query_coordinator as historical_cases
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.native_private_query_coordinator_fixtures import (
    private_gpu_query_records,
    private_query_records,
)
from tests.unit.test_control_file_set_publication import _publisher
from tests.unit.test_private_chat_public_query_workflow import (
    public_completed as public_completed,
)
from tests.unit.test_private_chat_public_query_workflow import (
    public_query_completed,
)
from tests.unit.test_private_chat_query_basis import TEXT
from tests.unit.test_private_chat_query_workflow import completed as completed


@pytest.fixture
def gpu_completed(completed):
    return public_query_completed(completed, device="CUDA")


@pytest.fixture
def records(gpu_completed):
    return private_gpu_query_records(gpu_completed)


@pytest.fixture
def stored(tmp_path, gpu_completed):
    publisher, _engine = _publisher(tmp_path)
    with publisher.sessions.begin() as session:
        create_native_query_launch(
            session, request=gpu_completed.request, launch=gpu_completed.launch
        )
    return publisher, NativePrivateChatQueryCoordinator(gpu_completed.request, gpu_completed.launch)


def test_gpu_schema_is_pinned_mirrored_and_cpu_bytes_remain_unchanged():
    root = Path(__file__).parents[2]
    name, identity, digest = NATIVE_PRIVATE_CHAT_QUERY_COORDINATOR_V21_SCHEMA_RESOURCE
    raw = (root / "schemas/workflow" / name).read_bytes()
    assert raw == (root / "packages/workflow/eom_workflow/resources" / name).read_bytes()
    assert sha256_bytes(raw) == digest
    import json

    schema = json.loads(raw)
    Draft202012Validator.check_schema(schema)
    assert schema["$id"] == identity
    for version, expected in (
        ("v1", "52b9d892e9010a923ed287163d60030113f2f03dc19fc79c1f26902e7187ae3f"),
        ("v2", "3fdb7ec4a71e7cd38add1c579e847e5f69cf897ee6fcbde56609b55983da22c1"),
    ):
        assert (
            sha256_bytes(
                (
                    root
                    / "schemas/workflow"
                    / f"native-private-chat-query-coordinator-{version}.schema.json"
                ).read_bytes()
            )
            == "sha256:" + expected
        )


def test_gpu_history_closes_original_four_phases_without_cpu_unit_or_question(
    records, gpu_completed
):
    assert type(records[1].payload) is NativePrivateQueryBatchExecuted
    for record in records:
        assert type(record) is NativePrivateChatQueryCheckpointV21
        assert parse_supported_native_private_chat_query_checkpoint(record) == record
        raw = canonical_json_bytes(record)
        assert TEXT.encode() not in raw
        assert not any(
            field in raw
            for field in (
                b'"text"',
                b'"prepare_template_sha256"',
                b'"query_template_sha256"',
                b'"lease_token"',
            )
        )
        with pytest.raises(ValueError):
            parse_native_private_chat_query_checkpoint_v2(record)
    for length in range(5):
        validate_native_private_chat_query_history(
            records[:length], gpu_completed.launch, gpu_completed.request
        )
    assert (
        private_chat_public_query_checkpoint_receipt(
            gpu_completed.request, gpu_completed.launch, *(record.payload for record in records[:3])
        )
        == gpu_completed.receipt
    )


@pytest.mark.parametrize("phase", range(4))
def test_cpu_and_gpu_checkpoint_families_never_mix(records, gpu_completed, phase):
    cpu = private_query_records(gpu_completed)
    mixed = (*records[:phase], cpu[phase], *records[phase + 1 :])
    with pytest.raises(ValueError):
        validate_native_private_chat_query_history(
            mixed, gpu_completed.launch, gpu_completed.request
        )


def test_gpu_successor_does_not_change_existing_cpu_builders(records, gpu_completed):
    with pytest.raises(ValueError):
        native_private_chat_public_query_checkpoint(
            gpu_completed.launch, "EXECUTED", records[1].payload
        )
    cpu = private_query_records(gpu_completed)
    assert all(
        record.schema_version == "native-private-chat-query-coordinator/2.0" for record in cpu
    )
    with pytest.raises(ValueError):
        native_private_chat_gpu_query_checkpoint(gpu_completed.launch, "EXECUTED", cpu[1].payload)
    with pytest.raises(ValueError):
        NativeQueryBatchExecuted.model_validate(records[1].payload.model_dump(mode="json"))


def test_gpu_metadata_cannot_make_a_cpu_request_or_legacy_origin_cuda(public_completed, completed):
    records = private_gpu_query_records(public_completed)
    with pytest.raises(ValueError):
        validate_native_private_chat_query_history(
            records, public_completed.launch, public_completed.request
        )
    allocation = native_private_chat_gpu_query_checkpoint(
        completed.launch, "ALLOCATION", private_query_records(completed)[0].payload
    )
    with pytest.raises(ValueError):
        validate_native_private_chat_query_history(
            (allocation,), completed.launch, completed.request
        )


@pytest.mark.parametrize(
    "fault", ("ordinal", "bool", "public", "member", "media", "question", "unit", "float", "hash")
)
def test_gpu_observation_rejects_public_receipt_cpu_fields_and_untrusted_values(records, fault):
    body = records[1].model_dump(mode="json")
    payload = body["payload"]
    if fault in {"ordinal", "bool", "float"}:
        payload["child_ordinal"] = 1 if fault == "ordinal" else False if fault == "bool" else 0.0
    elif fault == "public":
        payload["batch_receipt"]["schema_ref"] = (
            "eom://schemas/workflow/embedding-batch-execution-receipt/1.0"
        )
    elif fault == "member":
        payload["batch_receipt"]["member_path"] = "result.json"
    elif fault == "media":
        payload["batch_receipt"]["media_type"] = "image/png"
    elif fault in {"question", "unit"}:
        payload["text" if fault == "question" else "cpu_environment_sha256"] = TEXT
    else:
        body["checkpoint_sha256"] = "sha256:" + "f" * 64
    with pytest.raises(ValueError) as error:
        parse_native_private_chat_query_checkpoint_v21(
            body if fault in {"hash", "float"} else seal(body, "checkpoint_sha256")
        )
    assert TEXT not in str(error.value)


@pytest.mark.parametrize("fault", ("result", "time", "producer", "intent", "origin", "output"))
def test_resealed_gpu_metadata_still_requires_original_closure(records, gpu_completed, fault):
    ordinal = (
        1
        if fault in {"result", "time"}
        else 0
        if fault == "origin"
        else 3
        if fault == "output"
        else 2
    )
    body = records[ordinal].model_dump(mode="json")
    if fault == "result":
        body["payload"]["result_sha256"] = "sha256:" + "f" * 64
    elif fault == "time":
        body["payload"]["completed_observed_at"] = "2000-01-01T00:00:00Z"
    elif fault == "producer":
        body["payload"]["query_owner_job_id"] = "job_" + "f" * 32
    elif fault == "intent":
        body["payload"]["execution_record"]["sha256"] = "sha256:" + "f" * 64
    elif fault == "origin":
        origin = body["payload"]["origin"] | {"actor_id": "operator_" + "f" * 32}
        body["payload"]["origin"] = seal(origin, "origin_sha256")
    else:
        output = body["payload"]["output"]
        output["receipt"]["sha256"] = "sha256:" + "f" * 64
        body["payload"]["output"] = seal(output, "output_sha256")
    changed = parse_native_private_chat_query_checkpoint_v21(seal(body, "checkpoint_sha256"))
    with pytest.raises(ValueError):
        validate_native_private_chat_query_history(
            (*records[:ordinal], changed, *records[ordinal + 1 :]),
            gpu_completed.launch,
            gpu_completed.request,
        )


@pytest.mark.parametrize(
    "case",
    (
        historical_cases.test_exact_private_append_and_replay_share_one_original_job_history,
        historical_cases.test_original_origin_cannot_be_replaced_and_caller_rollback_preserves_state,
        historical_cases.test_missing_or_nested_root_cannot_append_and_failed_history_does_not_restart,
        historical_cases.test_foreign_purpose_event_is_not_silently_hidden_from_original_history,
    ),
)
def test_gpu_uses_same_original_store_and_failure_history(stored, records, case):
    case(stored, records)


def test_gpu_keeps_original_indexed_bounded_checkpoint_read(stored):
    historical_cases.test_shared_checkpoint_read_is_original_job_index_lookup_with_five_row_bound(
        stored
    )
