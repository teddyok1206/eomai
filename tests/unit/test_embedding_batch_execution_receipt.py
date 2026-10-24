"""Closed immutable execution metadata; synthetic proof values do not grant execution."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_workflow import embedding_batch_execution_receipt as receipt_module
from eom_workflow.embedding_batch_execution_receipt import EmbeddingBatchExecutionReceipt
from jsonschema import Draft202012Validator

from tests.unit.embedding_batch_execution_fixtures import execution_case
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_batch_plan import planning_case


def test_receipt_schema_is_pinned_mirrored_202012_and_independent():
    root = Path(__file__).resolve().parents[2]
    name = "embedding-batch-execution-receipt-v1.schema.json"
    raw = (root / "schemas/workflow" / name).read_bytes()
    assert raw == (root / "packages/workflow/eom_workflow/resources" / name).read_bytes()
    assert sha256_bytes(raw) == receipt_module.BATCH_EXECUTION_RECEIPT_SCHEMA_SHA256
    schema = receipt_module.embedding_batch_execution_receipt_schema()
    Draft202012Validator.check_schema(schema)
    schema.clear()
    assert (
        receipt_module.embedding_batch_execution_receipt_schema()["$id"]
        == receipt_module.BATCH_EXECUTION_RECEIPT_SCHEMA_REF
    )


@pytest.mark.parametrize("purpose", ("INDEX", "REFERENCE_QUERY"))
def test_exact_original_receipt_is_small_metadata_not_vectors_or_child_publication(purpose):
    value = execution_case(planned=planning_case(purpose=purpose))
    receipt = value.receipt
    raw = canonical_json_bytes(receipt.model_dump(mode="json"))
    assert EmbeddingBatchExecutionReceipt.model_validate_json(raw) == receipt
    assert len(raw) < receipt_module.MAX_BATCH_EXECUTION_RECEIPT_BYTES
    assert value.vectors not in raw and b'"text":' not in raw and b'"vectors":' not in raw
    assert [child.native_job_id for child in receipt.children] == [
        child.request.job_id for child in value.batch.children
    ]
    with pytest.raises(ValueError):
        receipt.device = "CPU"


@pytest.mark.parametrize(
    "field", ("role", "path", "vectors", "source_permission", "extra", "child_publications")
)
def test_unknown_payload_or_authority_fields_are_rejected(field):
    body = execution_case().receipt.model_dump(mode="json")
    with pytest.raises(ValueError):
        EmbeddingBatchExecutionReceipt.model_validate(seal(body | {field: []}, "receipt_sha256"))


@pytest.mark.parametrize(
    "fault",
    (
        "receipt_hash",
        "cpu",
        "purpose",
        "child_job",
        "child_input",
        "child_order",
        "child_extra",
        "offset",
        "length",
        "dimension",
        "boolean",
        "duplicate",
        "total",
        "ready",
        "bound",
        "unit",
        "grant",
        "child_selection",
    ),
)
def test_resealed_receipt_cannot_close_another_execution_or_hide_wrong_ranges(fault):
    body = deepcopy(execution_case().receipt.model_dump(mode="json"))
    child = body["children"][0]
    if fault == "receipt_hash":
        body["receipt_sha256"] = "sha256:" + "f" * 64
    elif fault == "cpu":
        body["device"] = "CPU"
    elif fault == "purpose":
        body["purpose"] = "INDEX"
    elif fault == "child_job":
        child["native_job_id"] = "job_" + "f" * 32
    elif fault == "child_input":
        child["input_sha256"] = "sha256:" + "f" * 64
    elif fault == "child_order":
        body["children"].reverse()
    elif fault == "child_extra":
        child["extra"] = True
    elif fault == "offset":
        child["vector_offset"] = 4
    elif fault == "length":
        child["vector_byte_count"] += 4
    elif fault == "dimension":
        child["dimension"] += 1
        child["vector_byte_count"] = 4 * child["dimension"] * child["row_count"]
    elif fault == "boolean":
        child["ordinal"] = False
    elif fault == "duplicate":
        body["children"][1] = child
    elif fault == "total":
        body["completed"] = seal(body["completed"] | {"vectors_byte_count": 4}, "message_sha256")
    elif fault == "child_selection":
        binding = body["bound"]["binding"]
        binding["children"][0]["selection_sha256"] = "sha256:" + "f" * 64
        body["bound"] = seal(
            body["bound"] | {"binding": seal(binding, "record_sha256")}, "message_sha256"
        )
        body["completed"] = seal(
            body["completed"] | {"bound_message_sha256": body["bound"]["message_sha256"]},
            "message_sha256",
        )
    else:
        if fault == "ready":
            key, changed = "ready", {"unit_invocation_id": "f" * 32}
        elif fault == "bound":
            key, changed = "bound", {"input_raw_sha256": "sha256:" + "f" * 64}
        elif fault == "unit":
            key, changed = "completed", {"unit_invocation_id": "f" * 32}
        else:
            key = "completed"
            changed = {
                "grant": seal(
                    body[key]["grant"] | {"ready_message_sha256": "sha256:" + "f" * 64},
                    "message_sha256",
                )
            }
        body[key] = seal(body[key] | changed, "message_sha256")
    if fault != "receipt_hash":
        body = seal(body, "receipt_sha256")
    with pytest.raises(ValueError):
        EmbeddingBatchExecutionReceipt.model_validate(body)


def test_copied_model_and_nested_extra_fields_are_not_sanitized():
    original = execution_case().receipt
    for corrupt in (
        original.model_copy(update={"extra": True}),
        original.model_copy(
            update={"children": (original.children[0].model_copy(update={"extra": 1}),)}
        ),
        original.model_copy(update={"scope": original.scope.model_copy(update={"extra": True})}),
    ):
        with pytest.raises(ValueError):
            EmbeddingBatchExecutionReceipt.model_validate(corrupt)
