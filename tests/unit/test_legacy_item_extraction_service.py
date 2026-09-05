from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any, cast

import pytest
from eom_catalog_contracts import LegacyItemExtractionRequest
from eom_catalog_service.legacy_item_extraction_service import (
    CreateLegacyItemExtractionCommand,
    LegacyItemExtractionApplicationResult,
    LegacyItemExtractionApplicationService,
    LegacyItemExtractionServiceError,
)
from eom_identifiers import content_sha256
from eomctl.cli import app
from sqlalchemy.dialects import postgresql, sqlite
from typer.testing import CliRunner

ZERO_SHA = "sha256:" + "0" * 64


def _artifact(seed: str, path: str, media_type: str, schema_ref: str) -> dict[str, str]:
    return {
        "artifact_id": "artifact_" + seed * 32,
        "artifact_revision_id": "rev_" + seed * 32,
        "member_path": path,
        "schema_ref": schema_ref,
        "media_type": media_type,
        "sha256": "sha256:" + seed * 64,
    }


def _request(*, seed: str = "1") -> LegacyItemExtractionRequest:
    document: dict[str, Any] = {
        "schema_version": "legacy-item-extraction-request/1.0",
        "extraction_request_id": "itemextractreq_" + seed * 32,
        "bundle": {
            "assessment_source_bundle_id": "assessbundle_" + "2" * 32,
            "assessment_source_bundle_revision_id": "assessbundlerev_" + "2" * 32,
            "bundle_manifest_sha256": "sha256:" + "2" * 64,
        },
        "occurrence": {
            "assessment_occurrence_id": "occurrence_" + "3" * 32,
            "assessment_occurrence_revision_id": "occurrev_" + "3" * 32,
            "occurrence_revision_sha256": "sha256:" + "3" * 64,
        },
        "layout_observation": {
            "assessment_layout_observation_id": "assessmentlayout_" + "4" * 32,
            "artifact": _artifact(
                "4",
                "layout.json",
                "application/json",
                "eom://schemas/legacy-assessment/assessment-layout-observation/1.0",
            ),
            "workspace_relative_path": "source/layout-observation.json",
            "observation_sha256": "sha256:" + "4" * 64,
        },
        "work_unit_ordinal": 0,
        "expected_item_numbers": [1],
        "page_inputs": [
            {
                "page_input_id": "assessmentpage_" + "5" * 32,
                "source_role": "PROBLEM_DOCUMENT",
                "physical_page": 1,
                "source": _artifact(
                    "5", "problem.pdf", "application/pdf", "eom://schemas/test/source/1.0"
                ),
                "image": _artifact(
                    "6", "page.png", "image/png", "eom://schemas/test/page-image/1.0"
                ),
                "workspace_relative_path": ("source/pages/assessmentpage_" + "5" * 32 + ".png"),
                "width_px": 2480,
                "height_px": 3508,
            }
        ],
        "source_materializations": [],
        "execution_preset_id": "execpreset_" + "7" * 32,
        "execution_preset_revision_id": "execpresetrev_" + "7" * 32,
        "execution_preset_sha256": "sha256:" + "7" * 64,
        "worker_result_schema_ref": (
            "eom://schemas/legacy-assessment/legacy-item-extraction-result/1.0"
        ),
        "created_at": "2026-09-01T00:00:00Z",
        "request_sha256": ZERO_SHA,
    }
    document["request_sha256"] = content_sha256(
        {key: value for key, value in document.items() if key != "request_sha256"}
    )
    return LegacyItemExtractionRequest.model_validate(document)


