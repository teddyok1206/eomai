from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock, Mock, patch

import pytest
from eom_api.services.command_adapter import _workflow_request_from_api
from eom_api.services.mock_exam_production_coordinator import _workflow_request
from eom_api_contracts.mock_exam_execution import MockExamGenerationBlockResolutionV1
from eom_catalog_contracts.approved_item_graph_publication import (
    ApprovedItemGraphPublicationResult,
    PublishApprovedItemAnalysesCommand,
)
from eom_catalog_contracts.assessment_assembly import (
    load_integrated_science_mock_exam_layout_policy,
    load_integrated_science_mock_exam_policy,
)
from eom_catalog_contracts.curriculum import load_integrated_science_editorial_outline
from eom_catalog_contracts.knowledge import (
    ApprovedItemKnowledgeSourceV2,
    ApprovedPastExamItemKnowledgeSourceV3,
    KnowledgeAnalysisRequestV9,
    KnowledgeArtifactMemberPointer,
    KnowledgeGraphCounts,
    KnowledgeGraphPublicationResult,
    KnowledgeGraphSnapshotPointer,
)
from eom_catalog_contracts.mock_exam_production_plan import (
    build_integrated_science_mock_exam_production_plan,
)
from eom_catalog_service.approved_item_graph_publication_service import (
    ApprovedItemGraphPublicationError,
    ApprovedItemGraphPublicationService,
)
from eom_catalog_service.automatic_item_graph_publication_service import (
    AutomaticItemGraphCandidate,
    AutomaticItemGraphPublicationService,
)
from eom_catalog_service.curriculum_graph_structure import integrated_science_curriculum_units
from eom_catalog_service.knowledge_graph_projection import AcceptedAnalysisProposal
from eom_catalog_service.knowledge_graph_publication_service import (
    CurrentKnowledgeGraphStructure,
    KnowledgeGraphPublicationError,
    KnowledgeGraphPublicationService,
)
from eom_identifiers import content_sha256
from eom_workflow_runner.repository import (
    load_persisted_workflow_request,
    workflow_business_fingerprint,
)
from jsonschema import Draft202012Validator, FormatChecker
from sqlalchemy.orm import Session

GRAPH_REVISION_ID = "graphrev_" + "1" * 32
NEW_GRAPH_REVISION_ID = "graphrev_" + "2" * 32
ANALYSIS_RUN_IDS = tuple("analysisrun_" + f"{100 + value:032x}" for value in range(25))
ANALYSIS_RUN_ID = ANALYSIS_RUN_IDS[0]
ITEM_IDS = tuple("item_" + f"{400 + value:032x}" for value in range(25))
ITEM_ID = ITEM_IDS[0]
ITEM_REVISION_IDS = tuple("itemrev_" + f"{200 + value:032x}" for value in range(25))
ITEM_REVISION_ID = ITEM_REVISION_IDS[0]
WORKFLOW_IDS = tuple("workflow_" + f"{300 + value:032x}" for value in range(25))
OPERATOR_ID = "operator_" + "6" * 32
ACCESS_POLICY_REVISION_ID = "accessrev_" + "7" * 32
ACCESS_POLICY_SHA256 = "sha256:" + "7" * 64
MANIFEST_SHA256 = "sha256:" + "8" * 64
SNAPSHOT_SHA256 = "sha256:" + "9" * 64
PUBLISHED_AT = datetime(2026, 9, 8, 8, 0, tzinfo=UTC)
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _command_value(
    *,
    analysis_ids: tuple[str, ...] = ANALYSIS_RUN_IDS,
    workflow_ids: tuple[str, ...] = WORKFLOW_IDS,
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "operation": "PUBLISH_APPROVED_ITEM_ANALYSES",
        "schema_version": "approved-item-graph-publication-command/1.0",
        "corpus_key": "integrated-science-textbooks",
        "expected_current_graph_snapshot_revision_id": GRAPH_REVISION_ID,
        "expected_current_graph_snapshot_sha256": SNAPSHOT_SHA256,
        "accepted_analysis_run_ids": list(analysis_ids),
        "expected_workflow_ids": list(workflow_ids),
        "access_policy_revision_id": ACCESS_POLICY_REVISION_ID,
        "access_policy_sha256": ACCESS_POLICY_SHA256,
        "requested_by_operator_id": OPERATOR_ID,
        "authorized_at": PUBLISHED_AT.isoformat().replace("+00:00", "Z"),
        "idempotency_key": "sample-exam-generated-items-01",
        "submission_sha256": "sha256:" + "0" * 64,
    }
    value["submission_sha256"] = content_sha256(
        {
            key: item
            for key, item in value.items()
            if key not in {"idempotency_key", "submission_sha256"}
        }
    )
    return value


def _command(
    *,
    analysis_ids: tuple[str, ...] = ANALYSIS_RUN_IDS,
    workflow_ids: tuple[str, ...] = WORKFLOW_IDS,
) -> PublishApprovedItemAnalysesCommand:
    return PublishApprovedItemAnalysesCommand.model_validate(
        _command_value(analysis_ids=analysis_ids, workflow_ids=workflow_ids)
    )


