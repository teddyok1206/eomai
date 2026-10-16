"""Pure refresh receipt closure; no IAM, DB, files, model or live acceptance."""

from __future__ import annotations

import pytest
from eom_identifiers import content_sha256
from eom_workflow.local_embedding_index_refresh import parse_index_refresh_request
from eom_workflow.local_embedding_workflow_receipt import (
    ResolvedNativeIndexCoverage,
    parse_local_embedding_workflow_receipt,
    validate_local_embedding_workflow_receipt,
)

from tests.unit.inference_transfer_embedding_fixtures import (
    index_manifest,
    seal,
    shard_pointer,
    source_binding,
    vector_shard,
)
from tests.unit.local_embedding_service_fixtures import service_fixture
from tests.unit.local_embedding_workflow_receipt_fixtures import receipt_fixture


@pytest.fixture
def refresh():
    original = receipt_fixture(borrowed_only=True)
    native = original.native
    service = service_fixture(base=native)
    shard = vector_shard(
        tuple(row.encoding for row in native.native_input.rows), space=native.plan.space
    )
    bindings = tuple(
        source_binding(
            entry,
            view=native.plan.namespace.view,
            recipe=native.plan.recipe,
            space=native.plan.space,
            shard=shard,
            pointer=shard_pointer(shard),
        )
        for entry in native.entries
    )
    index = index_manifest(*bindings, space=native.plan.space, view=native.plan.namespace.view)
    request_body = service.request.model_dump(mode="json") | {
        "schema_version": "local-embedding-workflow-request/1.3",
        "reconciliation_basis": {
            "reason": "MISSING_NAMESPACE_INDEX",
            "previous_index_manifest": None,
            "previous_index_sha256": None,
            "eligible_source_set_sha256": native.plan.source_set_sha256,
            "eligible_source_count": len(native.plan.sources),
            "available_binding_set_sha256": content_sha256(
                [binding.binding_sha256 for binding in bindings]
            ),
            "available_binding_count": len(bindings),
        },
    }
    request = parse_index_refresh_request(seal(request_body, "request_sha256"))
    receipt_body = original.receipt.model_dump(mode="json") | {
        "workflow_request_sha256": request.request_sha256
    }
    receipt = parse_local_embedding_workflow_receipt(seal(receipt_body, "receipt_sha256"))
    return (
        original,
        service,
        request,
        receipt,
        ResolvedNativeIndexCoverage(index, native.plan.sources),
    )


def validate(refresh, *, coverage=True, numerical=False):
    original, service, request, receipt, resolved = refresh
    return validate_local_embedding_workflow_receipt(
        receipt,
        request,
        original.native.plan,
        service.policy,
        workflow_id=receipt.workflow_id,
        step_run_id=receipt.step_run_id,
        receipt_owner_job_id=receipt.receipt_owner_job_id,
        launch_association=original.native.association if numerical else None,
        owned_input=original.native.native_input if numerical else None,
        index_coverage=resolved if coverage else None,
    )


def test_metadata_refresh_requires_full_owner_resolved_coverage_even_for_whole_plan(refresh):
    assert validate(refresh) == refresh[3]
    with pytest.raises(ValueError, match="refresh"):
        validate(refresh, coverage=False)


def test_metadata_refresh_never_accepts_numerical_launch_association(refresh):
    with pytest.raises(ValueError, match="refresh"):
        validate(refresh, numerical=True)


@pytest.mark.parametrize(
    "field,value",
    [
        ("eligible_source_set_sha256", "sha256:" + "f" * 64),
        ("eligible_source_count", 3),
        ("available_binding_set_sha256", "sha256:" + "f" * 64),
        ("available_binding_count", 1),
    ],
)
def test_resealed_refresh_basis_cannot_claim_different_population_or_membership(
    refresh, field, value
):
    original, service, request, receipt, coverage = refresh
    request_body = request.model_dump(mode="json")
    request_body["reconciliation_basis"][field] = value
    changed_request = parse_index_refresh_request(seal(request_body, "request_sha256"))
    receipt_body = receipt.model_dump(mode="json") | {
        "workflow_request_sha256": changed_request.request_sha256
    }
    changed_receipt = parse_local_embedding_workflow_receipt(seal(receipt_body, "receipt_sha256"))
    with pytest.raises(ValueError):
        validate((original, service, changed_request, changed_receipt, coverage))