def _result(workflow_id: str) -> LegacyItemExtractionApplicationResult:
    return LegacyItemExtractionApplicationResult(
        extraction_request_id="itemextractreq_" + "1" * 32,
        request_sha256="sha256:" + "1" * 64,
        workflow_id=workflow_id,
        workflow_state="REQUESTED",
        workflow_stage="KNOWLEDGE_ANALYSIS",
        plan_id="execplan_" + "1" * 32,
        plan_sha256="sha256:" + "2" * 64,
        preset_id="execpreset_" + "3" * 32,
        preset_revision_id="execpresetrev_" + "3" * 32,
        worker_pool_key="legacy-extraction",
        dedicated_slot_id="06",
        start_command_id="command_" + "4" * 32,
        platform_job_id=None,
        worker_slot_id=None,
        job_status=None,
        receipt_artifact_id=None,
        receipt_artifact_revision_id=None,
        receipt_content_sha256=None,
        extraction_result_id=None,
        result_sha256=None,
    )


class _ScalarSession:
    def __init__(self, values: list[object | None]) -> None:
        self.values = iter(values)

    def scalar(self, _query: object) -> object | None:
        return next(self.values)

    def flush(self) -> None:
        return None


def _service(session: object) -> LegacyItemExtractionApplicationService:
    service = object.__new__(LegacyItemExtractionApplicationService)
    service.sessions = cast(Any, object())
    return service


def test_create_is_atomic_and_enqueues_exactly_one_start_on_dedicated_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    definition = SimpleNamespace(
        definition_key="legacy-item-extraction",
        definition_version="1.0.0",
        definition_hash="sha256:" + "8" * 64,
        canonical_definition={
            "steps": [
                {
                    "type": "agent",
                    "result_schema": "legacy-item-extraction-result@1.0",
                }
            ]
        },
    )
    session = _ScalarSession([None, None, definition])
    service = _service(session)
    request = _request()
    workflow = SimpleNamespace(
        workflow_id="workflow_" + "9" * 32,
        role_schema_version="workflow-role/1.14.0",
        runtime_context={},
    )
    plan = SimpleNamespace(
        plan_id="execplan_" + "a" * 32,
        plan_sha256="sha256:" + "a" * 64,
        preset_id=request.execution_preset_id,
        preset_revision_id=request.execution_preset_revision_id,
        capacity_policy_revision_id="capacityrev_" + "b" * 32,
    )
    calls = {"validated": 0, "resolved": 0, "slot": 0, "enqueued": 0}

    @contextmanager
    def fake_transaction(_sessions: object) -> Iterator[_ScalarSession]:
        yield session

    def validate_pointers(_session: object, value: object) -> None:
        assert value == request
        calls["validated"] += 1

    def create_workflow(*_args: object, **kwargs: object) -> tuple[object, bool]:
        assert kwargs["actor_id"] == "operator-test"
        assert kwargs["runtime_context"]["legacy_item_extraction_request_sha256"] == (
            request.request_sha256
        )
        return workflow, True

    def resolve_plan(*_args: object, **kwargs: object) -> object:
        assert kwargs["request"] == request
        calls["resolved"] += 1
        return plan

    def require_slot(_session: object, revision_id: str) -> None:
        assert revision_id == plan.capacity_policy_revision_id
        calls["slot"] += 1

    def enqueue(*_args: object, **kwargs: object) -> tuple[object, bool]:
        assert kwargs["command_type"].value == "START_WORKFLOW"
        calls["enqueued"] += 1
        return SimpleNamespace(command_id="command_" + "c" * 32), True

    expected = _result(workflow.workflow_id)
    monkeypatch.setattr(
        "eom_catalog_service.legacy_item_extraction_service.transaction", fake_transaction
    )
    monkeypatch.setattr(service, "_validate_reviewed_pointers", validate_pointers)
    monkeypatch.setattr(
        "eom_catalog_service.legacy_item_extraction_service.create_workflow_instance",
        create_workflow,
    )
    monkeypatch.setattr(
        "eom_catalog_service.legacy_item_extraction_service.resolve_legacy_item_extraction_plan",
        resolve_plan,
    )
    monkeypatch.setattr(service, "_require_dedicated_slot", require_slot)
    monkeypatch.setattr(
        "eom_catalog_service.legacy_item_extraction_service.enqueue_command", enqueue
    )
    monkeypatch.setattr(service, "_projection", lambda *_args, **_kwargs: expected)

    actual = service.create(
        CreateLegacyItemExtractionCommand(
            request=request,
            idempotency_key="pilot-001",
            requested_by="operator-test",
        )
    )
    assert actual == expected
    assert calls == {"validated": 1, "resolved": 1, "slot": 1, "enqueued": 1}
    assert workflow.runtime_context["execution_plan"]["plan_id"] == plan.plan_id