def _graph_publication_result() -> KnowledgeGraphPublicationResult:
    manifest_pointer = KnowledgeArtifactMemberPointer(
        artifact_id="artifact_" + "a" * 32,
        artifact_revision_id="rev_" + "b" * 32,
        sha256=MANIFEST_SHA256,
        schema_ref="eom://schemas/knowledge/knowledge-graph-snapshot-manifest/8.0",
        media_type="application/json",
        logical_name="manifest.json",
        member_path="projections/manifest.json",
    )
    graph_pointer = KnowledgeGraphSnapshotPointer(
        graph_id="graph_" + "c" * 32,
        graph_snapshot_revision_id=NEW_GRAPH_REVISION_ID,
        manifest_artifact=manifest_pointer,
        manifest_sha256=MANIFEST_SHA256,
    )
    value: dict[str, Any] = {
        "schema_version": "knowledge-graph-publication-result/1.0",
        "publication_id": "graphpub_" + "d" * 32,
        "corpus_id": "corpus_" + "e" * 32,
        "corpus_key": "integrated-science-textbooks",
        "corpus_revision_id": "corpusrev_" + "f" * 32,
        "graph_snapshot": graph_pointer.model_dump(mode="json"),
        "revision_number": 48,
        "state": "PUBLISHED",
        "counts": KnowledgeGraphCounts(
            source_revisions=2,
            nodes=3,
            edges=1,
            anchors=2,
        ).model_dump(mode="json"),
        "request_sha256": "sha256:" + "1" * 64,
        "published_at": PUBLISHED_AT.isoformat().replace("+00:00", "Z"),
        "result_sha256": "sha256:" + "0" * 64,
    }
    value["result_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "result_sha256"}
    )
    return KnowledgeGraphPublicationResult.model_validate(value)


def _accepted_analysis(position: int = 0) -> AcceptedAnalysisProposal:
    source = ApprovedItemKnowledgeSourceV2.model_construct(
        source_class="APPROVED_ITEM",
        item_id=ITEM_IDS[position],
        item_revision_id=ITEM_REVISION_IDS[position],
        lifecycle_state="APPROVED",
        artifact_member=SimpleNamespace(schema_ref="eom.assessment.item-content/2.0"),
    )
    return AcceptedAnalysisProposal(
        analysis_run_id=ANALYSIS_RUN_IDS[position],
        source=source,
        accepted_result=cast(
            Any,
            SimpleNamespace(schema_ref="eom://schemas/knowledge/knowledge-analysis-result/2.0"),
        ),
        proposal=cast(Any, SimpleNamespace(nodes=())),
    )


def _origin_rows(*, stale_position: int | None = None) -> tuple[tuple[Any, ...], ...]:
    plan = build_integrated_science_mock_exam_production_plan(
        policy=load_integrated_science_mock_exam_policy(),
        layout_policy=load_integrated_science_mock_exam_layout_policy(),
        outline=load_integrated_science_editorial_outline(),
    )
    definition_document = {"schema_version": "1.0", "test": "atomic-25"}
    definition_sha256 = content_sha256(definition_document)
    resolution = MockExamGenerationBlockResolutionV1(
        generation_block_key=plan.one_item_generation_block.block_key,
        generation_block_revision=plan.one_item_generation_block.block_revision,
        generation_block_sha256=plan.one_item_generation_block.block_sha256,
        workflow_definition_key="generic-item-development",
        workflow_definition_version="1.8.0",
        workflow_definition_sha256=definition_sha256,
        content_pack_release_id="packrel_" + "a" * 32,
        content_pack_key="generated-knowledge-item",
        content_pack_version="1.13.0",
        content_pack_release_sha256="sha256:" + "b" * 64,
        content_pack_source_tree_sha256=(
            plan.one_item_generation_block.content_pack_source_tree_sha256
        ),
        execution_preset_id="execpreset_" + "c" * 32,
        execution_preset_revision_id="execpresetrev_" + "d" * 32,
        execution_preset_key="knowledge-grounded-item",
        execution_preset_sha256="sha256:" + "e" * 64,
        resolved_at=PUBLISHED_AT,
    )
    rows: list[tuple[Any, ...]] = []
    for index, call in enumerate(plan.workflow_calls):
        request = _workflow_request_from_api(
            _workflow_request(
                call,
                plan.one_item_generation_block,
                resolution,
                "productionreq_" + "f" * 32,
            )
        )
        request_document = request.model_dump(mode="json")
        revision = SimpleNamespace(
            item_id=ITEM_IDS[index],
            workflow_id=WORKFLOW_IDS[index],
            revision_number=1,
            workflow_definition_version="1.8.0",
            content_pack_release_id=resolution.content_pack_release_id,
            revision_state="APPROVED",
        )
        item = SimpleNamespace(
            lifecycle_state="ACTIVE",
            current_revision_id=(
                "itemrev_" + "f" * 32 if stale_position == index else ITEM_REVISION_IDS[index]
            ),
        )
        run = SimpleNamespace(
            analysis_run_id=ANALYSIS_RUN_IDS[index],
            state="ACCEPTED",
            source_kind="APPROVED_ITEM_REVISION",
            canonical_request={
                "schema_version": "knowledge-analysis-request/2.0",
                "source": {"source_class": "APPROVED_ITEM"},
            },
            item_id=ITEM_IDS[index],
            item_revision_id=ITEM_REVISION_IDS[index],
            workflow_id=WORKFLOW_IDS[index],
        )
        definition = SimpleNamespace(
            definition_id="workflowdef_" + "1" * 32,
            definition_key="generic-item-development",
            definition_version="1.8.0",
            definition_hash=definition_sha256,
            canonical_definition=definition_document,
            active=False,
        )
        workflow = SimpleNamespace(
            workflow_id=WORKFLOW_IDS[index],
            definition_id=definition.definition_id,
            definition_key="generic-item-development",
            definition_version="1.8.0",
            definition_hash=definition_sha256,
            role_schema_version="workflow-role/1.17.0",
            state="COMPLETED",
            stage="COMPLETED",
            current_step_key="complete",
            completed_at=PUBLISHED_AT,
            request_payload=request_document,
            initial_request=request_document,
            request_hash=workflow_business_fingerprint(cast(Any, definition), request),
            runtime_context={
                "accepted_resolution": request.expected_resolution.model_dump(mode="json"),
                "item_registration": {
                    "item_id": ITEM_IDS[index],
                    "item_revision_id": ITEM_REVISION_IDS[index],
                    "revision_number": 1,
                },
            },
        )
        rows.append((run, revision, item, workflow, definition))
    return tuple(rows)


