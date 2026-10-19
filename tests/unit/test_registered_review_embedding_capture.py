"""Actual local registered-role members; synthetic admission, no DB/model/auth."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock, patch

import pytest
from eom_catalog_contracts.curriculum import resolve_integrated_science_curriculum_scope
from eom_catalog_contracts.knowledge import KnowledgeGraphSnapshotPointer
from eom_catalog_service.embedding_registry_ports import EmbeddingRegistryError
from eom_catalog_service.evidence_usage_receipts import OrchestratorEvidenceUsageReceiptResolver
from eom_catalog_service.inference_transfer_service import AdmittedInferenceTransferSource
from eom_catalog_service.registered_review_embedding_capture import (
    capture_registered_review_embedding_entries,
)
from eom_identifiers import content_sha256
from eom_orchestrator.control_models import ResolvedExecutionPlanRecord
from eom_orchestrator.models import ArtifactRecord
from eom_workflow import WorkflowRequest, compile_definition
from eom_workflow_runner.models import WorkflowDefinitionRecord, WorkflowInstanceRecord
from eom_workflow_runner.repository import workflow_business_fingerprint

from tests.unit.inference_transfer_embedding_fixtures import view_recipe
from tests.unit.inference_transfer_snapshot_fixtures import snapshot_v3_record
from tests.unit.test_execution_materializer import _knowledge_fixture
from tests.unit.test_graph_review_v11_protocol import _upgrade_fixture_plan_to_v12
from tests.unit.test_registered_item_review_solution_resolver import _Artifacts, _fixture, _Session

ROOT = Path(__file__).resolve().parents[2]


def _capture_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, count: int = 1, family: int = 11
) -> dict[str, Any]:
    knowledge_root = tmp_path / "knowledge"
    knowledge_root.mkdir()
    knowledge = _knowledge_fixture(
        knowledge_root,
        monkeypatch,
        manifest_schema_version="5.0",
        workflow_definition_version="1.11.0",
    )
    if family == 12:
        _upgrade_fixture_plan_to_v12(knowledge)
    original = knowledge["session"].records[ResolvedExecutionPlanRecord, str(knowledge["plan_id"])]
    body = deepcopy(original.canonical_document)
    version = body["workflow_definition_version"]
    compiled = compile_definition(
        ROOT / f"config/workflows/generic-item-development.v{version[:-2]}.yaml",
        {"authoring", "image", "review", "item_management"},
    )
    body["workflow_definition_sha256"] = compiled.sha256
    scope = resolve_integrated_science_curriculum_scope("eom.is.middle.1-1")
    body["retrieval_requirement"]["curriculum_root_key"] = scope.graph_root_stable_key
    body["retrieval_requirement"]["topic_keys"] = []
    body["retrieval_requirement_sha256"] = content_sha256(body["retrieval_requirement"])
    body["plan_sha256"] = content_sha256(
        {key: value for key, value in body.items() if key != "plan_sha256"}
    )
    original.canonical_document, original.plan_sha256 = body, body["plan_sha256"]
    session = _Session()
    session.get_nested_transaction = lambda: None
    fixtures = []
    for index in range(1, count + 1):
        item_root = tmp_path / str(index)
        item_root.mkdir()
        value = _fixture(
            item_root, monkeypatch, ordinal=index, family=family, knowledge_fixture=knowledge
        )
        own = value["session"]
        request_body = json.loads(
            (
                ROOT / "content/packs/generated-knowledge-item/1.20.12/fixtures/smoke-request.json"
            ).read_text()
        )
        request_body["item_brief"]["curriculum_scope"] = scope.model_dump(mode="json")
        request_body["execution_preset_key"] = "knowledge-grounded-item"
        request_body["educational_retrieval"] = body["retrieval_requirement"]
        request = WorkflowRequest.model_validate(request_body)
        definition = WorkflowDefinitionRecord(
            definition_id="workflowdef_" + "f" * 32,
            definition_key="generic-item-development",
            definition_version=version,
            canonical_definition=compiled.as_dict(),
            definition_hash=compiled.sha256,
        )
        workflow = own.records[WorkflowInstanceRecord, value["workflow_id"]]
        workflow.definition_id, workflow.definition_hash = (
            definition.definition_id,
            definition.definition_hash,
        )
        workflow.initial_request = request.model_dump(mode="json")
        workflow.request_payload = request.model_dump(mode="json")
        workflow.request_hash = workflow_business_fingerprint(definition, request)
        own.records[WorkflowDefinitionRecord, definition.definition_id] = definition
        session.records.update(own.records)
        session.components.extend(own.components)
        session.steps.extend(own.steps)
        session.events.extend(own.events)
        fixtures.append(value)
    graph = KnowledgeGraphSnapshotPointer.model_validate(body["graph_snapshot"])
    return {
        "session": session,
        "fixtures": fixtures,
        "graph": graph,
        "admitted": tuple(
            AdmittedInferenceTransferSource(
                "analysisrun_" + f"{1000 + index:032x}", value["source"]
            )
            for index, value in enumerate(fixtures)
        ),
        "artifacts": _Artifacts(tmp_path, session),
        "receipts": OrchestratorEvidenceUsageReceiptResolver(cast(Any, lambda: session)),
        "auth": [],
    }


def _capture(value: dict[str, Any], **changes: Any) -> Any:
    return capture_registered_review_embedding_entries(
        cast(Any, value["session"]),
        admitted_sources=changes.get("admitted_sources", value["admitted"]),
        existing_entries=changes.get("existing_entries", ()),
        graph_snapshot=value["graph"],
        recipe=changes.get("recipe", view_recipe()),
        artifacts=value["artifacts"],
        receipts=value["receipts"],
        authorize_source=changes.get("authorize_source", value["auth"].append),
    )


@pytest.mark.parametrize("family", [11, 12])
def test_real_registered_review_materializes_pure_question_and_claims(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, family: int
) -> None:
    value = _capture_fixture(tmp_path, monkeypatch, family=family)
    captured = _capture(value)
    assert len(captured.entries) == 1 and captured.missing_source_revision_ids == ()
    entry = captured.entries[0]
    source = value["admitted"][0].source
    assert entry.profile.source_basis.source == source
    assert entry.content.original_source == source.artifact_member
    assert "정답" not in entry.content.text
    assert all(
        field.basis == "ORIGINAL_ITEM" and field.source_sha256 == source.artifact_member.sha256
        for field in entry.metadata
    )
    assert captured.base_analysis_run_ids == (
        (source.item_revision_id, value["admitted"][0].analysis_run_id),
    )
    assert len(value["auth"]) == 4
    captured.assert_current(cast(Any, value["session"]))


def test_real_past_v3_and_legacy_entry_are_preserved_without_registered_reads() -> None:
    record = snapshot_v3_record()
    assert record.staged_entry is not None
    entry = record.staged_entry
    source = record.source
    session = _Session()
    session.get_nested_transaction = lambda: None
    raw_before = source.model_dump(mode="json")
    with patch(
        "eom_catalog_service.registered_review_embedding_capture.resolve_registered_item_review_solutions"
    ) as resolver:
        captured = capture_registered_review_embedding_entries(
            cast(Any, session),
            admitted_sources=(
                AdmittedInferenceTransferSource(
                    entry.profile.source_basis.solution_evidence.base_analysis_run_id, source
                ),
            ),
            existing_entries=(entry,),
            graph_snapshot=entry.profile.source_basis.graph_snapshot,
            recipe=view_recipe(),
            artifacts=cast(Any, object()),
            receipts=cast(Any, object()),
            authorize_source=Mock(
                side_effect=AssertionError("legacy source already admitted by original owner")
            ),
        )
    assert captured.entries == (entry,) and captured.missing_source_revision_ids == ()
    assert source.model_dump(mode="json") == raw_before
    resolver.assert_not_called()
    assert session.statements == []


@pytest.mark.parametrize(
    "failure", ["missing_component", "wrong_workflow_role", "revoked_artifact", "plan_hash"]
)
def test_supported_corruption_never_becomes_quiet_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    value = _capture_fixture(tmp_path, monkeypatch)
    session = value["session"]
    if failure == "missing_component":
        session.components = [
            row for row in session.components if row.component_type != "REVIEW_REPORT"
        ]
    elif failure == "wrong_workflow_role":
        next(
            row for (model, _), row in session.records.items() if model is WorkflowInstanceRecord
        ).role_schema_version = "workflow-role/1.17.0"
    elif failure == "plan_hash":
        next(
            row
            for (model, _), row in session.records.items()
            if model is ResolvedExecutionPlanRecord
        ).plan_sha256 = "sha256:" + "0" * 64
    else:
        next(
            row for (model, _), row in session.records.items() if model is ArtifactRecord
        ).approved = False
    with pytest.raises(ValueError):
        _capture(value)


def test_unsupported_historical_review_is_explicit_missing_not_new_analysis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = _capture_fixture(tmp_path, monkeypatch)
    session = value["session"]
    workflow = next(
        row for (model, _), row in session.records.items() if model is WorkflowInstanceRecord
    )
    workflow.role_schema_version = "workflow-role/1.20.0"
    for row in session.components:
        if row.component_type == "UPPER_STEM":
            row.schema_ref = "authoring-result@10.0"
        if row.component_type == "REVIEW_REPORT":
            row.schema_ref = "review-result@10.0"
    with patch(
        "eom_catalog_service.registered_review_embedding_capture.resolve_registered_item_review_solutions"
    ) as resolver:
        result = _capture(value)
    assert result.entries == ()
    assert result.missing_source_revision_ids == (value["admitted"][0].source.item_revision_id,)
    assert result.limitations[0][1] == "REGISTERED_REVIEW_UNSUPPORTED_HISTORICAL_FAMILY"
    resolver.assert_not_called()


def test_late_current_permission_denial_preserves_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = _capture_fixture(tmp_path, monkeypatch)
    calls = 0

    def authorize(_source: Any) -> None:
        nonlocal calls
        calls += 1
        if calls == 4:
            raise PermissionError("ACTUAL_SOURCE_WITHDRAWN")

    with pytest.raises(PermissionError, match="ACTUAL_SOURCE_WITHDRAWN"):
        _capture(value, authorize_source=authorize)


def test_same_savepoint_capture_succeeds_but_released_handle_cannot_be_reused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = _capture_fixture(tmp_path, monkeypatch)
    nested = SimpleNamespace(is_active=True)
    value["session"].get_nested_transaction = lambda: nested
    capture = _capture(value)
    capture.assert_current(cast(Any, value["session"]))
    nested.is_active = False
    with pytest.raises(EmbeddingRegistryError):
        capture.assert_current(cast(Any, value["session"]))


@pytest.mark.parametrize("count", [1, 2, 16])
def test_batch_query_count_is_fixed_and_projection_happens_once_per_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, count: int
) -> None:
    value = _capture_fixture(tmp_path, monkeypatch, count=count)
    capture = _capture(value)
    assert len(capture.entries) == count and capture.missing_source_revision_ids == ()
    assert len(value["session"].statements) == 5 + 8 + 17
    assert all("count(" not in str(statement).lower() for statement in value["session"].statements)
    assert value["session"].new == value["session"].dirty == value["session"].deleted == set()
