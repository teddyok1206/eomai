"""Common numerical QUERY2 retains private purpose and exact original phase evidence."""

from pathlib import Path

import pytest
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator.models import JobRecord
from eom_orchestrator.native_private_chat_query_coordinator import NativePrivateChatQueryCoordinator
from eom_orchestrator.native_query_job_allocation import (
    NativeQueryLaunchError,
    create_native_query_launch,
    native_query_launch_key,
)
from eom_workflow.native_private_chat_query_coordinator import (
    NativePrivateChatQueryCheckpoint,
    NativePrivateChatQueryCheckpointV2,
    NativePrivateQueryPublishedV2,
    native_private_chat_public_query_checkpoint,
    parse_native_private_chat_query_checkpoint,
    parse_native_private_chat_query_checkpoint_v2,
    parse_supported_native_private_chat_query_checkpoint,
    private_chat_public_query_checkpoint_receipt,
    validate_native_private_chat_query_history,
)
from eom_workflow.schemas import NATIVE_PRIVATE_CHAT_QUERY_COORDINATOR_V2_SCHEMA_RESOURCE
from sqlalchemy import func, select

from tests.unit import test_native_private_query_coordinator as historical_cases
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.native_private_query_coordinator_fixtures import private_query_records
from tests.unit.test_control_file_set_publication import _publisher
from tests.unit.test_private_chat_public_query_workflow import public_completed as public_completed
from tests.unit.test_private_chat_query_basis import TEXT
from tests.unit.test_private_chat_query_workflow import completed as completed


@pytest.fixture
def records(public_completed):
    return private_query_records(public_completed)


@pytest.fixture
def stored(tmp_path, public_completed):
    publisher, _engine = _publisher(tmp_path)
    with publisher.sessions.begin() as session:
        create_native_query_launch(
            session, request=public_completed.request, launch=public_completed.launch
        )
    return publisher, NativePrivateChatQueryCoordinator(
        public_completed.request, public_completed.launch
    )


@pytest.mark.parametrize(
    "case",
    [
        historical_cases.test_exact_private_append_and_replay_share_one_original_job_history,
        historical_cases.test_original_origin_cannot_be_replaced_and_caller_rollback_preserves_state,
        historical_cases.test_missing_or_nested_root_cannot_append_and_failed_history_does_not_restart,
        historical_cases.test_foreign_purpose_event_is_not_silently_hidden_from_original_history,
    ],
)
def test_private2_uses_the_existing_interruption_and_replay_store(stored, records, case):
    case(stored, records)


def test_private2_history_keeps_the_same_indexed_bounded_lookup(stored):
    historical_cases.test_shared_checkpoint_read_is_original_job_index_lookup_with_five_row_bound(
        stored
    )


def test_old_private_original_cannot_be_reinterpreted_or_bypassed_as_private2(
    tmp_path, public_completed
):
    value, old = public_completed, public_completed.previous
    publisher, _engine = _publisher(tmp_path)
    assert native_query_launch_key(
        value.request, value.launch.workflow_id, value.launch.step_run_id
    ) == native_query_launch_key(old.request, old.launch.workflow_id, old.launch.step_run_id)
    with publisher.sessions.begin() as session:
        create_native_query_launch(session, request=old.request, launch=old.launch)
    with publisher.sessions.begin() as session:
        with pytest.raises(NativeQueryLaunchError):
            create_native_query_launch(session, request=value.request, launch=value.launch)
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 1
        original = session.get(JobRecord, old.launch.native_launch_job_id)
        assert (
            original.status == "CLAIMED" and original.protocol_version == "private-chat-query/1.0"
        )


def test_private2_schema_is_packaged_pinned_and_predecessor_bytes_unchanged():
    root = Path(__file__).parents[2]
    name, identity, digest = NATIVE_PRIVATE_CHAT_QUERY_COORDINATOR_V2_SCHEMA_RESOURCE
    raw = (root / "schemas/workflow" / name).read_bytes()
    assert raw == (root / "packages/workflow/eom_workflow/resources" / name).read_bytes()
    assert sha256_bytes(raw) == digest
    assert identity.endswith("/2.0")
    assert (
        sha256_bytes(
            (
                root / "schemas/workflow/native-private-chat-query-coordinator-v1.schema.json"
            ).read_bytes()
        )
        == "sha256:52b9d892e9010a923ed287163d60030113f2f03dc19fc79c1f26902e7187ae3f"
    )


def test_private2_each_contiguous_prefix_reconstructs_exact_private_receipt(
    public_completed, records
):
    value = public_completed
    for row in records:
        assert parse_native_private_chat_query_checkpoint_v2(row) == row
        assert parse_supported_native_private_chat_query_checkpoint(row) == row
        assert type(row) is NativePrivateChatQueryCheckpointV2
        raw = canonical_json_bytes(row)
        assert TEXT.encode() not in raw
        assert all(x not in raw for x in (b'"text"', b'"input.json"', b'"lease_token"'))
        with pytest.raises(ValueError):
            parse_native_private_chat_query_checkpoint(row)
    for length in range(5):
        validate_native_private_chat_query_history(records[:length], value.launch, value.request)
    receipt = private_chat_public_query_checkpoint_receipt(
        value.request, value.launch, records[0].payload, records[1].payload, records[2].payload
    )
    assert receipt == value.receipt
    assert receipt.execution_record.schema_ref.endswith("/2.0")
    assert receipt.execution_result_schema == "embedding-reference-query-result@2.0"


