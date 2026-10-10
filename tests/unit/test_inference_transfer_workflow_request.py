from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from eom_catalog_contracts.validation import catalog_schema_registry
from eom_identifiers import content_sha256
from eom_workflow.inference_transfer_workflow import InferenceTransferWorkflowRequest
from eom_workflow.models import WorkflowRequest
from eom_workflow.schemas import (
    WorkflowSchemaError,
    load_inference_transfer_workflow_request_schema,
    validate_inference_transfer_workflow_request,
)
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from tests.unit.inference_transfer_fixtures import sha
from tests.unit.inference_transfer_workflow_fixtures import workflow_request


def _rehash(body: dict[str, Any]) -> dict[str, Any]:
    return body | {"request_sha256": content_sha256(body)}


def test_schema_first_resource_and_typed_model_agree() -> None:
    canonical = Path("schemas/workflow/inference-transfer-workflow-request-v1.schema.json")
    mirror = Path(
        "packages/workflow/eom_workflow/resources/"
        "inference-transfer-workflow-request-v1.schema.json"
    )
    assert canonical.read_bytes() == mirror.read_bytes()
    schema = load_inference_transfer_workflow_request_schema()
    assert schema == json.loads(canonical.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    value = workflow_request().model_dump(mode="json")
    Draft202012Validator(schema, registry=catalog_schema_registry()).validate(value)
    assert validate_inference_transfer_workflow_request(value) == workflow_request()


def test_loaded_schema_is_not_a_mutable_shared_registry() -> None:
    first = load_inference_transfer_workflow_request_schema()
    first["properties"]["request_name"]["const"] = "CUSTOMER_SUPPORT_REQUEST"
    assert load_inference_transfer_workflow_request_schema()["properties"]["request_name"] == {
        "const": "ITEM_INFERENCE_TRANSFER_PAIR_REQUEST"
    }
    assert validate_inference_transfer_workflow_request(workflow_request().model_dump(mode="json"))


def test_application_snapshot_and_worker_input_have_separate_boundaries() -> None:
    value = workflow_request()
    worker = value.worker_request().model_dump(mode="json")
    assert set(worker) == {"request_name", "comparison", "left_profile", "right_profile"}
    assert "requester_permissions_sha256" not in worker
    assert "access_policy_revision_id" not in worker
    assert "actor_id" not in value.model_dump(mode="json")
    assert value.request_sha256 != value.comparison.request_sha256
    assert value.left_profile.extraction.prompt_sha256 is None


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("actor_id", "operator_" + "1" * 32),
        ("requester_role", "ADMIN"),
        ("permissions", ["ADMIN"]),
        ("content_pack", {"pack_key": "generated-knowledge-item"}),
        ("execution_preset_key", "customer-support"),
        ("schema_version", "inference-transfer-workflow-request/2.0"),
        ("request_name", "CUSTOMER_SUPPORT_REQUEST"),
    ),
)
def test_no_worker_or_client_supplied_authority_or_foreign_purpose(
    field: str, value: object
) -> None:
    document = workflow_request().model_dump(mode="json", exclude={"request_sha256"})
    document[field] = value
    with pytest.raises(WorkflowSchemaError):
        validate_inference_transfer_workflow_request(_rehash(document))


@pytest.mark.parametrize("field", ("access_policy_sha256", "requester_permissions_sha256"))
def test_changed_initial_audit_pin_cannot_preserve_old_request_hash(field: str) -> None:
    document = workflow_request().model_dump(mode="json")
    document[field] = sha("f")
    with pytest.raises(WorkflowSchemaError, match="typed validation"):
        validate_inference_transfer_workflow_request(document)


def test_explicit_nested_nulls_are_required_not_repaired() -> None:
    document = workflow_request().model_dump(mode="json", exclude={"request_sha256"})
    del document["left_profile"]["extraction"]["prompt_sha256"]
    with pytest.raises(WorkflowSchemaError):
        validate_inference_transfer_workflow_request(_rehash(document))


def test_copied_nested_literal_with_consistent_hash_is_rejected() -> None:
    value = workflow_request()
    left = value.left_profile.model_copy(update={"schema_version": "invented/1.0"})
    body = left.model_dump(mode="json", exclude={"profile_sha256"})
    left = left.model_copy(update={"profile_sha256": content_sha256(body)})
    copied = value.model_copy(update={"left_profile": left})
    copied = copied.model_copy(
        update={
            "request_sha256": content_sha256(
                copied.model_dump(mode="json", exclude={"request_sha256"})
            )
        }
    )
    with pytest.raises(WorkflowSchemaError):
        validate_inference_transfer_workflow_request(copied.model_dump(mode="json"))


def test_dangling_claim_and_swapped_profile_are_rejected() -> None:
    for foreign in ("selected_claim", "profile"):
        document = workflow_request().model_dump(mode="json", exclude={"request_sha256"})
        if foreign == "selected_claim":
            document["comparison"]["left_claim_ids"] = ["transferclaim_missing"]
            comparison = dict(document["comparison"])
            comparison.pop("request_sha256")
            document["comparison"] = _rehash(comparison)
        else:
            document["left_profile"], document["right_profile"] = (
                document["right_profile"],
                document["left_profile"],
            )
        with pytest.raises(WorkflowSchemaError):
            validate_inference_transfer_workflow_request(_rehash(document))


def test_bounded_values_reject_large_context_without_truncation() -> None:
    document = workflow_request().model_dump(mode="json", exclude={"request_sha256"})
    left = deepcopy(document["left_profile"])
    left["claims"] = [
        dict(left["claims"][0], claim_id=f"transferclaim_large_{index}", text="가" * 4000)
        for index in range(20)
    ]
    left.pop("profile_sha256")
    left["profile_sha256"] = content_sha256(left)
    document["left_profile"] = left
    comparison = dict(document["comparison"])
    comparison["left_profile"]["profile_sha256"] = left["profile_sha256"]
    comparison["left_claim_ids"] = []
    comparison.pop("request_sha256")
    document["comparison"] = _rehash(comparison)
    with pytest.raises(WorkflowSchemaError, match="typed validation"):
        validate_inference_transfer_workflow_request(_rehash(document))


def test_legacy_workflow_model_remains_closed_to_comparison_wrapper() -> None:
    with pytest.raises(ValidationError):
        WorkflowRequest.model_validate(workflow_request().model_dump(mode="json"))
    legacy = WorkflowRequest(request_name="PLACEHOLDER_REQUEST", image_mode="skip")
    with pytest.raises(ValidationError):
        InferenceTransferWorkflowRequest.model_validate(legacy.model_dump(mode="json"))