@pytest.mark.parametrize(
    "name",
    (
        "approved-item-graph-publication-command-v1.schema.json",
        "approved-item-graph-publication-result-v1.schema.json",
    ),
)
def test_protocol_schemas_are_draft_2020_12_and_package_exact(name: str) -> None:
    canonical = REPOSITORY_ROOT / "schemas" / "knowledge" / name
    packaged = (
        REPOSITORY_ROOT
        / "packages/catalog_contracts/eom_catalog_contracts/resources/knowledge"
        / name
    )
    assert canonical.read_bytes() == packaged.read_bytes()
    schema = json.loads(canonical.read_bytes())
    Draft202012Validator.check_schema(schema)


def test_command_schema_validates_the_closed_pydantic_message() -> None:
    schema = json.loads(
        (
            REPOSITORY_ROOT
            / "schemas/knowledge/approved-item-graph-publication-command-v1.schema.json"
        ).read_bytes()
    )
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(
        _command().model_dump(mode="json")
    )


def test_command_preserves_exact_order_and_rejects_duplicates_or_hash_drift() -> None:
    reordered = (ANALYSIS_RUN_IDS[1], ANALYSIS_RUN_IDS[0], *ANALYSIS_RUN_IDS[2:])
    command = _command(analysis_ids=reordered)

    assert command.accepted_analysis_run_ids == reordered

    duplicate = _command_value(analysis_ids=(*ANALYSIS_RUN_IDS[:-1], ANALYSIS_RUN_IDS[0]))
    with pytest.raises(ValueError, match="unique and ordered"):
        PublishApprovedItemAnalysesCommand.model_validate(duplicate)

    changed = _command_value()
    changed["access_policy_revision_id"] = "accessrev_" + "f" * 32
    with pytest.raises(ValueError, match="submission hash"):
        PublishApprovedItemAnalysesCommand.model_validate(changed)


def test_result_carries_distinct_snapshot_and_manifest_hashes() -> None:
    command = _command()
    graph_result = _graph_publication_result()
    value: dict[str, Any] = {
        "schema_version": "approved-item-graph-publication-result/1.0",
        "publication_id": graph_result.publication_id,
        "corpus_key": graph_result.corpus_key,
        "previous_graph_snapshot_revision_id": GRAPH_REVISION_ID,
        "previous_graph_snapshot_sha256": SNAPSHOT_SHA256,
        "graph_snapshot": graph_result.graph_snapshot.model_dump(mode="json"),
        "graph_snapshot_sha256": SNAPSHOT_SHA256,
        "revision_number": graph_result.revision_number,
        "accepted_analysis_run_ids": list(command.accepted_analysis_run_ids),
        "expected_workflow_ids": list(command.expected_workflow_ids),
        "item_revision_ids": list(ITEM_REVISION_IDS),
        "authorized_at": command.authorized_at.isoformat().replace("+00:00", "Z"),
        "outcome": "CREATED",
        "published_at": PUBLISHED_AT.isoformat().replace("+00:00", "Z"),
        "result_sha256": "sha256:" + "0" * 64,
    }
    value["result_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "result_sha256"}
    )

    result = ApprovedItemGraphPublicationResult.model_validate(value)

    assert result.graph_snapshot_sha256 == SNAPSHOT_SHA256
    assert result.graph_snapshot.manifest_sha256 == MANIFEST_SHA256
    assert result.graph_snapshot.graph_snapshot_revision_id == NEW_GRAPH_REVISION_ID