@pytest.mark.parametrize("phase", range(4))
def test_predecessor_and_successor_history_cannot_mix(public_completed, records, phase):
    old = private_query_records(public_completed.previous)
    mixed = (*records[:phase], old[phase], *records[phase + 1 :])
    with pytest.raises(ValueError):
        validate_native_private_chat_query_history(
            mixed, public_completed.launch, public_completed.request
        )
    with pytest.raises(ValueError):
        validate_native_private_chat_query_history(
            records, public_completed.previous.launch, public_completed.previous.request
        )
    with pytest.raises(ValueError):
        parse_native_private_chat_query_checkpoint_v2(old[phase])
    assert (
        type(parse_supported_native_private_chat_query_checkpoint(old[phase]))
        is NativePrivateChatQueryCheckpoint
    )


@pytest.mark.parametrize(
    "fault",
    [
        "hash",
        "extra",
        "phase",
        "float",
        "template",
        "invocation",
        "member",
        "mixed_file",
        "copy",
        "unrecognized",
    ],
)
def test_successor_still_rejects_untrusted_metadata_and_private_text(
    public_completed, records, fault
):
    index = (
        1
        if fault in {"float", "template", "invocation"}
        else 2
        if fault in {"member", "mixed_file"}
        else 0
    )
    body = records[index].model_dump(mode="json")
    if fault == "copy":
        with pytest.raises(ValueError):
            native_private_chat_public_query_checkpoint(
                public_completed.launch,
                "ALLOCATION",
                records[0].payload.model_copy(update={"text": TEXT}),
            )
        return
    if fault == "hash":
        body["checkpoint_sha256"] = "sha256:" + "f" * 64
    elif fault == "extra":
        body["text"] = TEXT
    elif fault == "phase":
        body["record_type"] = "EXECUTED"
    elif fault == "float":
        body["payload"]["query"]["started_monotonic"] = 3.0
    elif fault == "template":
        body["payload"]["prepare_template_sha256"] = "sha256:" + "f" * 64
    elif fault == "invocation":
        body["payload"]["query"]["invocation_id"] = body["payload"]["prepare"]["invocation_id"]
    elif fault == "member":
        body["payload"]["execution_record"]["member_path"] = "input.json"
    elif fault == "mixed_file":
        body["payload"]["result"]["artifact_revision_id"] = "rev_" + "f" * 32
    else:
        body["schema_version"] = "native-private-chat-query-coordinator/3.0"
    with pytest.raises(ValueError) as caught:
        parse_supported_native_private_chat_query_checkpoint(
            body if fault in {"hash", "float"} else seal(body, "checkpoint_sha256")
        )
    assert TEXT not in str(caught.value)


@pytest.mark.parametrize("member", ["execution_record", "result"])
def test_private2_published_members_cannot_reuse_predecessor_refs(records, member):
    body = records[2].payload.model_dump(mode="json")
    body[member]["schema_ref"] = body[member]["schema_ref"].replace("/2.0", "/1.0")
    with pytest.raises(ValueError):
        NativePrivateQueryPublishedV2.model_validate(body)


@pytest.mark.parametrize(
    "fault", ["skip", "duplicate", "foreign", "actor", "intent", "producer", "output"]
)
def test_private2_order_origin_and_exact_producers_remain_required(
    public_completed, records, fault
):
    value = public_completed
    if fault == "skip":
        changed = records[1:]
    elif fault == "duplicate":
        changed = (records[0], *records)
    else:
        index = 0 if fault in {"foreign", "actor"} else 3 if fault == "output" else 2
        body = records[index].model_dump(mode="json")
        if fault == "foreign":
            body["native_launch_job_id"] = "job_" + "f" * 32
        elif fault == "actor":
            origin = body["payload"]["origin"] | {"actor_id": "operator_" + "f" * 32}
            body["payload"]["origin"] = seal(origin, "origin_sha256")
        elif fault == "intent":
            body["payload"]["execution_record"]["sha256"] = "sha256:" + "f" * 64
        elif fault == "producer":
            body["payload"]["query_owner_job_id"] = "job_" + "f" * 32
        else:
            body["payload"]["output"]["receipt"]["sha256"] = "sha256:" + "f" * 64
            body["payload"]["output"] = seal(body["payload"]["output"], "output_sha256")
        row = parse_native_private_chat_query_checkpoint_v2(seal(body, "checkpoint_sha256"))
        changed = (*records[:index], row, *records[index + 1 :])
    with pytest.raises(ValueError):
        validate_native_private_chat_query_history(changed, value.launch, value.request)
