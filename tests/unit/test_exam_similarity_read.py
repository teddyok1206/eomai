"""Actual schema/service orchestration with synthetic source/identity, not live acceptance."""

import json
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts import build_mock_exam_assembly_cohort
from eom_catalog_contracts.exam_similarity_read import (
    ExamObservationReadReply,
    ExamObservationReadRequest,
    validate_exam_observation_read_reply,
)
from eom_catalog_contracts.validation import load_schema
from eom_catalog_service import exam_similarity_read_service as module
from eom_catalog_service.exam_similarity_read_service import (
    CatalogExamSimilarityReadService,
    ExamObservationReadError,
)
from eom_catalog_service.mock_exam_assembly_service import (
    MockExamAssemblyError,
    MockExamAssemblyService,
)
from eom_catalog_service.similarity_context_ports import SimilarityContextReadError
from eom_identifiers import canonical_json_bytes
from eom_operator_identity import PermissionKey
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError
from sqlalchemy import create_engine

from tests.unit.exam_similarity_read_fixtures import read_case
from tests.unit.inference_transfer_embedding_fixtures import seal


def test_protocol_closed_schema_and_exact_actor_selection_reply():
    request, reply, _ = read_case()
    Draft202012Validator.check_schema(load_schema("system-rag-exam-observation-read"))
    validate_exam_observation_read_reply(request, reply)
    assert ExamObservationReadReply.model_validate(json.loads(canonical_json_bytes(reply))) == reply
    for name, value in (("actor_id", "ADMIN"), ("role", "ADMIN"), ("vectors", [[0.5]])):
        body = request.model_dump(mode="json") | {name: value}
        with pytest.raises((ValueError, SchemaError)):
            ExamObservationReadRequest.model_validate(body)


@pytest.mark.parametrize("fault", ("actor", "hash", "partial", "unpaired", "unknown_code"))
def test_substituted_or_partial_reply_never_passes(fault):
    request, reply, _ = read_case()
    body = reply.model_dump(mode="json")
    if fault == "actor":
        body["actor_id"] = "operator_" + "f" * 32
    elif fault == "hash":
        body["request_sha256"] = "sha256:" + "f" * 64
    else:
        body |= {"status": "FAILED", "error_code": "SOURCE_REVOKED"}
        if fault == "unpaired":
            body |= {"result": None, "actor_id": None}
        elif fault == "unknown_code":
            body |= {"result": None, "error_code": "secret/private/path"}
    with pytest.raises((ValueError, SchemaError)):
        validate_exam_observation_read_reply(request, ExamObservationReadReply.model_validate(body))


@pytest.mark.parametrize("version", (1, 2, 3))
def test_source_service_reuses_real_released_manifest_projection_and_same_root(
    monkeypatch, version
):
    request, reply, manifest = read_case(version)
    engine = create_engine("sqlite+pysqlite:///:memory:")
    root = SimpleNamespace(is_active=True)
    operator = SimpleNamespace(status="ACTIVE", deleted_at=None, must_change_password=False)
    session = SimpleNamespace(
        get=Mock(return_value=operator),
        get_transaction=lambda: root,
        in_nested_transaction=lambda: False,
    )
    capture = Mock(return_value=reply.result)
    owner = SimpleNamespace(
        catalog=SimpleNamespace(engine=engine, observe_exam_similarity_in_session=capture),
        identity=SimpleNamespace(fence_current_operator=Mock()),
    )
    service = CatalogExamSimilarityReadService(owner.catalog, owner.identity)
    service.sessions = SimpleNamespace(begin=lambda: nullcontext(session))
    inspect = Mock(return_value=manifest)
    monkeypatch.setattr(module.MockExamAssemblyService, "inspect_observation_source", inspect)
    permissions = Mock(return_value=frozenset({PermissionKey.DELIVERABLE_READ}))
    monkeypatch.setattr(module, "effective_permissions", permissions)
    try:
        assert service.read(request) == reply.result
        assert inspect.call_count == 2 and permissions.call_count == 2
        capture.assert_called_once()
        assert capture.call_args.args[0] is session
        assert capture.call_args.args[1].operator_id == request.actor_id
        assert capture.call_args.args[2] == request.selection.observation_request
        assert owner.identity.fence_current_operator.call_args_list == [
            ((session, request.actor_id),),
            ((session, request.actor_id),),
        ]
    finally:
        engine.dispose()


@pytest.mark.parametrize("state", ("RELEASED", "SUPERSEDED", "WITHDRAWN", "missing"))
def test_assembly_lifecycle_read_refreshes_existing_record_not_latest(state):
    request, _, manifest = read_case()
    row = SimpleNamespace(
        revision_state=state,
        canonical_document=manifest.model_dump(mode="json"),
        manifest_sha256=manifest.manifest_sha256,
    )
    session = SimpleNamespace(get=Mock(return_value=None if state == "missing" else row))
    if state == "WITHDRAWN":
        with pytest.raises(MockExamAssemblyError, match="withdrawn"):
            MockExamAssemblyService.inspect_observation_source(
                session, request.selection.assembly_revision_id
            )
    else:
        actual = MockExamAssemblyService.inspect_observation_source(
            session, request.selection.assembly_revision_id
        )
        assert actual == (None if state == "missing" else manifest)
    assert session.get.call_args_list[0].kwargs == {"populate_existing": True}