def test_shared_publisher_rejects_existing_membership_before_any_artifact_write() -> None:
    publication = Mock()
    publication.current_structure_context.return_value = CurrentKnowledgeGraphStructure(
        corpus_key="integrated-science-textbooks",
        display_name="통합과학 지식 그래프",
        graph_snapshot_revision_id=GRAPH_REVISION_ID,
        accepted_analysis_run_ids=(ANALYSIS_RUN_ID,),
        structure=cast(Any, object()),
    )
    service = object.__new__(AutomaticItemGraphPublicationService)
    service.publication = publication

    with pytest.raises(ValueError, match="already belongs"):
        service.publish(
            (
                AutomaticItemGraphCandidate(
                    analysis_run_id=ANALYSIS_RUN_ID,
                    requested_by_operator_id=OPERATOR_ID,
                    graph_snapshot_revision_id=GRAPH_REVISION_ID,
                ),
            ),
            required_source_class="APPROVED_ITEM",
            retrieval_idempotency_namespace="approved-item-auto-alignment",
            publication_idempotency_namespace="approved-item-auto-graph",
            publisher_version="1.7.0",
        )

    publication.sessions.assert_not_called()
    publication.commit_structure_manifest.assert_not_called()
    publication.publish.assert_not_called()


def test_shared_publisher_reports_stale_current_before_retrieval_or_artifact_write() -> None:
    publication = Mock()
    publication.current_structure_context.return_value = CurrentKnowledgeGraphStructure(
        corpus_key="integrated-science-textbooks",
        display_name="통합과학 지식 그래프",
        graph_snapshot_revision_id=NEW_GRAPH_REVISION_ID,
        accepted_analysis_run_ids=(),
        structure=cast(Any, object()),
    )
    service = object.__new__(AutomaticItemGraphPublicationService)
    service.publication = publication
    service.retrieval = Mock()

    with pytest.raises(KnowledgeGraphPublicationError) as caught:
        service.publish(
            (
                AutomaticItemGraphCandidate(
                    analysis_run_id=ANALYSIS_RUN_ID,
                    requested_by_operator_id=OPERATOR_ID,
                    graph_snapshot_revision_id=GRAPH_REVISION_ID,
                ),
            ),
            required_source_class="APPROVED_ITEM",
            retrieval_idempotency_namespace="approved-item-auto-alignment",
            publication_idempotency_namespace="approved-item-auto-graph",
            publisher_version="1.7.0",
        )

    assert caught.value.code == "KNOWLEDGE_GRAPH_STALE_CURRENT"
    service.retrieval.create.assert_not_called()
    publication.sessions.assert_not_called()
    publication.commit_structure_manifest.assert_not_called()
    publication.publish.assert_not_called()


def test_shared_publisher_forbids_occurrence_builder_for_generated_items() -> None:
    analysis = _accepted_analysis()
    publication = Mock()
    publication.current_structure_context.return_value = CurrentKnowledgeGraphStructure(
        corpus_key="integrated-science-textbooks",
        display_name="통합과학 지식 그래프",
        graph_snapshot_revision_id=GRAPH_REVISION_ID,
        accepted_analysis_run_ids=(),
        structure=cast(Any, object()),
    )
    session = Mock(spec=Session)
    context = Mock()
    context.__enter__ = Mock(return_value=session)
    context.__exit__ = Mock(return_value=False)
    publication.sessions.return_value = context
    publication._load_accepted_analysis.return_value = analysis
    service = object.__new__(AutomaticItemGraphPublicationService)
    service.publication = publication

    with pytest.raises(ValueError, match="cannot add exam occurrences"):
        service.publish(
            (
                AutomaticItemGraphCandidate(
                    analysis_run_id=ANALYSIS_RUN_ID,
                    requested_by_operator_id=OPERATOR_ID,
                    graph_snapshot_revision_id=GRAPH_REVISION_ID,
                ),
            ),
            required_source_class="APPROVED_ITEM",
            retrieval_idempotency_namespace="approved-item-auto-alignment",
            publication_idempotency_namespace="approved-item-auto-graph",
            publisher_version="1.7.0",
            occurrence_binding_resolver=cast(Any, lambda *_args: ()),
        )

    publication.commit_structure_manifest.assert_not_called()


def test_shared_analysis_validator_fails_before_retrieval_create() -> None:
    analysis = _accepted_analysis()
    publication = Mock()
    publication.current_structure_context.return_value = CurrentKnowledgeGraphStructure(
        corpus_key="integrated-science-textbooks",
        display_name="통합과학 지식 그래프",
        graph_snapshot_revision_id=GRAPH_REVISION_ID,
        accepted_analysis_run_ids=(),
        structure=cast(Any, object()),
    )
    load_context = MagicMock()
    load_context.__enter__.return_value = Mock(spec=Session)
    publication.sessions.return_value = load_context
    publication._load_accepted_analysis.return_value = analysis
    validation_context = MagicMock()
    validation_context.__enter__.return_value = Mock(spec=Session)
    service = object.__new__(AutomaticItemGraphPublicationService)
    service.publication = publication
    service.sessions = Mock(return_value=validation_context)
    service.retrieval = Mock()

    def reject_origin(_session: Session, _analyses: tuple[AcceptedAnalysisProposal, ...]) -> None:
        raise ValueError("invalid origin")

    with pytest.raises(ValueError, match="invalid origin"):
        service.publish(
            (
                AutomaticItemGraphCandidate(
                    analysis_run_id=ANALYSIS_RUN_ID,
                    requested_by_operator_id=OPERATOR_ID,
                    graph_snapshot_revision_id=GRAPH_REVISION_ID,
                ),
            ),
            required_source_class="APPROVED_ITEM",
            retrieval_idempotency_namespace="approved-item-auto-alignment",
            publication_idempotency_namespace="approved-item-auto-graph",
            publisher_version="1.7.0",
            analysis_validator=reject_origin,
        )

    service.retrieval.create.assert_not_called()
    publication.commit_structure_manifest.assert_not_called()
    publication.publish.assert_not_called()


