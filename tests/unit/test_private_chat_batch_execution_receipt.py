"""Private metadata and local publication; source/GPU proof is explicitly synthetic."""

import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_catalog_service.settings import CatalogSettings
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.local_embedding_control_artifacts import (
    BATCH_EXECUTION_RECEIPT_ARTIFACT_TYPE,
    LocalEmbeddingControlArtifactPublisher,
    batch_execution_receipt_publication_key,
)
from eom_orchestrator.models import JobRecord
from eom_workflow.embedding_batch_execution_receipt import (
    PRIVATE_CHAT_BATCH_EXECUTION_RECEIPT_SCHEMA_REF,
    PRIVATE_CHAT_BATCH_EXECUTION_RECEIPT_SCHEMA_SHA256,
    EmbeddingBatchExecutionReceipt,
    PrivateChatBatchExecutionReceipt,
    embedding_batch_execution_receipt_schema_ref,
    parse_supported_embedding_batch_execution_receipt,
    private_chat_batch_execution_receipt_schema,
)
from jsonschema import Draft202012Validator
from sqlalchemy import func, select

from tests.unit.embedding_batch_execution_fixtures import execution_case
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.private_chat_batch_plan_fixtures import private_planning_case
from tests.unit.test_control_file_set_publication import _publisher
from tests.unit.test_embedding_batch_plan import planning_case
from tests.unit.test_private_chat_query_basis import TEXT


@pytest.fixture
def executed():
    return execution_case(planned=private_planning_case())


def test_private_receipt_schema_is_pinned_mirrored_and_has_no_authority_fields():
    root = Path(__file__).resolve().parents[2]
    name = "private-chat-batch-execution-receipt-v1.1.schema.json"
    raw = (root / "schemas/workflow" / name).read_bytes()
    assert raw == (root / "packages/workflow/eom_workflow/resources" / name).read_bytes()
    assert sha256_bytes(raw) == PRIVATE_CHAT_BATCH_EXECUTION_RECEIPT_SCHEMA_SHA256
    schema = private_chat_batch_execution_receipt_schema()
    Draft202012Validator.check_schema(schema)
    assert schema["$id"] == PRIVATE_CHAT_BATCH_EXECUTION_RECEIPT_SCHEMA_REF
    schema.clear()
    assert private_chat_batch_execution_receipt_schema()["properties"]["purpose"] == {
        "const": "PRIVATE_CHAT_QUERY"
    }
    assert EmbeddingBatchExecutionReceipt.model_json_schema()["properties"]["purpose"]["enum"] == [
        "INDEX",
        "REFERENCE_QUERY",
    ]


def test_private_original_scope_and_query2_do_not_become_public_or_cpu_proof(executed):
    value = executed
    receipt = value.receipt
    assert type(receipt) is PrivateChatBatchExecutionReceipt
    assert parse_supported_embedding_batch_execution_receipt(receipt) == receipt
    assert (
        embedding_batch_execution_receipt_schema_ref(receipt)
        == PRIVATE_CHAT_BATCH_EXECUTION_RECEIPT_SCHEMA_REF
    )
    assert len(receipt.children) == receipt.children[0].row_count == 1
    assert receipt.scope.actor_kind == "OPERATOR"
    assert receipt.children[0].result_sha256 == value.result.children[0].result.result_sha256
    assert receipt.children[0].binary_sha256 == receipt.completed.vectors_sha256
    raw = canonical_json_bytes(receipt.model_dump(mode="json"))
    assert TEXT.encode() not in raw and value.vectors not in raw
    assert b'"text":' not in raw and b'"vectors":' not in raw
    assert b"prepare_template_sha256" not in raw and b"cpu_environment_sha256" not in raw
    with pytest.raises(ValueError):
        EmbeddingBatchExecutionReceipt.model_validate_json(raw)
    with pytest.raises(ValueError):
        receipt.device = "CPU"


