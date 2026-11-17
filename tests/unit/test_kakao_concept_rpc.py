"""Closed public concept projections/peer transport, never real model or retrieval evidence."""

import io
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.kakao_concept_rpc import (
    ConceptFailure,
    ConceptHistory,
    ConceptStarted,
    ConceptSuccess,
    ConceptSummary,
    ConceptView,
    ListConceptsRequest,
    ReadConceptRequest,
    StartConceptRequest,
    check_concept_reply,
    parse_concept_reply,
    parse_concept_request,
)
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES
from eom_catalog_service import kakao_concept_dispatch as dispatch
from eom_catalog_service.kakao_concept_reads import project_kakao_concept_result
from eom_identifiers import sha256_bytes

from tests.unit.test_kakao_concept_contracts import ROOT
from tests.unit.test_kakao_concept_study import inputs
from tests.unit.test_kakao_concept_tasks import command_value
from tests.unit.test_kakao_question_rpc import IDENTITY


def summary():
    command = command_value()
    return ConceptSummary(
        task_id="kakaoconcepttask_" + "a" * 32,
        created_at=datetime.now(UTC),
        **{
            key: command[key]
            for key in ("source_binding_id", "question_id", "question_revision_id")
        },
    )


def cases():
    task = summary()
    return [
        (
            StartConceptRequest(
                **IDENTITY, command=command_value(), idempotency_key="concept-fixture-key-0001"
            ),
            ConceptStarted(task=task, replayed=True),
        ),
        (
            ReadConceptRequest(
                **IDENTITY, source_binding_id=task.source_binding_id, task_id=task.task_id
            ),
            ConceptView(task=task, state="PLAN_PENDING"),
        ),
        (
            ListConceptsRequest(**IDENTITY, source_binding_id=task.source_binding_id),
            ConceptHistory(items=(task,), next_cursor=None),
        ),
    ]


def test_schema_mirror_and_hash():
    resource = CATALOG_SCHEMA_RESOURCES["catalog-kakao-concept-v1"]
    raw = (ROOT / resource.canonical_path).read_bytes()
    assert (
        raw
        == (
            ROOT / "packages/catalog_contracts/eom_catalog_contracts" / resource.resource_path
        ).read_bytes()
    )
    assert sha256_bytes(raw) == resource.sha256


@pytest.mark.parametrize("req,result", cases())
def test_parse_dispatch_and_correlation(req, result, monkeypatch):
    service, out = Mock(), io.BytesIO()
    if isinstance(req, StartConceptRequest):
        handler = Mock(return_value=(SimpleNamespace(task=result.task, replayed=True), object()))
        monkeypatch.setattr(dispatch, "start_kakao_concept_task", handler)
    else:
        name = (
            "read_kakao_concept" if isinstance(req, ReadConceptRequest) else "list_kakao_concepts"
        )
        handler = Mock(return_value=result)
        # Optional read adapters are imported only when this RPC executes.
        from eom_catalog_service import kakao_concept_reads

        monkeypatch.setattr(kakao_concept_reads, name, handler)
    assert parse_concept_request(req.model_dump(mode="json")) == req
    dispatch.dispatch_kakao_concept(service, req.model_dump(mode="json"), out)
    reply = parse_concept_reply(json.loads(out.getvalue()))
    assert reply.status == "OK" and reply.result == result
    check_concept_reply(req, reply)


@pytest.mark.parametrize("req,result", cases())
def test_other_task_binding_operation_and_request_are_rejected(req, result):
    if hasattr(result, "task"):
        changed = result.model_copy(
            update={
                "task": result.task.model_copy(
                    update={"source_binding_id": "kakaobinding_" + "f" * 32}
                )
            }
        )
    else:
        changed = result.model_copy(
            update={
                "items": (
                    result.items[0].model_copy(
                        update={"source_binding_id": "kakaobinding_" + "f" * 32}
                    ),
                )
            }
        )
    with pytest.raises(ValueError, match="RESULT_INVALID"):
        check_concept_reply(
            req,
            ConceptSuccess(operation=req.operation, request_id=req.request_id, result=changed),
        )
    with pytest.raises(ValueError, match="RESULT_INVALID"):
        check_concept_reply(
            req,
            ConceptFailure(
                operation=req.operation,
                request_id="unrelated-req",
                error_code="KAKAO_ARCHIVE_REQUEST_INVALID",
            ),
        )


@pytest.mark.parametrize(
    "field,value", [("role", "ADMIN"), ("slot", "05"), ("path", "/mnt/nas"), ("scope", {})]
)
def test_no_caller_authority_or_paths(field, value):
    req, _ = cases()[0]
    app, out = Mock(), io.BytesIO()
    dispatch.dispatch_kakao_concept(app, req.model_dump(mode="json") | {field: value}, out)
    assert json.loads(out.getvalue())["error_code"] == "KAKAO_ARCHIVE_REQUEST_INVALID"
    assert not app.mock_calls


def test_start_refuses_when_automatic_continuation_disabled(monkeypatch):
    req, _ = cases()[0]
    start = Mock()
    monkeypatch.setattr(dispatch, "start_kakao_concept_task", start)
    out = io.BytesIO()
    dispatch.dispatch_kakao_concept(
        SimpleNamespace(concepts=object(), concept_coordinator=None),
        req.model_dump(mode="json"),
        out,
    )
    assert json.loads(out.getvalue())["error_code"] == "KAKAO_CONCEPT_RUNTIME_UNAVAILABLE"
    start.assert_not_called()


def test_materialized_result_projection_distinguishes_quotes_and_actual_page(tmp_path):
    _artifacts, _staged, _outputs, req, result, _captures = inputs(tmp_path)
    completed = SimpleNamespace(
        request=req,
        result=SimpleNamespace(output=result),
        pin=SimpleNamespace(sha256="sha256:" + "a" * 64),
    )
    projected = project_kakao_concept_result(summary(), completed)
    assert projected.state == "COMPLETED" and len(projected.blocks) == 1
    assert projected.blocks[0].captures[0].physical_page == 1
    assert projected.blocks[0].captures[0].source_title == "검증 교과서"
    assert projected.blocks[0].citations[0].kind == "APPROVED_ANALYSIS_NOT_VERBATIM_SOURCE"
    raw = projected.model_dump_json()
    assert "relative_path" not in raw and "artifact_id" not in raw and "analysis_text" not in raw
    assert (
        parse_concept_reply(
            ConceptSuccess(
                operation="READ_KAKAO_CONCEPT", request_id="fixture-req", result=projected
            ).model_dump(mode="json")
        ).result
        == projected
    )


def test_result_blocks_cannot_be_shown_before_completed():
    with pytest.raises(ValueError, match="RESULT_INVALID"):
        ConceptView(task=summary(), state="PLAN_RUNNING", result_sha256="sha256:" + "a" * 64)
    for state in ("COMPLETED", "NEEDS_INPUT"):
        with pytest.raises(ValueError, match="RESULT_INVALID"):
            ConceptView(task=summary(), state=state)