@pytest.mark.parametrize("field", ("source_revision_id", "item_id", "item_revision_id"))
def test_load_accepted_analysis_rejects_persisted_item_source_identity_drift(
    field: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact_member = SimpleNamespace(
        artifact_id="artifact_" + "1" * 32,
        artifact_revision_id="rev_" + "2" * 32,
        sha256="sha256:" + "3" * 64,
    )
    source = ApprovedPastExamItemKnowledgeSourceV3.model_construct(
        item_id=ITEM_ID,
        item_revision_id=ITEM_REVISION_ID,
        artifact_member=artifact_member,
    )
    request = SimpleNamespace(
        source=source,
        request_sha256="sha256:" + "4" * 64,
    )
    monkeypatch.setattr(
        KnowledgeAnalysisRequestV9,
        "model_validate",
        classmethod(lambda _cls, _value: request),
    )
    run = SimpleNamespace(
        state="ACCEPTED",
        accepted_result_artifact_id="artifact_" + "5" * 32,
        accepted_result_artifact_revision_id="rev_" + "6" * 32,
        accepted_result_sha256="sha256:" + "7" * 64,
        proposal_artifact_id="artifact_" + "8" * 32,
        proposal_artifact_revision_id="rev_" + "9" * 32,
        proposal_content_set_sha256="sha256:" + "a" * 64,
        canonical_request={"schema_version": "knowledge-analysis-request/9.0"},
        request_sha256=request.request_sha256,
        source_kind="APPROVED_ITEM_REVISION",
        source_revision_id=ITEM_REVISION_ID,
        source_file_id=None,
        item_id=ITEM_ID,
        item_revision_id=ITEM_REVISION_ID,
        educational_document_id=None,
        educational_document_revision_id=None,
        source_artifact_id=artifact_member.artifact_id,
        source_artifact_revision_id=artifact_member.artifact_revision_id,
        source_sha256=artifact_member.sha256,
    )
    setattr(run, field, "wrong")
    session = Mock(spec=Session)
    session.get.return_value = run
    service = object.__new__(KnowledgeGraphPublicationService)
    service._resolve_source_again = Mock(return_value=source)  # type: ignore[method-assign]
    service._exact_artifact_revision = Mock()  # type: ignore[method-assign]

    with pytest.raises(KnowledgeGraphPublicationError) as caught:
        service._load_accepted_analysis(session, ANALYSIS_RUN_ID)

    assert caught.value.code == "KNOWLEDGE_GRAPH_SOURCE_POINTER_INVALID"
    service._exact_artifact_revision.assert_not_called()


def test_current_v2_validator_rejects_a_stale_current_revision() -> None:
    session = Mock(spec=Session)
    session.execute.return_value = _origin_rows(stale_position=0)

    with pytest.raises(ValueError, match="fresh completed"):
        ApprovedItemGraphPublicationService._validate_current_v2_item_analyses(
            session,
            tuple(_accepted_analysis(value) for value in range(25)),
            WORKFLOW_IDS,
        )


def test_publication_input_resolves_exact_graph_and_access_policy_hashes() -> None:
    session = Mock(spec=Session)
    session.get.side_effect = [
        SimpleNamespace(
            state="PUBLISHED",
            snapshot_sha256=SNAPSHOT_SHA256,
            graph_id="graph_" + "1" * 32,
        ),
        SimpleNamespace(state="RELEASED", content_sha256=ACCESS_POLICY_SHA256),
    ]
    session.scalar.return_value = SimpleNamespace(
        lifecycle_state="ACTIVE",
        graph_id="graph_" + "1" * 32,
        current_graph_snapshot_revision_id=GRAPH_REVISION_ID,
    )
    context = Mock()
    context.__enter__ = Mock(return_value=session)
    context.__exit__ = Mock(return_value=False)
    service = object.__new__(ApprovedItemGraphPublicationService)
    service.sessions = Mock(return_value=context)

    service._validate_input_pointers(_command())

    session.get.side_effect = [
        SimpleNamespace(state="PUBLISHED", snapshot_sha256="sha256:" + "0" * 64),
        SimpleNamespace(state="RELEASED", content_sha256=ACCESS_POLICY_SHA256),
    ]
    with pytest.raises(ApprovedItemGraphPublicationError) as caught:
        service._validate_input_pointers(_command())
    assert caught.value.code == "APPROVED_ITEM_GRAPH_BASE_POINTER_INVALID"


def test_publication_input_reports_authorized_base_superseded_by_current() -> None:
    session = Mock(spec=Session)
    session.get.side_effect = [
        SimpleNamespace(
            state="PUBLISHED",
            snapshot_sha256=SNAPSHOT_SHA256,
            graph_id="graph_" + "1" * 32,
        ),
        SimpleNamespace(state="RELEASED", content_sha256=ACCESS_POLICY_SHA256),
    ]
    session.scalar.return_value = SimpleNamespace(
        lifecycle_state="ACTIVE",
        graph_id="graph_" + "1" * 32,
        current_graph_snapshot_revision_id=NEW_GRAPH_REVISION_ID,
    )
    context = Mock()
    context.__enter__ = Mock(return_value=session)
    context.__exit__ = Mock(return_value=False)
    service = object.__new__(ApprovedItemGraphPublicationService)
    service.sessions = Mock(return_value=context)

    with pytest.raises(ApprovedItemGraphPublicationError) as caught:
        service._validate_input_pointers(_command())

    assert caught.value.code == "KNOWLEDGE_GRAPH_STALE_CURRENT"


def test_exact_replay_precedes_mutable_current_admission() -> None:
    command = _command()
    expected = cast(Any, SimpleNamespace(outcome="REPLAYED"))
    service = cast(Any, object.__new__(ApprovedItemGraphPublicationService))
    service._existing_publication = Mock(return_value=expected)
    service._validate_input_pointers = Mock(
        side_effect=AssertionError("replay must not resolve mutable current state")
    )

    with patch("eom_catalog_service.approved_item_graph_publication_service.validate_contract"):
        result = service.publish(command)

    assert result is expected
    service._validate_input_pointers.assert_not_called()


def test_late_publication_race_preserves_stable_stale_current_code() -> None:
    command = _command()
    service = cast(Any, object.__new__(ApprovedItemGraphPublicationService))
    service.engine = Mock()
    service.publication = Mock()
    service.retrieval = Mock()
    service._existing_publication = Mock(return_value=None)
    service._validate_input_pointers = Mock()
    service._validate_official_review_eligibility = Mock()

    with (
        patch(
            "eom_catalog_service.approved_item_graph_publication_service."
            "AutomaticItemGraphPublicationService"
        ) as automatic_type,
        pytest.raises(ApprovedItemGraphPublicationError) as caught,
    ):
        automatic_type.return_value.publish.side_effect = KnowledgeGraphPublicationError(
            "KNOWLEDGE_GRAPH_STALE_CURRENT",
            "concurrent publisher advanced current",
        )
        service.publish(command)

    assert caught.value.code == "KNOWLEDGE_GRAPH_STALE_CURRENT"


def test_current_v2_validator_accepts_deactivated_definition_for_pinned_origin() -> None:
    session = Mock(spec=Session)
    session.execute.return_value = _origin_rows()

    ApprovedItemGraphPublicationService._validate_current_v2_item_analyses(
        session,
        tuple(_accepted_analysis(value) for value in range(25)),
        WORKFLOW_IDS,
    )


def test_direct_graph_publication_rejects_unapproved_operator_before_side_effect() -> None:
    command = _command()

    class WrongOperatorEligibility:
        def __init__(self) -> None:
            self.queries: tuple[Any, ...] = ()

        def inspect_eligibility_batch(self, queries: tuple[Any, ...]) -> tuple[Any, ...]:
            self.queries = queries
            return tuple(
                SimpleNamespace(
                    workflow_id=query.workflow_id,
                    approval_state="APPROVED",
                    eligible=True,
                    finding_counts=SimpleNamespace(blocking=0),
                    reviewer_operator_id="operator_" + "f" * 32,
                    approved_at=PUBLISHED_AT,
                )
                for query in queries
            )

    eligibility = WrongOperatorEligibility()
    service = cast(Any, object.__new__(ApprovedItemGraphPublicationService))
    service.review_eligibility = eligibility
    service._validate_input_pointers = Mock()
    service._existing_publication = Mock(return_value=None)

    with (
        patch(
            "eom_catalog_service.approved_item_graph_publication_service."
            "AutomaticItemGraphPublicationService"
        ) as automatic,
        pytest.raises(ApprovedItemGraphPublicationError) as caught,
    ):
        service.publish(command)

    assert caught.value.code == "APPROVED_ITEM_GRAPH_REVIEW_INELIGIBLE"
    assert tuple(row.workflow_id for row in eligibility.queries) == WORKFLOW_IDS
    automatic.assert_not_called()


def test_direct_graph_publication_rejects_blocking_review_before_side_effect() -> None:
    command = _command()

    class BlockingEligibility:
        def inspect_eligibility_batch(self, queries: tuple[Any, ...]) -> tuple[Any, ...]:
            return tuple(
                SimpleNamespace(
                    workflow_id=query.workflow_id,
                    approval_state="APPROVED",
                    eligible=index != 0,
                    finding_counts=SimpleNamespace(blocking=1 if index == 0 else 0),
                    reviewer_operator_id=OPERATOR_ID,
                    approved_at=PUBLISHED_AT,
                )
                for index, query in enumerate(queries)
            )

    service = cast(Any, object.__new__(ApprovedItemGraphPublicationService))
    service.review_eligibility = BlockingEligibility()
    service._validate_input_pointers = Mock()
    service._existing_publication = Mock(return_value=None)

    with (
        patch(
            "eom_catalog_service.approved_item_graph_publication_service."
            "AutomaticItemGraphPublicationService"
        ) as automatic,
        pytest.raises(ApprovedItemGraphPublicationError) as caught,
    ):
        service.publish(command)

    assert caught.value.code == "APPROVED_ITEM_GRAPH_REVIEW_INELIGIBLE"
    automatic.assert_not_called()


def test_graph_authorization_cannot_predate_human_approval() -> None:
    command = _command()

    class FutureApprovalEligibility:
        def inspect_eligibility_batch(self, queries: tuple[Any, ...]) -> tuple[Any, ...]:
            return tuple(
                SimpleNamespace(
                    workflow_id=query.workflow_id,
                    approval_state="APPROVED",
                    eligible=True,
                    finding_counts=SimpleNamespace(blocking=0),
                    reviewer_operator_id=OPERATOR_ID,
                    approved_at=PUBLISHED_AT + timedelta(seconds=1),
                )
                for query in queries
            )

    service = cast(Any, object.__new__(ApprovedItemGraphPublicationService))
    service.review_eligibility = FutureApprovalEligibility()
    service._validate_input_pointers = Mock()
    service._existing_publication = Mock(return_value=None)

    with (
        patch(
            "eom_catalog_service.approved_item_graph_publication_service."
            "AutomaticItemGraphPublicationService"
        ) as automatic,
        pytest.raises(ApprovedItemGraphPublicationError) as caught,
    ):
        service.publish(command)

    assert caught.value.code == "APPROVED_ITEM_GRAPH_REVIEW_INELIGIBLE"
    automatic.assert_not_called()


def test_alignment_must_include_each_originating_mock_exam_slot_unit() -> None:
    session = Mock(spec=Session)
    session.execute.return_value = _origin_rows()
    unit_keys = ApprovedItemGraphPublicationService._validate_current_v2_item_analyses(
        session,
        tuple(_accepted_analysis(value) for value in range(25)),
        WORKFLOW_IDS,
    )
    unit_id_by_key = {
        row.unit_key: row.curriculum_unit_id for row in integrated_science_curriculum_units()
    }
    alignments = tuple(
        SimpleNamespace(
            analysis_run_id=analysis_run_id,
            curriculum_unit_ids=(unit_id_by_key[unit_key],),
        )
        for analysis_run_id, unit_key in zip(ANALYSIS_RUN_IDS, unit_keys, strict=True)
    )
    ApprovedItemGraphPublicationService._validate_slot_unit_alignments(
        ANALYSIS_RUN_IDS,
        unit_keys,
        cast(Any, alignments),
    )

    wrong_unit_id = next(
        unit_id for unit_key, unit_id in unit_id_by_key.items() if unit_key != unit_keys[0]
    )
    wrong = (
        SimpleNamespace(
            analysis_run_id=ANALYSIS_RUN_IDS[0],
            curriculum_unit_ids=(wrong_unit_id,),
        ),
        *alignments[1:],
    )
    with pytest.raises(ValueError, match="originating mock-exam slot unit"):
        ApprovedItemGraphPublicationService._validate_slot_unit_alignments(
            ANALYSIS_RUN_IDS,
            unit_keys,
            cast(Any, wrong),
        )


def test_current_v2_validator_requires_aligned_origin_workflows_and_create_revision_one() -> None:
    analyses = tuple(_accepted_analysis(value) for value in range(25))
    session = Mock(spec=Session)
    session.execute.return_value = _origin_rows()
    with pytest.raises(ValueError, match="fresh completed"):
        ApprovedItemGraphPublicationService._validate_current_v2_item_analyses(
            session,
            analyses,
            (WORKFLOW_IDS[1], WORKFLOW_IDS[0], *WORKFLOW_IDS[2:]),
        )

    rows = list(_origin_rows())
    rows[0][1].revision_number = 2
    session.execute.return_value = tuple(rows)
    with pytest.raises(ValueError, match="CREATE_ITEM Workflow"):
        ApprovedItemGraphPublicationService._validate_current_v2_item_analyses(
            session,
            analyses,
            WORKFLOW_IDS,
        )


def test_current_v2_validator_requires_one_production_request_and_unique_calls() -> None:
    rows = list(_origin_rows())
    first_request = rows[0][3].initial_request
    second_workflow = rows[1][3]
    changed = deepcopy(second_workflow.initial_request)
    changed["production_occurrence"]["workflow_call_id"] = first_request["production_occurrence"][
        "workflow_call_id"
    ]
    second_workflow.initial_request = changed
    second_workflow.request_payload = changed
    second_workflow.request_hash = workflow_business_fingerprint(
        cast(Any, rows[1][4]),
        load_persisted_workflow_request(changed),
    )
    session = Mock(spec=Session)
    session.execute.return_value = tuple(rows)

    with pytest.raises(ValueError, match="25 ordered unique CREATE_ITEM calls"):
        ApprovedItemGraphPublicationService._validate_current_v2_item_analyses(
            session,
            tuple(_accepted_analysis(value) for value in range(25)),
            WORKFLOW_IDS,
        )


def test_exact_replay_returns_original_snapshot_without_republication() -> None:
    command = _command()
    publication_row = SimpleNamespace(
        graph_snapshot_revision_id=NEW_GRAPH_REVISION_ID,
        published_by_operator_id=OPERATOR_ID,
        authorized_at=PUBLISHED_AT,
    )
    snapshot = SimpleNamespace(
        graph_snapshot_revision_id=NEW_GRAPH_REVISION_ID,
        previous_graph_snapshot_revision_id=GRAPH_REVISION_ID,
        snapshot_sha256=SNAPSHOT_SHA256,
    )
    retrievals = tuple(
        SimpleNamespace(
            idempotency_key=(f"approved-item-auto-alignment:{analysis_run_id}:{GRAPH_REVISION_ID}"),
            access_policy_revision_id=ACCESS_POLICY_REVISION_ID,
            graph_snapshot_revision_id=GRAPH_REVISION_ID,
            requester_operator_id=OPERATOR_ID,
            state="PUBLISHED",
        )
        for analysis_run_id in ANALYSIS_RUN_IDS
    )
    session = Mock(spec=Session)
    session.scalar.return_value = publication_row
    session.get.return_value = snapshot
    session.scalars.side_effect = [(), ANALYSIS_RUN_IDS, retrievals]
    session.execute.return_value = tuple(
        zip(ANALYSIS_RUN_IDS, ITEM_REVISION_IDS, WORKFLOW_IDS, strict=True)
    )
    context = Mock()
    context.__enter__ = Mock(return_value=session)
    context.__exit__ = Mock(return_value=False)
    service = object.__new__(ApprovedItemGraphPublicationService)
    service.sessions = Mock(return_value=context)
    graph_result = _graph_publication_result()

    with (
        patch.object(KnowledgeGraphPublicationService, "_result", return_value=graph_result),
        patch("eom_catalog_service.approved_item_graph_publication_service.validate_contract"),
    ):
        result = service._existing_publication(
            command,
            service._publication_idempotency_key(command),
        )

    assert result is not None
    assert result.outcome == "REPLAYED"
    assert result.graph_snapshot.graph_snapshot_revision_id == NEW_GRAPH_REVISION_ID
    assert result.item_revision_ids == ITEM_REVISION_IDS
    assert result.expected_workflow_ids == WORKFLOW_IDS
    assert result.authorized_at == PUBLISHED_AT


def test_replay_rejects_membership_that_is_not_the_exact_requested_addition() -> None:
    command = _command()
    publication_row = SimpleNamespace(
        graph_snapshot_revision_id=NEW_GRAPH_REVISION_ID,
        published_by_operator_id=OPERATOR_ID,
        authorized_at=PUBLISHED_AT,
    )
    snapshot = SimpleNamespace(
        graph_snapshot_revision_id=NEW_GRAPH_REVISION_ID,
        previous_graph_snapshot_revision_id=GRAPH_REVISION_ID,
        snapshot_sha256=SNAPSHOT_SHA256,
    )
    session = Mock(spec=Session)
    session.scalar.return_value = publication_row
    session.get.return_value = snapshot
    session.scalars.side_effect = [(), ("analysisrun_" + "f" * 32,)]
    context = Mock()
    context.__enter__ = Mock(return_value=session)
    context.__exit__ = Mock(return_value=False)
    service = object.__new__(ApprovedItemGraphPublicationService)
    service.sessions = Mock(return_value=context)

    with pytest.raises(ApprovedItemGraphPublicationError) as caught:
        service._existing_publication(
            command,
            service._publication_idempotency_key(command),
        )

    assert caught.value.code == "APPROVED_ITEM_GRAPH_IDEMPOTENCY_CONFLICT"


def test_replay_rejects_a_different_authorization_time() -> None:
    command = _command()
    publication_row = SimpleNamespace(
        graph_snapshot_revision_id=NEW_GRAPH_REVISION_ID,
        published_by_operator_id=OPERATOR_ID,
        authorized_at=PUBLISHED_AT.replace(hour=PUBLISHED_AT.hour - 1),
    )
    snapshot = SimpleNamespace(
        graph_snapshot_revision_id=NEW_GRAPH_REVISION_ID,
        previous_graph_snapshot_revision_id=GRAPH_REVISION_ID,
        snapshot_sha256=SNAPSHOT_SHA256,
    )
    session = Mock(spec=Session)
    session.scalar.return_value = publication_row
    session.get.return_value = snapshot
    session.scalars.side_effect = [(), ANALYSIS_RUN_IDS]
    context = Mock()
    context.__enter__ = Mock(return_value=session)
    context.__exit__ = Mock(return_value=False)
    service = object.__new__(ApprovedItemGraphPublicationService)
    service.sessions = Mock(return_value=context)

    with pytest.raises(ApprovedItemGraphPublicationError) as caught:
        service._existing_publication(
            command,
            service._publication_idempotency_key(command),
        )

    assert caught.value.code == "APPROVED_ITEM_GRAPH_IDEMPOTENCY_CONFLICT"