def test_observation_graph_is_explicit_and_not_rebased_to_historical_planning_graph(monkeypatch):
    request, _reply, manifest = read_case()
    selected = request.selection.model_dump(mode="json")
    observation = selected["observation_request"]
    observation["graph_snapshot"]["graph_snapshot_revision_id"] = "graphrev_" + "f" * 32
    selected["observation_request"] = seal(observation, "request_sha256")
    request = ExamObservationReadRequest.model_validate(
        request.model_dump(mode="json") | {"selection": selected}
    )
    inspect = Mock(return_value=manifest)
    monkeypatch.setattr(module.MockExamAssemblyService, "inspect_observation_source", inspect)
    # This verifies selection semantics only. Actual Graph/binding authorization
    # still belongs to the real document owner, not this fake manifest reader.
    CatalogExamSimilarityReadService._inspect_selection(object(), request.selection)
    assert request.selection.observation_request.graph_snapshot.graph_snapshot_revision_id == (
        "graphrev_" + "f" * 32
    )
    assert manifest.graph_snapshot_revision_id != "graphrev_" + "f" * 32


@pytest.mark.parametrize(
    "fault", ("disabled", "denied", "missing", "wrong_hash", "wrong_order", "late_revoked", "index")
)
def test_source_denial_and_pin_failures_do_not_return_partial_result(monkeypatch, fault):
    request, reply, manifest = read_case()
    engine = create_engine("sqlite+pysqlite:///:memory:")
    root = SimpleNamespace(is_active=True)
    operator = SimpleNamespace(
        status="DISABLED" if fault == "disabled" else "ACTIVE",
        deleted_at=None,
        must_change_password=False,
    )
    session = SimpleNamespace(
        get=Mock(return_value=operator),
        get_transaction=lambda: root,
        in_nested_transaction=lambda: False,
    )
    capture = Mock(return_value=reply.result)
    owner = SimpleNamespace(
        catalog=SimpleNamespace(engine=engine, observe_exam_similarity_in_session=capture),
        identity=SimpleNamespace(fence_current_operator=Mock()),
    )
    service = CatalogExamSimilarityReadService(owner.catalog, owner.identity)
    service.sessions = SimpleNamespace(begin=lambda: nullcontext(session))
    permissions = Mock(
        return_value=frozenset()
        if fault == "denied"
        else frozenset({PermissionKey.DELIVERABLE_READ})
    )
    monkeypatch.setattr(module, "effective_permissions", permissions)
    inspect = Mock(return_value=None if fault == "missing" else manifest)
    if fault == "late_revoked":
        inspect.side_effect = [
            manifest,
            MockExamAssemblyError("ASSEMBLY_REVISION_INELIGIBLE", "withdrawn"),
        ]
    if fault == "index":
        capture.side_effect = SimilarityContextReadError("INDEX_HASH_MISMATCH")
    if fault == "wrong_hash":
        request = ExamObservationReadRequest.model_validate(
            request.model_dump(mode="json")
            | {
                "selection": request.selection.model_dump(mode="json")
                | {"assembly_manifest_sha256": "sha256:" + "f" * 64}
            }
        )
    if fault == "wrong_order":
        selected = request.selection.model_dump(mode="json")
        observation = selected["observation_request"]
        observation["cohort"] = build_mock_exam_assembly_cohort(
            tuple(
                reversed(
                    tuple(
                        m.item_revision_id
                        for m in request.selection.observation_request.cohort.members
                    )
                )
            )
        ).model_dump(mode="json")
        selected["observation_request"] = seal(observation, "request_sha256")
        request = ExamObservationReadRequest.model_validate(
            request.model_dump(mode="json") | {"selection": selected}
        )
    monkeypatch.setattr(module.MockExamAssemblyService, "inspect_observation_source", inspect)
    try:
        with pytest.raises(ExamObservationReadError) as error:
            service.read(request)
        assert (
            error.value.code
            == {
                "disabled": "SOURCE_ACCESS_DENIED",
                "denied": "SOURCE_ACCESS_DENIED",
                "missing": "ASSEMBLY_REVISION_NOT_FOUND",
                "wrong_hash": "ASSEMBLY_OBSERVATION_PIN_MISMATCH",
                "wrong_order": "ASSEMBLY_OBSERVATION_PIN_MISMATCH",
                "late_revoked": "SOURCE_REVOKED",
                "index": "INDEX_HASH_MISMATCH",
            }[fault]
        )
        if fault in {"disabled", "denied", "missing", "wrong_hash", "wrong_order"}:
            capture.assert_not_called()
    finally:
        engine.dispose()
