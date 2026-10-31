"""Actual temporary IAM/Artifact rows; completed QUERY/source reads are explicitly synthetic."""

from dataclasses import replace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.item_similarity_publication import ItemSimilarityPublicationRequestV2
from eom_catalog_contracts.registered_public_solution_similarity import (
    parse_supported_public_solution_similarity_context,
)
from eom_catalog_contracts.similarity_read import CompletedSimilarityQuerySelection
from eom_catalog_service import item_similarity_publication_service as module
from eom_catalog_service.item_similarity_publication_service import (
    CatalogItemSimilarityPublicationService,
)
from eom_catalog_service.similarity_context_ports import SimilarityContextReadError
from eom_identifiers import content_sha256
from eom_identity_service import OperatorAuthorizationFenceError
from eom_identity_service.models import RolePermissionRecord
from eom_orchestrator.control_service import ControlPlaneError
from eom_workflow.reference_query_execution import parse_supported_reference_query_workflow_request

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_item_similarity_preparation import counts, preparation_case
from tests.unit.test_public_solution_reference_query_execution import public_workflow_case
from tests.unit.test_public_solution_similarity_contracts import public_similarity_case
from tests.unit.test_registered_public_reference_query_execution import (
    registered_public_workflow_case,
)
from tests.unit.test_registered_public_solution_similarity_contracts import (
    registered_similarity_case,
)
from tests.unit.test_similarity_context_artifact import SOURCE


def public_service_case(tmp_path, monkeypatch, version=4, purpose="ITEM_AUTHORING"):
    value = preparation_case(tmp_path, monkeypatch)
    value.value.query.owner.catalog.engine = value.publisher.engine
    workflow = (
        public_workflow_case()
        if version == 3
        else registered_public_workflow_case(registered_anchor=False)
    )
    _, context, *_ = (public_similarity_case if version == 3 else registered_similarity_case)()
    body = workflow.request.model_dump(mode="json")
    body["operator_audit"]["operator_id"] = value.caller.operator_id
    body["context_request"]["consumer_purpose"] = purpose
    body["context_request"] = seal(body["context_request"], "request_sha256")
    original = parse_supported_reference_query_workflow_request(seal(body, "request_sha256"))
    context = parse_supported_public_solution_similarity_context(
        seal(
            context.model_dump(mode="json")
            | {"request": original.context_request.model_dump(mode="json")},
            "context_sha256",
        )
    )
    request = ItemSimilarityPublicationRequestV2(
        schema_version="system-rag-item-similarity-publication-request/2.0",
        operation="PUBLISH_ITEM_SIMILARITY_CONTEXT",
        actor_id=value.caller.operator_id,
        selection=CompletedSimilarityQuerySelection(
            workflow_id=value.value.query.workflow_id,
            workflow_request_sha256=original.request_sha256,
            context_request_sha256=original.context_request.request_sha256,
        ),
    )
    selected = Mock(return_value=original)
    reader = Mock(return_value=context)
    monkeypatch.setattr(module, "select_completed_reference_query_request", selected)
    monkeypatch.setattr(module, "read_completed_public_solution_similarity_in_session", reader)
    service = CatalogItemSimilarityPublicationService(
        value.value.query.owner,
        value.publisher,
        source_commit=SOURCE,
        public_owner=value.value.query.owner,
    )
    return value, service, request, selected, reader, context


@pytest.mark.parametrize("version", (3, 4))
def test_public_owner_rechecks_one_root_and_replays_one_canonical_artifact(
    tmp_path, monkeypatch, version
):
    value, service, request, selected, reader, context = public_service_case(
        tmp_path, monkeypatch, version
    )
    first = service.publish_public(request)
    assert service.publish_public(request) == first and counts(value) == (1, 1)
    assert first.delivery.context_sha256 == context.context_sha256
    assert first.delivery.context_member.sha256 == content_sha256(context.model_dump(mode="json"))
    assert first.delivery.schema_version == "system-rag-similarity-delivery/2.0"
    assert selected.call_count == 2 and reader.call_count == 4
    for before, after in zip(reader.call_args_list[::2], reader.call_args_list[1::2], strict=True):
        assert before.args[0] is after.args[0]
        assert before.args[1:] == (service.owner, value.caller, request.selection)
        assert after.args[1:] == before.args[1:]
    assert reader.call_args_list[0].args[0] is not reader.call_args_list[2].args[0]


