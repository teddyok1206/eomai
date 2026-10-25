"""Closed catch-up intent values only; no source, CPU completion or physical GPU proof."""

from pathlib import Path

import pytest
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_workflow import document_embedding_reconciliation as protocol

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.local_embedding_workflow_receipt_fixtures import receipt_fixture
from tests.unit.test_embedding_batch_plan import planning_case


def reconciliation_case():
    plan = planning_case(purpose="INDEX")
    receipt = receipt_fixture()
    request = protocol.DocumentEmbeddingReconciliationRequest.model_validate(
        seal(
            dict(
                schema_version=protocol.DOCUMENT_RECONCILIATION_PROTOCOL,
                message_type="REQUEST",
                source_request_sha256=plan.request.parent_request_sha256,
                origin_parent_job_id="job_" + "1" * 32,
                origin_parent_request_sha256=plan.request.request_sha256,
                scope=plan.request.scope.model_dump(mode="json"),
                cpu_request_sha256=receipt.native.request.request_sha256,
                cpu_output=receipt.output.model_dump(mode="json"),
            ),
            "request_sha256",
        )
    )
    return plan, request


def test_original_cpu_receipt_and_next_gpu_identity_have_no_device_relabeling():
    plan, request = reconciliation_case()
    original = plan.request.model_dump(mode="json")
    intent = protocol.prepare_document_reconciliation_intent(
        request,
        plan.request,
        ordinal=1,
        previous_parent_job_id=request.origin_parent_job_id,
        previous_parent_request_sha256=plan.request.request_sha256,
    )
    successor = protocol.document_reconciliation_parent(plan.request, intent)
    assert plan.request.model_dump(mode="json") == original
    assert successor != plan.request
    assert successor.selection_manifest == plan.request.selection_manifest
    assert successor.scope == plan.request.scope
    assert successor.routing_policy == plan.request.routing_policy
    assert successor.parent_request_sha256 == plan.request.parent_request_sha256
    assert successor.request_sha256 == intent.parent_request_sha256
    assert protocol.document_reconciliation_parent(plan.request, intent) == successor


@pytest.mark.parametrize("field", ("request_sha256", "source_request_sha256", "scope", "extra"))
def test_request_hash_and_actual_scope_cannot_be_replaced(field):
    _plan, request = reconciliation_case()
    body = request.model_dump(mode="json")
    body[field] = {} if field == "scope" else "sha256:" + "f" * 64
    with pytest.raises(ValueError):
        protocol.DocumentEmbeddingReconciliationRequest.model_validate(body)


@pytest.mark.parametrize("ordinal", (0, True, 1_000_001))
def test_unbounded_or_boolean_attempt_number_is_rejected(ordinal):
    plan, request = reconciliation_case()
    with pytest.raises(ValueError):
        protocol.prepare_document_reconciliation_intent(
            request,
            plan.request,
            ordinal=ordinal,
            previous_parent_job_id=request.origin_parent_job_id,
            previous_parent_request_sha256=plan.request.request_sha256,
        )


def test_next_attempt_cannot_change_the_planned_parent_or_use_another_source_request():
    plan, request = reconciliation_case()
    intent = protocol.prepare_document_reconciliation_intent(
        request,
        plan.request,
        ordinal=1,
        previous_parent_job_id=request.origin_parent_job_id,
        previous_parent_request_sha256=plan.request.request_sha256,
    )
    body = intent.model_dump(mode="json")
    body["batch_id"] = "embeddingbatch_" + "f" * 32
    with pytest.raises(ValueError):
        protocol.DocumentEmbeddingReconciliationAttempt.model_validate(seal(body, "intent_sha256"))
    body = intent.model_dump(mode="json")
    body["parent_request_sha256"] = "sha256:" + "f" * 64
    wrong = protocol.DocumentEmbeddingReconciliationAttempt.model_validate(
        seal(body, "intent_sha256")
    )
    with pytest.raises(ValueError):
        protocol.document_reconciliation_parent(plan.request, wrong)
    body = request.model_dump(mode="json")
    body["source_request_sha256"] = "sha256:" + "f" * 64
    wrong_request = protocol.DocumentEmbeddingReconciliationRequest.model_validate(
        seal(body, "request_sha256")
    )
    with pytest.raises(ValueError):
        protocol.prepare_document_reconciliation_intent(
            wrong_request,
            plan.request,
            ordinal=1,
            previous_parent_job_id=request.origin_parent_job_id,
            previous_parent_request_sha256=plan.request.request_sha256,
        )


def test_schema_resource_mirror_and_hash_are_exact_and_dependency_direction_is_pure():
    root = Path(__file__).resolve().parents[2]
    source = root / "schemas/workflow/document-embedding-reconciliation-v1.schema.json"
    mirror = root / "packages/workflow/eom_workflow/resources" / source.name
    assert source.read_bytes() == mirror.read_bytes()
    schema = protocol.document_reconciliation_schema()
    assert schema["$id"] == protocol.DOCUMENT_RECONCILIATION_SCHEMA_REF
    assert len(protocol.DOCUMENT_RECONCILIATION_PROTOCOL) <= 32
    _plan, request = reconciliation_case()
    assert len(canonical_json_bytes(request)) < protocol.MAX_DOCUMENT_RECONCILIATION_BYTES
    assert request.request_sha256 == content_sha256(
        request.model_dump(mode="json", exclude={"request_sha256"})
    )