def test_exact_replay_returns_existing_without_validation_resolution_or_enqueue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request()
    actor = "operator-test"
    submission_sha256 = content_sha256(
        {"request": request.model_dump(mode="json"), "requested_by": actor}
    )
    workflow = SimpleNamespace(
        workflow_id="workflow_" + "d" * 32,
        runtime_context={
            "legacy_item_extraction_submission_sha256": submission_sha256,
        },
        created_actor_id=actor,
    )
    session = _ScalarSession([workflow])
    service = _service(session)
    expected = _result(workflow.workflow_id)

    @contextmanager
    def fake_transaction(_sessions: object) -> Iterator[_ScalarSession]:
        yield session

    monkeypatch.setattr(
        "eom_catalog_service.legacy_item_extraction_service.transaction", fake_transaction
    )
    monkeypatch.setattr(service, "_projection", lambda *_args, **_kwargs: expected)
    monkeypatch.setattr(
        service,
        "_validate_reviewed_pointers",
        lambda *_args: pytest.fail("replay must not revalidate or create"),
    )
    monkeypatch.setattr(
        "eom_catalog_service.legacy_item_extraction_service.enqueue_command",
        lambda *_args, **_kwargs: pytest.fail("replay must not enqueue"),
    )

    assert (
        service.create(CreateLegacyItemExtractionCommand(request, "pilot-001", actor)) == expected
    )


def test_same_idempotency_key_with_different_actor_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request()
    workflow = SimpleNamespace(
        runtime_context={
            "legacy_item_extraction_submission_sha256": "sha256:" + "f" * 64,
        },
        created_actor_id="other-operator",
    )
    session = _ScalarSession([workflow])
    service = _service(session)

    @contextmanager
    def fake_transaction(_sessions: object) -> Iterator[_ScalarSession]:
        yield session

    monkeypatch.setattr(
        "eom_catalog_service.legacy_item_extraction_service.transaction", fake_transaction
    )
    with pytest.raises(LegacyItemExtractionServiceError) as captured:
        service.create(CreateLegacyItemExtractionCommand(request, "pilot-001", "operator-test"))
    assert captured.value.code == "LEGACY_ITEM_EXTRACTION_IDEMPOTENCY_CONFLICT"


def test_request_identity_cannot_be_rebound_to_a_second_idempotency_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request()
    session = _ScalarSession(
        [
            None,
            SimpleNamespace(workflow_id="workflow_" + "e" * 32),
        ]
    )
    service = _service(session)

    @contextmanager
    def fake_transaction(_sessions: object) -> Iterator[_ScalarSession]:
        yield session

    monkeypatch.setattr(
        "eom_catalog_service.legacy_item_extraction_service.transaction", fake_transaction
    )
    with pytest.raises(LegacyItemExtractionServiceError) as captured:
        service.create(CreateLegacyItemExtractionCommand(request, "different-key", "operator-test"))
    assert captured.value.code == "LEGACY_ITEM_EXTRACTION_IDENTITY_CONFLICT"


def test_duplicate_request_json_query_is_portable_between_supported_test_dialects() -> None:
    statement = LegacyItemExtractionApplicationService._duplicate_request_statement(
        "itemextractreq_" + "1" * 32
    )
    compile_options = {"literal_binds": True}
    postgres_sql = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs=compile_options,
        )
    )
    sqlite_sql = str(
        statement.compile(
            dialect=sqlite.dialect(),
            compile_kwargs=compile_options,
        )
    )
    assert "extraction_request_id" in postgres_sql
    assert "extraction_request_id" in sqlite_sql
    assert "FOR UPDATE" in postgres_sql
    assert "JSON_EXTRACT" in sqlite_sql


