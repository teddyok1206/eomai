"""Real correction verifier with synthetic analysis/publication ports, not DB/model proof."""

from contextlib import nullcontext
from dataclasses import FrozenInstanceError
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from eom_catalog_contracts import (
    ApprovedItemKnowledgeSourceV2,
    KnowledgeAnalysisApplicationResult,
    KnowledgeAnalysisRequestV2,
    KnowledgeAnalysisRequestV11,
)
from eom_catalog_service import material_native_visual_correction_learning as owner
from eom_catalog_service.knowledge_graph_publication_service import KnowledgeGraphPublicationError
from eom_catalog_service.material_graph_learning import MaterialAnalysisControls
from eom_identifiers import content_sha256
from eom_operator_identity import PermissionKey

from tests.unit.test_material_native_visual_correction import (
    BASE,
    applied_correction,
)
from tests.unit.test_material_native_visual_correction import correction as correction
from tests.unit.test_registered_item_solution_analysis_candidate_schemas import request_value
from tests.unit.test_registered_item_solution_application import base_request

BASE_RUN = "analysisrun_" + "a" * 32
PUBLIC_RUN = "analysisrun_" + "b" * 32
GRAPH = "graphrev_" + "c" * 32
NEXT_GRAPH = "graphrev_" + "d" * 32


