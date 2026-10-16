"""Ordinary delivery uses real local Artifact bytes; IAM/query observations remain synthetic."""

from __future__ import annotations

from dataclasses import replace

import pytest
from eom_catalog_contracts.similarity_context import parse_similarity_context_request
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator import execution_resolver as resolver
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.execution_materializer import authorized_evidence_artifact_revisions
from eom_orchestrator.similarity_materialization import (
    ORDINARY_SIMILARITY_ROLE_CONTRACT,
    SIMILARITY_MATERIALS_WORKSPACE_ALIAS,
    SIMILARITY_ROLE_CONTRACT,
    SIMILARITY_WORKSPACE_ALIAS,
)
from eom_workflow.similarity_control import PreparedSimilarityPlan, ResolvedExecutionPlanV24
from eom_workflow_runner.engine import _parse_review_escalation_plan

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.similarity_plan_fixtures import ordinary_similarity_case
from tests.unit.test_execution_materializer import _workspace
from tests.unit.test_knowledge_backed_execution import _Session
from tests.unit.test_similarity_execution_materializer import materialize, workspace_case
from tests.unit.test_similarity_materialization import failed_context, materialization_case, resolve
from tests.unit.test_similarity_plan_execution_binding import creation_arguments
from tests.unit.test_similarity_reference_pack import prompt_case
from tests.unit.test_similarity_role_composition import prepare, provider_case


@pytest.mark.parametrize("role", ("authoring", "review"))
def test_ordinary_exact_bytes_are_read_between_current_checks_without_reencoding(
    tmp_path, monkeypatch, role
):
    case = materialization_case(tmp_path, monkeypatch, ordinary=True)
    path = next(case["publisher"].settings.nas_artifact_root.rglob("context.json"))
    before = path.stat()
    with case["publisher"].sessions.begin() as session:
        raw = resolve(case, session, step_key=role)
    assert raw.context_payload == canonical_json_bytes(case["context"].model_dump(mode="json"))
    assert raw.references_payload == canonical_json_bytes(
        case["references"].model_dump(mode="json")
    )
    assert path.stat() == before
    assert case["reader"].calls == [(case["caller"], case["context"].request)] * 2


def test_ordinary_late_source_revocation_does_not_return_saved_materials(tmp_path, monkeypatch):
    case = materialization_case(tmp_path, monkeypatch, ordinary=True)
    case["reader"].late = failed_context(case["context"], "SOURCE_REVOKED")
    with case["publisher"].sessions.begin() as session, pytest.raises(ControlPlaneError) as caught:
        resolve(case, session)
    assert caught.value.code == "CONTROL_SIMILARITY_AUTHORITY_DENIED"
    assert len(case["reader"].calls) == 2
    assert len(tuple(case["publisher"].settings.nas_artifact_root.rglob("context.json"))) == 1


@pytest.mark.parametrize(
    "role,tier", (("authoring", "PRIMARY"), ("review", "PRIMARY"), ("review", "ESCALATED"))
)
def test_ordinary_workspace_has_official_and_auxiliary_evidence_without_variation_intent(
    tmp_path, monkeypatch, role, tier
):
    case = workspace_case(tmp_path, monkeypatch, ordinary=True)
    workspace = _workspace(tmp_path, "ordinary-reference")
    result = materialize(case, workspace, step_key=role, execution_tier=tier)
    assert (workspace / SIMILARITY_WORKSPACE_ALIAS).read_bytes() == canonical_json_bytes(
        case["context"].model_dump(mode="json")
    )
    assert (workspace / SIMILARITY_MATERIALS_WORKSPACE_ALIAS).read_bytes() == canonical_json_bytes(
        case["references"].model_dump(mode="json")
    )
    assert not (workspace / "references/variation").exists()
    assert (workspace / "references/evidence/manifest.json").read_bytes() == case[
        "manifest_payload"
    ]
    assert (workspace / "references/evidence/context.md").read_bytes() == case["context_payload"]
    agents = (workspace / "AGENTS.md").read_bytes()
    assert agents.endswith(ORDINARY_SIMILARITY_ROLE_CONTRACT)
    assert not agents.endswith(SIMILARITY_ROLE_CONTRACT)
    assert result.agents_sha256 == sha256_bytes(agents)
    assert result.materialized_member_count == 7
    assert _parse_review_escalation_plan(case["plan"].model_dump(mode="json")) == case["plan"]
    evidence = authorized_evidence_artifact_revisions(
        case["session"], plan_id=case["plan_id"], step_key=role
    )
    assert case["plan"].similarity_delivery.context_member.artifact_revision_id not in evidence