@pytest.mark.parametrize(
    "fault",
    (
        "family",
        "purpose",
        "device",
        "service",
        "partition",
        "multiple",
        "ordinal",
        "rows",
        "binary_hash",
        "question",
        "source_permission",
        "path",
        "vectors",
    ),
)
def test_resealed_metadata_cannot_claim_another_scope_or_public_execution(executed, fault):
    body = deepcopy(executed.receipt.model_dump(mode="json"))
    if fault == "family":
        body["schema_version"] = "embedding-batch-execution-receipt/1.0"
    elif fault == "purpose":
        body["purpose"] = "REFERENCE_QUERY"
    elif fault == "device":
        body["device"] = "CPU"
    elif fault == "service":
        body["scope"] = seal(
            body["scope"]
            | {
                "actor_kind": "LOCAL_INDEXING_SERVICE",
                "actor_id": "localindexservice_" + "f" * 32,
            },
            "scope_sha256",
        )
    elif fault == "partition":
        body["scope"] = seal(
            body["scope"] | {"storage_partition": "shared-system-rag"}, "scope_sha256"
        )
    elif fault == "multiple":
        body["children"].append(body["children"][0])
    elif fault == "ordinal":
        body["children"][0]["ordinal"] = 1
    elif fault == "rows":
        body["children"][0]["row_count"] = 2
    elif fault == "binary_hash":
        body["children"][0]["binary_sha256"] = "sha256:" + "f" * 64
    else:
        body[fault] = TEXT
    with pytest.raises(ValueError):
        parse_supported_embedding_batch_execution_receipt(seal(body, "receipt_sha256"))


def test_public_receipt_stays_a_distinct_family():
    public = execution_case(planned=planning_case(purpose="REFERENCE_QUERY")).receipt
    assert type(public) is EmbeddingBatchExecutionReceipt
    assert parse_supported_embedding_batch_execution_receipt(public) == public
    with pytest.raises(ValueError):
        PrivateChatBatchExecutionReceipt.model_validate(public.model_dump(mode="json"))


def test_schema_identity_does_not_guess_a_family_for_a_modified_header(executed):
    modified = executed.receipt.model_copy(
        update={"schema_version": "embedding-batch-execution-receipt/1.0"}
    )
    with pytest.raises(ValueError, match="EMBEDDING_BATCH_EXECUTION_RECEIPT_INVALID"):
        embedding_batch_execution_receipt_schema_ref(modified)


def test_private_receipt_uses_same_publisher_and_finds_its_actual_schema(tmp_path, executed):
    publisher, _ = _publisher(tmp_path)
    publisher.settings = replace(publisher.settings, workspace_root=tmp_path)
    controls = LocalEmbeddingControlArtifactPublisher(publisher, source_commit="a" * 40)
    request_sha = executed.frames.request.parent_request_sha256
    allocation_sha = "sha256:" + "8" * 64
    key = batch_execution_receipt_publication_key(request_sha, allocation_sha)
    assert (
        controls.find_batch_execution_receipt(
            parent_request_sha256=request_sha, allocation_record_sha256=allocation_sha
        )
        is None
    )
    saved = controls.publish_batch_execution_receipt(executed.receipt, idempotency_key=key)
    assert controls.publish_batch_execution_receipt(executed.receipt, idempotency_key=key) == saved
    assert saved.member.schema_ref == PRIVATE_CHAT_BATCH_EXECUTION_RECEIPT_SCHEMA_REF
    assert (
        controls.find_batch_execution_receipt(
            parent_request_sha256=request_sha, allocation_record_sha256=allocation_sha
        )
        == saved.member
    )
    with publisher.sessions.begin() as session:
        reader = PinnedArtifactReadContext(
            session, CatalogSettings(nas_artifact_root=publisher.settings.nas_artifact_root)
        )
        reader.prefetch(((saved.member.artifact_id, saved.member.artifact_revision_id),))
        raw = reader.read_pinned(
            **saved.member.model_dump(mode="python"),
            expected_artifact_types=(BATCH_EXECUTION_RECEIPT_ARTIFACT_TYPE,),
            expected_primary_file="receipt.json",
            max_bytes=512 * 1024,
        ).payload
        assert raw == canonical_json_bytes(executed.receipt.model_dump(mode="json"))
        assert (
            parse_supported_embedding_batch_execution_receipt(json.loads(raw)) == executed.receipt
        )
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 1
        job = session.scalar(select(JobRecord))
        assert job is not None and TEXT.encode() not in canonical_json_bytes(job.request)
    public = execution_case().receipt
    with pytest.raises(ControlPlaneError):
        controls.publish_batch_execution_receipt(public, idempotency_key=key)