def learning_case(monkeypatch, correction):
    corrections, receipt, source_state = applied_correction(correction)
    actor = receipt.prepared.command.actor_id
    source = ApprovedItemKnowledgeSourceV2(
        source_class="APPROVED_ITEM",
        item_id=receipt.prepared.item_id,
        item_revision_id=receipt.item_revision_id,
        artifact_member={
            **receipt.content.model_dump(mode="json"),
            "materialized_path": "source/item-content.json",
            "bytes": receipt.prepared.corrected_content_bytes,
            "logical_name": "item-content.json",
        },
    )
    templates = {"BASE": base_request().model_dump(mode="json"), "PUBLIC": request_value()}
    for kind, body in templates.items():
        body["source"] = source.model_dump(mode="json")
        body["general_knowledge_mode"] = "DISABLED"
        if kind == "PUBLIC":
            body["predecessor_analysis_run_id"] = BASE_RUN
            body["base_analysis"]["analysis_run_id"] = BASE_RUN
            body["base_analysis"]["analysis_request_id"] = templates["BASE"]["analysis_request_id"]
        body["request_sha256"] = content_sha256(
            {key: value for key, value in body.items() if key != "request_sha256"}
        )
    requests = {
        "BASE": KnowledgeAnalysisRequestV2.model_validate(templates["BASE"]),
        "PUBLIC": KnowledgeAnalysisRequestV11.model_validate(templates["PUBLIC"]),
    }
    rows = {}

    class Session:
        def scalar(self, statement):
            key = statement.compile().params["idempotency_key_1"]
            return next((row for row in rows.values() if row.idempotency_key == key), None)

        def get(self, _model, key, **_kwargs):
            return rows.get(key)

    session = Session()
    service = object.__new__(owner.MaterialNativeVisualCorrectionLearningService)
    service.sessions = lambda: nullcontext(session)
    service.corrections = corrections
    service.controls = MaterialAnalysisControls(
        item=NS(
            preset_id=requests["BASE"].execution_preset_id,
            preset_revision_id=requests["BASE"].execution_preset_revision_id,
        ),
        document=NS(),
        solution=NS(
            preset_id=requests["PUBLIC"].execution_preset_id,
            preset_revision_id=requests["PUBLIC"].execution_preset_revision_id,
        ),
        risk_policy_revision_id=requests["BASE"].risk_policy_revision_id,
        access_policy_revision_id="accessrev_" + "e" * 32,
    )
    assert requests["PUBLIC"].risk_policy_revision_id == service.controls.risk_policy_revision_id
    monkeypatch.setattr(owner, "current_model_preset", lambda _session, baseline: baseline)
    permission = {"allowed": True}
    monkeypatch.setattr(
        owner,
        "authorize_material_learning",
        lambda _session, actual: (
            None if actual == actor else (_ for _ in ()).throw(ValueError("wrong actual actor"))
        ),
    )
    monkeypatch.setattr(
        owner,
        "effective_permissions",
        lambda *_a: (
            {
                PermissionKey.KNOWLEDGE_ANALYSIS_CREATE,
                PermissionKey.KNOWLEDGE_GRAPH_READ,
                PermissionKey.KNOWLEDGE_GRAPH_PUBLISH,
            }
            if permission["allowed"]
            else set()
        ),
    )
    service.analyses = Mock()

    def projection(row):
        return KnowledgeAnalysisApplicationResult(
            analysis_run_id=row.analysis_run_id,
            workflow_id=row.workflow_id,
            state=row.state,
            resource_version=1,
            accepted_result_artifact_revision_id=row.accepted_result_artifact_revision_id
            if row.state == "ACCEPTED"
            else None,
        )

    def create(kind, command):
        request = requests[kind]
        identity = BASE_RUN if kind == "BASE" else PUBLIC_RUN
        assert command.requested_by == actor
        assert command.idempotency_key == owner.native_visual_correction_analysis_key(
            receipt, kind=kind
        )
        if kind == "BASE":
            assert command.source.item_revision_id == receipt.item_revision_id != BASE
            assert command.predecessor_analysis_run_id is None
        else:
            assert command.base_analysis_run_id == BASE_RUN
        rows[identity] = NS(
            analysis_run_id=identity,
            analysis_request_id=request.analysis_request_id,
            workflow_id="workflow_" + ("a" if kind == "BASE" else "b") * 32,
            state="QUEUED",
            idempotency_key=command.idempotency_key,
            created_by_operator_id=actor,
            item_id=receipt.prepared.item_id,
            item_revision_id=receipt.item_revision_id,
            canonical_request=request.model_dump(mode="json"),
            request_sha256=request.request_sha256,
            predecessor_analysis_run_id=None if kind == "BASE" else BASE_RUN,
            preset_id=request.execution_preset_id,
            preset_revision_id=request.execution_preset_revision_id,
            risk_policy_revision_id=request.risk_policy_revision_id,
            source_sha256=receipt.content.sha256,
            source_artifact_id=receipt.content.artifact_id,
            source_artifact_revision_id=receipt.content.artifact_revision_id,
            accepted_result_artifact_revision_id="rev_" + ("c" if kind == "BASE" else "d") * 32,
            accepted_result_sha256="sha256:" + ("c" if kind == "BASE" else "d") * 64,
        )
        return projection(rows[identity])

    service.analyses.create_with_pinned_preset.side_effect = lambda command, **_kwargs: create(
        "BASE", command
    )
    service.analyses.create_material_solution_with_pinned_preset.side_effect = (
        lambda command, **_kwargs: create("PUBLIC", command)
    )
    service.analyses.reconcile.side_effect = lambda command: projection(
        rows[command.analysis_run_id]
    )

    def accept(*, analysis_run_id, requested_by):
        assert requested_by == actor
        rows[analysis_run_id].state = "ACCEPTED"
        return projection(rows[analysis_run_id])

    service.analyses.accept_validated_without_review.side_effect = accept
    service.publication = Mock()
    context = NS(graph_snapshot_revision_id=GRAPH, accepted_analysis_run_ids=())
    service.publication.current_structure_context.return_value = context

    def accepted():
        return NS(
            analysis_run_id=BASE_RUN,
            source=source,
            accepted_result=NS(
                artifact_revision_id=rows[BASE_RUN].accepted_result_artifact_revision_id,
                sha256=rows[BASE_RUN].accepted_result_sha256,
            ),
        )

    service.publication.resolve_accepted_analyses.side_effect = lambda _session, ids: (
        {BASE_RUN: NS(analysis=accepted())}
        if ids == (BASE_RUN,)
        else (_ for _ in ()).throw(AssertionError("foreign accepted ID"))
    )

    def evidence(_session, _artifacts, *, base_analysis_run_ids):
        assert base_analysis_run_ids == (BASE_RUN,)
        return {
            BASE_RUN: NS(
                source=source,
                pointer=NS(
                    solution_analysis_run_id=PUBLIC_RUN,
                    accepted_result_artifact=NS(
                        artifact_revision_id=rows[PUBLIC_RUN].accepted_result_artifact_revision_id,
                        sha256=rows[PUBLIC_RUN].accepted_result_sha256,
                    ),
                ),
                base_accepted_result=accepted().accepted_result,
            )
        }

    evidence_reader = Mock(side_effect=evidence)
    monkeypatch.setattr(owner, "resolve_registered_solution_evidence_by_base_run", evidence_reader)
    service.automatic = Mock()

    def publish(candidates, **kwargs):
        assert len(candidates) == 1 and candidates[0].analysis_run_id == BASE_RUN
        assert candidates[0].requested_by_operator_id == actor
        kwargs["analysis_validator"](session, (accepted(),))
        context.accepted_analysis_run_ids = (BASE_RUN,)
        context.graph_snapshot_revision_id = NEXT_GRAPH
        return NS(graph_publication=NS(graph_snapshot=NS(graph_snapshot_revision_id=NEXT_GRAPH)))

    service.automatic.publish.side_effect = publish
    return NS(**locals())


def advance(value):
    return value.service.advance(value.receipt, operator_id=value.actor)


def accepted_reports(value):
    assert advance(value).state == "BASE_PENDING"
    value.rows[BASE_RUN].state = "ACCEPTED"
    assert advance(value).state == "PUBLIC_PENDING"
    value.rows[PUBLIC_RUN].state = "ACCEPTED"