def test_ordinary_plan_is_resolved_once_before_first_persistence(tmp_path, monkeypatch):
    from types import SimpleNamespace

    case = ordinary_similarity_case(tmp_path, monkeypatch)
    arguments, preset = creation_arguments(case)
    captured = []

    def record(session, *, document, dependencies):
        captured.append(document)
        assert document["schema_version"] == "resolved-execution-plan/24.0"
        return SimpleNamespace(canonical_document=document)

    monkeypatch.setattr(resolver, "record_knowledge_backed_execution_plan", record)
    result = resolver.resolve_knowledge_backed_execution_plan(
        _Session(preset),
        **arguments,
        similarity=PreparedSimilarityPlan(case["delivery"], case["context"]),
    )
    assert type(result) is ResolvedExecutionPlanV24
    assert result.similarity_reference == case["context"].request.anchor
    expected_mode = (
        "DENIED" if preset.general_knowledge_policy == "DENY" else "ALLOWED_WITH_PROVENANCE"
    )
    assert result.steps == tuple(
        step.model_copy(update={"general_knowledge_mode": expected_mode})
        for step in case["base"].steps
    )
    assert len(captured) == 1


def test_ordinary_exact_replay_returns_original_plan_without_current_lookup(tmp_path, monkeypatch):
    from types import SimpleNamespace

    case = ordinary_similarity_case(tmp_path, monkeypatch)
    arguments, _preset = creation_arguments(case)
    plan = case["plan"]

    class ReplaySession:
        def scalar(self, statement):
            return SimpleNamespace(
                canonical_document=plan.model_dump(mode="json"),
                plan_id=plan.plan_id,
                workflow_id=plan.workflow_id,
                plan_sha256=plan.plan_sha256,
            )

        def get(self, *args):
            raise AssertionError("replay must not read mutable controls")

    prepared = PreparedSimilarityPlan(case["delivery"], case["context"])
    assert resolver.resolve_knowledge_backed_execution_plan(ReplaySession(), **arguments) == plan
    assert (
        resolver.resolve_knowledge_backed_execution_plan(
            ReplaySession(), **arguments, similarity=prepared
        )
        == plan
    )
    foreign_pin = case["delivery"].model_copy(
        update={
            "context_member": case["delivery"].context_member.model_copy(
                update={
                    "artifact_id": "artifact_" + "0" * 32,
                }
            ),
        }
    )
    with pytest.raises(ControlPlaneError) as caught:
        resolver.resolve_knowledge_backed_execution_plan(
            ReplaySession(), **arguments, similarity=replace(prepared, delivery=foreign_pin)
        )
    assert caught.value.code == "CONTROL_PLAN_CONFLICT"


@pytest.mark.parametrize("role", ("authoring", "review"))
def test_ordinary_role_binds_current_human_creator_and_unchanged_reference_query(
    tmp_path, monkeypatch, role
):
    value = provider_case(tmp_path, monkeypatch, role, ordinary=True)
    context = prepare(value)
    assert context.request.consumer_purpose == "ITEM_AUTHORING"
    assert context.request == value.query.request.context_request
    assert context.operator_id == value.workflow.created_actor_id
    value.query.owner.identity.fence_current_operator.assert_called_once_with(
        value.session, context.operator_id
    )


def test_ordinary_foreign_query_fails_before_workspace_disclosure(tmp_path, monkeypatch):
    case = workspace_case(tmp_path, monkeypatch, ordinary=True)
    raw = case["context"].request.model_dump(mode="json")
    raw["consumer_purpose"] = "ITEM_REVIEW"
    foreign = replace(
        case["bound"], request=parse_similarity_context_request(seal(raw, "request_sha256"))
    )
    workspace = _workspace(tmp_path, "wrong-purpose")
    with pytest.raises(ControlPlaneError) as caught:
        materialize(case, workspace, similarity_context=foreign)
    assert caught.value.code == "CONTROL_SIMILARITY_CONTEXT_INVALID"
    assert not (workspace / "references").exists()


def test_ordinary_prompt_mode_is_derived_from_persisted_plan_not_worker_request(
    tmp_path, monkeypatch
):
    from eom_catalog_service.similarity_prompt_context import read_similarity_prompt_context

    _case, record, workflow, step, session = prompt_case(tmp_path, monkeypatch, ordinary=True)
    assert (
        read_similarity_prompt_context(
            session,
            workflow=workflow,
            step=step,
            pack_release_id=record.canonical_document["content_pack_release_id"],
        ).reference_mode
        == "PINNED_REFERENCE_CONTEXT"
    )
