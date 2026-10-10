"""Three-axis Catalog preparation/owner wiring; synthetic ports, not live quality."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from types import SimpleNamespace
from typing import cast

import pytest
from eom_catalog_contracts.inference_transfer_invocation import InferenceTransferWorkflowReadRequest
from eom_catalog_service.inference_transfer_comparison import (
    admit_pair_comparison_result_v11,
    prepare_pair_comparison,
    prepare_pair_comparison_v11,
)
from eom_catalog_service.inference_transfer_service import InferenceTransferServiceError
from eom_catalog_service.inference_transfer_worker_preparation import (
    prepare_inference_transfer_worker_comparison,
    prepare_inference_transfer_worker_comparison_v11,
)
from eom_identifiers import canonical_json_bytes, content_sha256
from jsonschema import ValidationError as SchemaError

from tests.unit.inference_transfer_fixtures import profile, request, result
from tests.unit.inference_transfer_pair_v11_fixtures import pair_result_v11
from tests.unit.inference_transfer_service_v11_fixtures import owner_fixture_v11, read_request_v11
from tests.unit.inference_transfer_workflow_fixtures import OPERATOR_ID, OTHER_OPERATOR_ID
from tests.unit.inference_transfer_workflow_read_fixtures import owner_fixture, read_request


def test_prompt_successor_requires_three_grounded_distinct_axes_without_changing_legacy() -> None:
    left, right = profile("a"), profile("b")
    query = request(left, right)
    old = prepare_pair_comparison(query, left=left, right=right)
    new = prepare_pair_comparison_v11(query, left=left, right=right)
    assert old.prompt_version.endswith("/1.0") and new.prompt_version.endswith("/1.1")
    assert "item-inference-transfer-pair-result/1.0" in old.prompt_text
    assert "axes는 CONCEPT, MATERIAL, CRUX" not in old.prompt_text
    assert "item-inference-transfer-pair-result/1.1" in new.prompt_text
    for phrase in (
        "axes는 CONCEPT, MATERIAL, CRUX",
        "과학적 개념·관계",
        "주어진 자료의 구성·조건 역할",
        "A를 풀 때 얻은 결정적 착상",
        "양쪽 DECISIVE_INFERENCE",
        "숫자나 이름만 바뀐",
        "사람 평가나 출판 승인이 아니다",
    ):
        assert phrase in new.prompt_text
    assert old.context_bytes == new.context_bytes
    assert old.prompt_sha256 != new.prompt_sha256
    old_worker = prepare_inference_transfer_worker_comparison(query, left=left, right=right)
    new_worker = prepare_inference_transfer_worker_comparison_v11(query, left=left, right=right)
    assert new_worker.request.request_name == "ITEM_INFERENCE_TRANSFER_PAIR_REQUEST_V11"
    assert "workflow-role/1.30.0" in new_worker.prompt_text
    assert "workflow-role/1.29.0" not in new_worker.prompt_text
    assert "workflow-role/1.29.0" in old_worker.prompt_text
    assert new_worker.core_prompt_sha256 == new.prompt_sha256
    assert new_worker.prompt_sha256 != old_worker.prompt_sha256


def test_new_result_admission_does_not_promote_legacy_or_unknown_claim_axes() -> None:
    left, right = profile("a"), profile("b")
    query = request(left, right)
    expected = pair_result_v11(query)
    assert (
        admit_pair_comparison_result_v11(
            expected.model_dump(mode="json"), request=query, left=left, right=right
        )
        == expected
    )
    with pytest.raises((ValueError, SchemaError)):
        admit_pair_comparison_result_v11(
            result(query).model_dump(mode="json"), request=query, left=left, right=right
        )
    forged = expected.model_dump(mode="json")
    forged["axes"][0]["left_claim_ids"] = ["transferclaim_unknown"]
    forged["result_sha256"] = content_sha256(
        {key: item for key, item in forged.items() if key != "result_sha256"}
    )
    with pytest.raises(ValueError):
        admit_pair_comparison_result_v11(forged, request=query, left=left, right=right)


def test_new_owner_materializes_outer_envelope_with_axes_and_current_source_reauthorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = owner_fixture_v11(monkeypatch)
    response = value.owner.read_v11(OPERATOR_ID, read_request_v11())
    assert response.result_state == "MEMBER_VERIFIED"
    assert response.result == value.role_result.output
    assert len(response.result.axes) == 3
    assert response.result_artifact.member_path == "result.json"
    assert response.result_artifact.schema_ref.endswith("pair-result-v2.schema.json")
    assert response.result_artifact.sha256 != response.result.result_sha256
    assert value.owner.source.authorize_pair.call_count == 2
    assert value.owner.artifacts.load_json_revision.call_count == 1


@pytest.mark.parametrize("state", ["REQUESTED", "RUNNING", "FAILED", "CANCELLED"])
@pytest.mark.parametrize("mode", ["STATUS_ONLY", "CANONICAL_RESULT"])
def test_new_nonterminal_or_unsuccessful_read_never_fabricates_axes_or_member(
    monkeypatch: pytest.MonkeyPatch, state: str, mode: str
) -> None:
    value = owner_fixture_v11(monkeypatch, state)
    response = value.owner.read_v11(OPERATOR_ID, read_request_v11(mode))
    assert response.result_state == (
        "PENDING" if state in {"REQUESTED", "RUNNING"} else "NO_RESULT"
    )
    assert response.result is None and response.result_artifact is None
    value.owner.artifacts.load_json_revision.assert_not_called()


def test_new_status_pointer_is_not_model_or_scientific_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = owner_fixture_v11(monkeypatch)
    response = value.owner.read_v11(OPERATOR_ID, read_request_v11("STATUS_ONLY"))
    assert response.result_state == "POINTER_ONLY" and response.result is None
    value.owner.artifacts.load_json_revision.assert_not_called()


@pytest.mark.parametrize("successor", [False, True])
def test_read_generation_cannot_promote_or_downgrade_saved_workflow(
    monkeypatch: pytest.MonkeyPatch, successor: bool
) -> None:
    old_fixture = cast(Callable[[pytest.MonkeyPatch], SimpleNamespace], owner_fixture)
    old_query = cast(Callable[[], InferenceTransferWorkflowReadRequest], read_request)
    value = owner_fixture_v11(monkeypatch) if successor else old_fixture(monkeypatch)
    with pytest.raises(InferenceTransferServiceError, match="WORKFLOW_REQUEST_INVALID"):
        if successor:
            value.owner.read(OPERATOR_ID, old_query())
        else:
            value.owner.read_v11(OPERATOR_ID, read_request_v11())
    value.owner.artifacts.load_json_revision.assert_not_called()


@pytest.mark.parametrize("at", ["initial", "final"])
def test_new_member_read_cannot_reuse_permission_snapshot_after_revocation(
    monkeypatch: pytest.MonkeyPatch, at: str
) -> None:
    value = owner_fixture_v11(monkeypatch)
    failure = InferenceTransferServiceError("INFERENCE_TRANSFER_FORBIDDEN")
    value.owner.source.authorize_pair.side_effect = failure if at == "initial" else [None, failure]
    with pytest.raises(InferenceTransferServiceError, match="FORBIDDEN"):
        value.owner.read_v11(OPERATOR_ID, read_request_v11())
    assert value.owner.artifacts.load_json_revision.call_count == (0 if at == "initial" else 1)


def test_new_read_remains_own_creator_only(monkeypatch: pytest.MonkeyPatch) -> None:
    value = owner_fixture_v11(monkeypatch)
    with pytest.raises(InferenceTransferServiceError, match="FORBIDDEN"):
        value.owner.read_v11(OTHER_OPERATOR_ID, read_request_v11())
    value.owner.source.authorize_pair.assert_not_called()


@pytest.mark.parametrize(
    "entity,field,replacement",
    [
        ("workflow", "definition_version", "1.0.0"),
        ("workflow", "role_schema_version", "workflow-role/1.29.0"),
        ("step", "result_schema", "item-inference-transfer-pair-result@1.0"),
        ("job", "protocol_version", "workflow-role/1.29.0"),
        ("revision", "approved", False),
        ("plan", "resolver_version", "21.0.0"),
        ("plan", "plan_sha256", "sha256:" + "f" * 64),
    ],
)
def test_new_read_rejects_legacy_or_changed_lineage_before_bytes(
    monkeypatch: pytest.MonkeyPatch, entity: str, field: str, replacement: object
) -> None:
    value = owner_fixture_v11(monkeypatch)
    setattr(getattr(value, entity), field, replacement)
    with pytest.raises(InferenceTransferServiceError, match="RESULT_INVALID"):
        value.owner.read_v11(OPERATOR_ID, read_request_v11())
    value.owner.artifacts.load_json_revision.assert_not_called()


def test_new_exact_raw_hash_does_not_waive_axis_reference_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = owner_fixture_v11(monkeypatch)
    document = deepcopy(value.document)
    document["output"]["axes"][0]["left_claim_ids"] = ["transferclaim_unknown"]
    document["output"]["result_sha256"] = content_sha256(
        {key: item for key, item in document["output"].items() if key != "result_sha256"}
    )
    # A consistent raw payload/hash is still not selected-reference authority.
    value.owner.artifacts.load_json_revision.return_value = document
    value.revision.content_hash = content_sha256(document)
    value.revision.content_bytes = len(canonical_json_bytes(document))
    value.revision.manifest.update(
        content_hash=value.revision.content_hash, content_bytes=value.revision.content_bytes
    )
    value.revision.manifest_hash = content_sha256(value.revision.manifest)
    value.step.output_pointer_manifest["content_hash"] = value.revision.content_hash
    with pytest.raises(InferenceTransferServiceError, match="RESULT_INVALID"):
        value.owner.read_v11(OPERATOR_ID, read_request_v11())