def test_corrected_content_gets_fresh_base_and_public_once_then_common_graph(
    monkeypatch, correction
):
    value = learning_case(monkeypatch, correction)
    assert advance(value).state == "BASE_PENDING"
    assert advance(value).state == "BASE_PENDING"
    value.service.analyses.create_with_pinned_preset.assert_called_once()
    assert not value.service.analyses.create_material_solution_with_pinned_preset.called
    value.rows[BASE_RUN].state = "VALIDATING"
    assert advance(value).state == "PUBLIC_PENDING"
    assert advance(value).state == "PUBLIC_PENDING"
    value.service.analyses.create_material_solution_with_pinned_preset.assert_called_once()
    value.rows[PUBLIC_RUN].state = "NEEDS_REVIEW"
    result = advance(value)
    assert result.state == "PUBLISHED" and result.graph_snapshot_revision_id == NEXT_GRAPH
    assert result.item_revision_id == value.receipt.item_revision_id
    assert result.base_analysis.analysis_run_id == BASE_RUN
    assert result.public_analysis.analysis_run_id == PUBLIC_RUN
    assert advance(value) == result
    value.service.automatic.publish.assert_called_once()
    assert value.source_state.imports == 1
    assert not hasattr(result, "__dict__")
    with pytest.raises(FrozenInstanceError):
        result.state = "BASE_PENDING"


@pytest.mark.parametrize("kind", ["BASE", "PUBLIC"])
@pytest.mark.parametrize("state", ["FAILED", "REJECTED", "CANCELLED"])
def test_failed_history_blocks_without_automatic_new_model_or_report(
    monkeypatch, correction, kind, state
):
    value = learning_case(monkeypatch, correction)
    advance(value)
    identity = BASE_RUN
    if kind == "PUBLIC":
        value.rows[BASE_RUN].state = "ACCEPTED"
        advance(value)
        identity = PUBLIC_RUN
    value.rows[identity].state = state
    assert advance(value).state == kind + "_FAILED"
    assert advance(value).state == kind + "_FAILED"
    assert value.rows[identity].state == state
    assert value.service.analyses.create_with_pinned_preset.call_count == 1
    assert value.service.analyses.create_material_solution_with_pinned_preset.call_count == (
        kind == "PUBLIC"
    )
    value.service.automatic.publish.assert_not_called()


@pytest.mark.parametrize(
    "field",
    ["source_sha256", "created_by_operator_id", "item_revision_id", "preset_id", "request_sha256"],
)
def test_existing_analysis_is_exact_receipt_source_not_old_accepted_base(
    monkeypatch, correction, field
):
    value = learning_case(monkeypatch, correction)
    advance(value)
    setattr(value.rows[BASE_RUN], field, "foreign")
    with pytest.raises(ValueError, match="ANALYSIS_MISMATCH"):
        advance(value)
    value.service.automatic.publish.assert_not_called()


def test_same_source_operator_and_current_approved_revision_are_required_on_every_poll(
    monkeypatch, correction
):
    value = learning_case(monkeypatch, correction)
    advance(value)
    value.source_state.permission = False
    with pytest.raises(ValueError, match="PERMISSION_REVOKED"):
        advance(value)
    assert value.service.analyses.create_with_pinned_preset.call_count == 1
    value.service.automatic.publish.assert_not_called()


def test_publication_replay_still_resolves_real_public_evidence_and_source(monkeypatch, correction):
    value = learning_case(monkeypatch, correction)
    accepted_reports(value)
    advance(value)
    value.evidence_reader.return_value = {}
    value.evidence_reader.side_effect = None
    with pytest.raises(ValueError, match="PUBLIC_EVIDENCE_MISMATCH"):
        advance(value)
    value.service.automatic.publish.assert_called_once()


def test_final_graph_validator_rechecks_source_before_common_publisher_commit(
    monkeypatch, correction
):
    value = learning_case(monkeypatch, correction)
    accepted_reports(value)

    def revoked(_candidates, **kwargs):
        value.source_state.permission = False
        kwargs["analysis_validator"](value.session, (value.accepted(),))
        raise AssertionError("must not reach publication")

    value.service.automatic.publish.side_effect = revoked
    with pytest.raises(ValueError, match="PERMISSION_REVOKED"):
        advance(value)


def test_graph_cas_retry_is_bounded_and_does_not_recreate_models(monkeypatch, correction):
    value = learning_case(monkeypatch, correction)
    accepted_reports(value)
    value.service.automatic.publish.side_effect = KnowledgeGraphPublicationError(
        "KNOWLEDGE_GRAPH_STALE_CURRENT", "synthetic race"
    )
    with pytest.raises(ValueError, match="GRAPH_BUSY"):
        advance(value)
    assert value.service.automatic.publish.call_count == 3
    value.service.analyses.create_with_pinned_preset.assert_called_once()
    value.service.analyses.create_material_solution_with_pinned_preset.assert_called_once()
