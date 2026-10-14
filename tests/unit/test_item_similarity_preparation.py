"""Real publisher/SQLite/Artifact bytes; source/capture/QUERY observations remain synthetic."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace

import pytest
from eom_catalog_contracts.similarity_context import parse_similarity_context
from eom_catalog_service.embedding_registry_ports import EmbeddingRegistryCaller
from eom_catalog_service.settings import CatalogSettings
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_identity_service import OperatorAuthorizationFenceError
from eom_image_contracts import SVG_LABEL_LAYOUT_PACK_BUNDLES
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord, JobRecord
from eom_workflow.control_plane import ExecutionPresetRevisionV2
from eom_workflow.models import ExpectedWorkflowResolution, WorkflowRequest
from eom_workflow.similarity_control import PreparedSimilarityPlan
from eom_workflow_runner import item_similarity_preparation as module
from eom_workflow_runner.item_similarity_preparation import CatalogItemSimilarityPreparation
from sqlalchemy import func, select

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_knowledge_backed_execution import _Session
from tests.unit.test_similarity_context_artifact import SOURCE, publisher_for
from tests.unit.test_similarity_plan_execution_binding import creation_arguments
from tests.unit.test_similarity_role_composition import provider_case


def preparation_case(tmp_path, monkeypatch):
    scope = tmp_path / "scope"
    scope.mkdir()
    value = provider_case(scope, monkeypatch)
    arguments, preset = creation_arguments(value.case)
    preset_body = preset.model_dump(mode="json")
    # This synthetic control explicitly allows the auxiliary classes used by the fixture.
    preset_body["retrieval_policy"]["allowed_source_classes"] = list(
        value.case["context"].request.source_classes
    )
    preset = ExecutionPresetRevisionV2.model_validate(seal(preset_body, "content_sha256"))
    base = value.case["base"]
    expected = ExpectedWorkflowResolution(
        workflow_definition_key=base.workflow_definition_key,
        workflow_definition_version=base.workflow_definition_version,
        workflow_definition_sha256=base.workflow_definition_sha256,
        content_pack_release_id=base.content_pack_release_id,
        content_pack_key="generated-knowledge-item",
        content_pack_version="1.20.17",
        content_pack_bundle_sha256=SVG_LABEL_LAYOUT_PACK_BUNDLES["1.20.17"],
        content_pack_source_tree_sha256="sha256:" + "1" * 64,
        execution_preset_id=preset.preset_id,
        execution_preset_revision_id=preset.preset_revision_id,
        execution_preset_key=value.request.execution_preset_key,
        execution_preset_content_sha256=preset.content_sha256,
    )
    request = value.request
    publication = tmp_path / "publication"
    publication.mkdir()
    publisher = publisher_for(publication)
    value.query.sessions = publisher.sessions
    value.query.workflow_id = "workflow_" + "9" * 32
    value.query.owner.settings = CatalogSettings(
        nas_artifact_root=publisher.settings.nas_artifact_root
    )
    calls = []
    hooks = []

    def compose(session, caller, query_request):
        assert session.get_transaction() is not None and session.get_transaction().is_active
        assert caller.operator_id == value.workflow.created_actor_id
        assert query_request == value.case["context"].request
        calls.append(session)
        if hooks:
            return hooks.pop(0)()
        return value.case["context"]

    monkeypatch.setattr(
        module,
        "CatalogSimilaritySessionContextReader",
        lambda query: SimpleNamespace(compose_in_session=compose),
    )
    return SimpleNamespace(
        value=value,
        publisher=publisher,
        request=request,
        resolution=expected,
        evidence=arguments["evidence"],
        preset=preset,
        calls=calls,
        hooks=hooks,
        caller=EmbeddingRegistryCaller(value.workflow.created_actor_id),
        owner=CatalogItemSimilarityPreparation(value.query, publisher, source_commit=SOURCE),
    )


def prepare(case, **changes):
    values = dict(
        workflow_request=case.request,
        expected_resolution=case.resolution,
        evidence=case.evidence,
        preset=case.preset,
    )
    values.update(changes)
    return case.owner.prepare(case.caller, **values)


def counts(case):
    with case.publisher.sessions.begin() as session:
        return tuple(
            session.scalar(select(func.count()).select_from(model))
            for model in (JobRecord, ArtifactRevisionRecord)
        )


def failed_context(context, code="SOURCE_REVOKED"):
    raw = context.model_dump(mode="json") | {
        "status": "FAILED",
        "population": None,
        "query_execution": None,
        "graph_evidence": None,
        "candidates": [],
        "error_code": code,
    }
    return parse_similarity_context(seal(raw, "context_sha256"))


def test_owner_publication_replay_preserves_one_canonical_artifact_and_same_root(
    tmp_path, monkeypatch
):
    case = preparation_case(tmp_path, monkeypatch)
    first = prepare(case)
    assert isinstance(first.plan, PreparedSimilarityPlan)
    assert first.plan.delivery == first.publication.delivery
    assert first.workflow_request_sha256 == content_sha256(case.request.model_dump(mode="json"))
    assert first.evidence_result_sha256 == case.evidence.result_sha256
    assert first.preset_content_sha256 == case.preset.content_sha256
    assert first.resolution == case.resolution
    assert case.request.production_occurrence is None and case.request.expected_resolution is None
    (member,) = tuple(case.publisher.settings.nas_artifact_root.rglob("context.json"))
    before = member.stat()
    assert prepare(case) == first
    assert member.stat() == before
    assert counts(case) == (1, 1)
    assert case.calls[0] is case.calls[1] and case.calls[2] is case.calls[3]
    assert case.calls[0] is not case.calls[2]
    assert member.read_bytes() == canonical_json_bytes(first.plan.context.model_dump(mode="json"))
    with pytest.raises(FrozenInstanceError):
        first.evidence_result_sha256 = "sha256:" + "0" * 64


@pytest.mark.parametrize(
    "fault",
    (
        "query_identity",
        "other_actor",
        "expected_missing",
        "pack_version",
        "pack_hash",
        "preset_pin",
        "source_revision",
        "evidence_graph",
        "copied_request",
        "copied_evidence",
        "copied_preset",
        "copied_resolution",
        "source_classes",
    ),
)
def test_bad_scope_or_raw_model_copies_never_create_a_publication(tmp_path, monkeypatch, fault):
    case = preparation_case(tmp_path, monkeypatch)
    changes = {}
    if fault == "query_identity":
        case.value.query.workflow_id = True
    elif fault == "other_actor":
        case.caller = EmbeddingRegistryCaller("operator_" + "0" * 32)
    elif fault == "expected_missing":
        changes["expected_resolution"] = None
    elif fault in {"pack_version", "pack_hash", "preset_pin"}:
        key, value = {
            "pack_version": ("content_pack_version", "1.20.16"),
            "pack_hash": ("content_pack_bundle_sha256", "sha256:" + "0" * 64),
            "preset_pin": ("execution_preset_content_sha256", "sha256:" + "0" * 64),
        }[fault]
        changes["expected_resolution"] = case.resolution.model_copy(update={key: value})
    elif fault == "source_revision":
        requirement = case.request.educational_retrieval
        variation = requirement.past_exam_variation.model_copy(
            update={"source_item_revision_id": "itemrev_" + "0" * 32}
        )
        changes["workflow_request"] = case.request.model_copy(
            update={
                "educational_retrieval": requirement.model_copy(
                    update={"past_exam_variation": variation}
                ),
            }
        )
    elif fault == "evidence_graph":
        document = case.evidence.model_dump(mode="json")
        document["graph_snapshot"]["graph_snapshot_revision_id"] = "graphrev_" + "0" * 32
        changes["evidence"] = type(case.evidence).model_validate(seal(document, "result_sha256"))
    elif fault == "source_classes":
        body = case.preset.model_dump(mode="json")
        body["retrieval_policy"]["allowed_source_classes"] = ["PAST_EXAM"]
        restricted = ExecutionPresetRevisionV2.model_validate(seal(body, "content_sha256"))
        changes["preset"] = restricted
        changes["expected_resolution"] = case.resolution.model_copy(
            update={
                "execution_preset_content_sha256": restricted.content_sha256,
            }
        )
    else:
        key, value = {
            "copied_request": ("workflow_request", case.request),
            "copied_evidence": ("evidence", case.evidence),
            "copied_preset": ("preset", case.preset),
            "copied_resolution": ("expected_resolution", case.resolution),
        }[fault]
        changes[key] = value.model_copy(update={"authority": "ADMIN"})
    with pytest.raises(ControlPlaneError):
        prepare(case, **changes)
    assert case.calls == [] and counts(case) == (0, 0)


@pytest.mark.parametrize("when", ("before", "after"))
def test_current_denial_preserves_committed_history_without_returning_a_plan(
    tmp_path, monkeypatch, when
):
    case = preparation_case(tmp_path, monkeypatch)
    context = case.value.case["context"]
    case.hooks.extend(
        ([lambda: context] if when == "after" else []) + [lambda: failed_context(context)]
    )
    with pytest.raises(ControlPlaneError) as error:
        prepare(case)
    assert error.value.code == "CONTROL_SIMILARITY_AUTHORITY_DENIED"
    assert counts(case) == ((1, 1) if when == "after" else (0, 0))
    if when == "after":
        with case.publisher.sessions.begin() as session:
            assert session.scalar(select(JobRecord)).status == "SUCCEEDED"
        # Restored current permission can replay the original publication, not create a successor.
        result = prepare(case)
        assert result.plan.context == context and counts(case) == (1, 1)


def test_expired_capture_cannot_be_replaced_by_caller_or_stored_context(tmp_path, monkeypatch):
    case = preparation_case(tmp_path, monkeypatch)
    case.value.query.owner.identity.fence_current_operator.side_effect = (
        OperatorAuthorizationFenceError("OPERATOR_AUTHORIZATION_FENCE_UNAVAILABLE")
    )
    with pytest.raises(ControlPlaneError, match="current owner unavailable"):
        prepare(case)
    assert case.calls == [] and counts(case) == (0, 0)


def test_same_key_changed_context_conflicts_instead_of_making_another_artifact(
    tmp_path, monkeypatch
):
    case = preparation_case(tmp_path, monkeypatch)
    original = prepare(case)
    raw = original.plan.context.model_dump(mode="json")
    raw["population"]["truncated"] = True
    raw["limitations"].append("BOUNDED_SCOPE_TRUNCATED")
    successor = parse_similarity_context(seal(raw, "context_sha256"))
    case.hooks.append(lambda: successor)
    with pytest.raises(ControlPlaneError):
        prepare(case)
    assert counts(case) == (1, 1)
    assert prepare(case) == original


def test_distinct_private_briefs_reuse_the_same_exact_query_context_without_duplicate_bytes(
    tmp_path, monkeypatch
):
    case = preparation_case(tmp_path, monkeypatch)
    first = prepare(case)
    document = case.request.model_dump(mode="json")
    document["item_brief"]["topic"] = "다른 출제 요청의 합성 문항 주제"
    document["item_brief"]["original_request_sha256"] = "1" * 64
    changed = WorkflowRequest.model_validate(document)
    second = prepare(case, workflow_request=changed)
    assert first.plan == second.plan and first.publication == second.publication
    assert first.workflow_request_sha256 != second.workflow_request_sha256
    assert counts(case) == (1, 1)


def test_production_pin_must_match_explicit_preflight_without_changing_the_normal_item_contract(
    tmp_path, monkeypatch
):
    case = preparation_case(tmp_path, monkeypatch)
    document = case.request.model_dump(mode="json") | {
        "production_occurrence": {
            "schema_version": "workflow-production-occurrence/1.0",
            "production_request_id": "productionreq_" + "a" * 32,
            "workflow_call_id": "workflowcall_" + "b" * 32,
        },
        "expected_resolution": case.resolution.model_dump(mode="json"),
    }
    production = WorkflowRequest.model_validate(document)
    mismatched = case.resolution.model_copy(
        update={"content_pack_source_tree_sha256": "sha256:" + "0" * 64}
    )
    with pytest.raises(ControlPlaneError):
        prepare(case, workflow_request=production, expected_resolution=mismatched)
    assert counts(case) == (0, 0) and case.calls == []
    assert prepare(case, workflow_request=production).resolution == case.resolution


def test_actual_published_context_binds_plan23_before_the_one_plan_record_call(
    tmp_path, monkeypatch
):
    from eom_orchestrator.execution_resolver import resolve_knowledge_backed_execution_plan

    case = preparation_case(tmp_path, monkeypatch)
    prepared = prepare(case)
    arguments, _original_preset = creation_arguments(case.value.case)
    arguments["dependencies"] = replace(
        arguments["dependencies"], content_pack_sha256=case.resolution.content_pack_bundle_sha256
    )
    captures = []

    def record(session, *, document, dependencies):
        captures.append(document)
        assert document["schema_version"] == "resolved-execution-plan/23.0"
        return SimpleNamespace(canonical_document=document)

    monkeypatch.setattr(
        "eom_orchestrator.execution_resolver.record_knowledge_backed_execution_plan", record
    )
    plan = resolve_knowledge_backed_execution_plan(
        _Session(case.preset), **arguments, similarity=prepared.plan
    )
    assert len(captures) == 1
    assert plan.similarity_delivery == prepared.publication.delivery
    assert plan.evidence_manifest_artifact == case.evidence.manifest_artifact
    assert plan.content_pack_sha256 == case.resolution.content_pack_bundle_sha256
    assert counts(case) == (1, 1)


def test_late_canonical_lifecycle_change_preserves_bytes_but_refuses_handoff(tmp_path, monkeypatch):
    case = preparation_case(tmp_path, monkeypatch)
    context = case.value.case["context"]

    def unapprove():
        with case.publisher.sessions.begin() as session:
            session.scalar(select(ArtifactRecord)).approved = False
        return context

    case.hooks.extend((lambda: context, unapprove))
    with pytest.raises(ControlPlaneError):
        prepare(case)
    assert counts(case) == (1, 1)