def test_publication_requires_explicit_public_owner_without_legacy_fallback(tmp_path, monkeypatch):
    value, service, request, selected, reader, _ = public_service_case(tmp_path, monkeypatch)
    service.public_owner = None
    with pytest.raises(ControlPlaneError) as caught:
        service.publish_public(request)
    assert caught.value.code == "CONTROL_SIMILARITY_AUTHORITY_UNAVAILABLE"
    selected.assert_not_called()
    reader.assert_not_called()
    assert counts(value) == (0, 0)


@pytest.mark.parametrize("purpose", ("ITEM_DATABASE_SEARCH", "ITEM_REVIEW"))
def test_other_consumer_purpose_cannot_publish_item_start_context(tmp_path, monkeypatch, purpose):
    value, service, request, _, reader, _ = public_service_case(
        tmp_path, monkeypatch, purpose=purpose
    )
    with pytest.raises(ControlPlaneError) as caught:
        service.publish_public(request)
    assert caught.value.code == "CONTROL_SIMILARITY_PREPARATION_INVALID"
    reader.assert_not_called()
    assert counts(value) == (0, 0)


def test_legacy_query_cannot_be_relabelled_as_publication2(tmp_path, monkeypatch):
    value, service, request, selected, reader, _ = public_service_case(tmp_path, monkeypatch)
    selected.return_value = value.value.query.request
    with pytest.raises(ControlPlaneError) as caught:
        service.publish_public(request)
    assert caught.value.code == "CONTROL_SIMILARITY_PREPARATION_INVALID"
    reader.assert_not_called()
    assert counts(value) == (0, 0)


def test_replay_requires_actual_current_start_permission(tmp_path, monkeypatch):
    value, service, request, _, _, _ = public_service_case(tmp_path, monkeypatch)
    first = service.publish_public(request)
    with value.publisher.sessions.begin() as session:
        session.delete(
            session.get(RolePermissionRecord, ("role_" + "a" * 32, "permission_" + "0" * 32))
        )
    with pytest.raises(ControlPlaneError) as caught:
        service.publish_public(request)
    assert caught.value.code == "CONTROL_SIMILARITY_AUTHORITY_DENIED"
    assert counts(value) == (1, 1)
    with value.publisher.sessions.begin() as session:
        session.add(
            RolePermissionRecord(role_id="role_" + "a" * 32, permission_id="permission_" + "0" * 32)
        )
    assert service.publish_public(request) == first and counts(value) == (1, 1)


@pytest.mark.parametrize(
    "stage", ("selector", "early_read", "late_read", "late_permission", "receipt")
)
def test_failure_preserves_history_and_never_rekeys_or_launches_another_query(
    tmp_path, monkeypatch, stage
):
    value, service, request, selected, reader, context = public_service_case(tmp_path, monkeypatch)
    if stage == "selector":
        selected.side_effect = SimilarityContextReadError("QUERY_RESULT_INVALID")
    elif stage == "early_read":
        reader.side_effect = SimilarityContextReadError("SOURCE_REVOKED")
    elif stage == "late_read":
        reader.side_effect = [context, SimilarityContextReadError("SOURCE_REVOKED")]
    elif stage == "late_permission":
        value.value.query.owner.identity.fence_current_operator.side_effect = [
            None,
            OperatorAuthorizationFenceError("OPERATOR_AUTHORIZATION_FENCE_FORBIDDEN"),
        ]
    original_publisher = module.publish_public_solution_similarity_context
    if stage == "receipt":

        def wrong_receipt(*args, **kwargs):
            return replace(original_publisher(*args, **kwargs), owner_job_id="job_" + "0" * 32)

        monkeypatch.setattr(module, "publish_public_solution_similarity_context", wrong_receipt)
    with pytest.raises((ControlPlaneError, SimilarityContextReadError)) as caught:
        service.publish_public(request)
    assert (
        caught.value.code
        == {
            "selector": "QUERY_RESULT_INVALID",
            "early_read": "SOURCE_REVOKED",
            "late_read": "SOURCE_REVOKED",
            "late_permission": "CONTROL_SIMILARITY_AUTHORITY_DENIED",
            "receipt": "CONTROL_SIMILARITY_PREPARATION_INVALID",
        }[stage]
    )
    expected = (0, 0) if stage in {"selector", "early_read"} else (1, 1)
    assert counts(value) == expected
    if expected == (1, 1):
        selected.side_effect = None
        reader.side_effect = None
        value.value.query.owner.identity.fence_current_operator.side_effect = None
        monkeypatch.setattr(
            module, "publish_public_solution_similarity_context", original_publisher
        )
        first = service.publish_public(request)
        assert service.publish_public(request) == first and counts(value) == (1, 1)