def test_missing_bundle_pointer_fails_before_any_plan_or_command() -> None:
    class MissingSession:
        @staticmethod
        def get(_model: object, _identity: object) -> None:
            return None

    service = _service(MissingSession())
    with pytest.raises(LegacyItemExtractionServiceError) as captured:
        service._validate_reviewed_pointers(cast(Any, MissingSession()), _request())
    assert captured.value.code == "LEGACY_ITEM_EXTRACTION_POINTER_STALE"


def test_stale_artifact_member_hash_fails_closed() -> None:
    pointer = _request().page_inputs[0].image
    artifact = SimpleNamespace(approved=True, job_id="job_" + "1" * 32)
    revision = SimpleNamespace(
        approved=True,
        job_id=artifact.job_id,
        logical_artifact_id=pointer.artifact_id,
        manifest={
            "files": [
                {
                    "file_name": pointer.member_path,
                    "sha256": "sha256:" + "f" * 64,
                    "media_type": pointer.media_type,
                    "schema_ref": pointer.schema_ref,
                    "bytes": 100,
                }
            ]
        },
    )
    job = SimpleNamespace(status="SUCCEEDED")

    class ArtifactSession:
        @staticmethod
        def get(model: object, _identity: object) -> object:
            name = cast(type[object], model).__name__
            return {"ArtifactRecord": artifact, "ArtifactRevisionRecord": revision}.get(name, job)

    service = _service(ArtifactSession())
    with pytest.raises(LegacyItemExtractionServiceError) as captured:
        service._require_artifact_member(cast(Any, ArtifactSession()), pointer)
    assert captured.value.code == "LEGACY_ITEM_EXTRACTION_POINTER_STALE"


def test_page_source_must_match_exact_reviewed_bundle_member_and_role() -> None:
    pointer = _request().page_inputs[0].source
    exact = {LegacyItemExtractionApplicationService._member_identity("PROBLEM_DOCUMENT", pointer)}
    LegacyItemExtractionApplicationService._require_reviewed_bundle_member(
        exact,
        role="PROBLEM_DOCUMENT",
        pointer=pointer,
    )
    with pytest.raises(LegacyItemExtractionServiceError) as captured:
        LegacyItemExtractionApplicationService._require_reviewed_bundle_member(
            exact,
            role="ANSWER_EXPLANATION_DOCUMENT",
            pointer=pointer,
        )
    assert captured.value.code == "LEGACY_ITEM_EXTRACTION_POINTER_STALE"


@pytest.mark.parametrize(
    ("slots", "passes"),
    [
        (("06",), True),
        (("05",), False),
        (("05", "06"), False),
        ((), False),
    ],
)
def test_capacity_contract_allows_only_slot06(slots: tuple[str, ...], passes: bool) -> None:
    class CapacitySession:
        @staticmethod
        def scalars(_query: object) -> tuple[str, ...]:
            return slots

    service = _service(CapacitySession())
    if passes:
        service._require_dedicated_slot(cast(Any, CapacitySession()), "capacityrev_" + "1" * 32)
    else:
        with pytest.raises(LegacyItemExtractionServiceError) as captured:
            service._require_dedicated_slot(cast(Any, CapacitySession()), "capacityrev_" + "1" * 32)
        assert captured.value.code == "LEGACY_ITEM_EXTRACTION_CAPACITY_INVALID"


def test_cli_exposes_create_and_pointer_only_inspection() -> None:
    runner = CliRunner()
    root = runner.invoke(app, ["legacy-assessment", "--help"])
    assert root.exit_code == 0
    assert "extraction" in root.stdout
    extraction = runner.invoke(app, ["legacy-assessment", "extraction", "--help"])
    assert extraction.exit_code == 0
    assert "create" in extraction.stdout
    assert "inspect" in extraction.stdout
