"""Existing resolver/persistence seam with synthetic dependencies, not live authority."""

from dataclasses import replace
from types import SimpleNamespace

import pytest
from eom_orchestrator.control_models import ResolvedExecutionPlanRecord
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.execution_materializer import (
    authorized_evidence_artifact_revisions,
    authorized_execution_artifact_revisions,
    materialize_execution_step,
)
from eom_orchestrator.execution_resolver import resolve_knowledge_backed_execution_plan
from eom_workflow.public_similarity_control import (
    PreparedPublicSimilarityPlan,
    SupportedPublicSimilarityExecutionPlan,
)
from eom_workflow.similarity_control import (
    PreparedSimilarityPlan,
    parse_post_registration_grounded_plan,
)

from tests.unit.public_similarity_plan_fixtures import public_plan_case
from tests.unit.test_execution_materializer import GROUP_ID, _workspace
from tests.unit.test_knowledge_backed_execution import _Session
from tests.unit.test_similarity_plan_execution_binding import creation_arguments


@pytest.fixture(params=(False, True))
def case(tmp_path, monkeypatch, request):
    return public_plan_case(tmp_path, monkeypatch, ordinary=request.param, registered=True)


def test_public_context_is_bound_before_first_persistence_without_replacing_base(case, monkeypatch):
    arguments, preset = creation_arguments(case)
    captured = []

    def record(session, *, document, dependencies):
        captured.append(document)
        assert document["schema_version"] == case["plan"].schema_version
        return SimpleNamespace(canonical_document=document)

    monkeypatch.setattr(
        "eom_orchestrator.execution_resolver.record_knowledge_backed_execution_plan", record
    )
    result = resolve_knowledge_backed_execution_plan(
        _Session(preset),
        **arguments,
        similarity=PreparedPublicSimilarityPlan(case["delivery"], case["context"]),
    )
    assert isinstance(result, SupportedPublicSimilarityExecutionPlan)
    assert parse_post_registration_grounded_plan(result.model_dump(mode="json")) == result
    assert result.similarity_delivery == case["delivery"]
    assert tuple(
        step.model_dump(exclude={"general_knowledge_mode"}) for step in result.steps
    ) == tuple(step.model_dump(exclude={"general_knowledge_mode"}) for step in case["base"].steps)
    # The resolver applies its actual preset's policy, unlike the nominal base fixture.
    assert preset.general_knowledge_policy == "DENY"
    assert all(step.general_knowledge_mode == "DENIED" for step in result.steps)
    assert result.retrieval_requirement == case["base"].retrieval_requirement
    assert len(captured) == 1
    assert case["base"].schema_version == "resolved-execution-plan/19.0"


class ReplaySession:
    def __init__(self, plan):
        self.plan = plan

    def scalar(self, statement):
        return SimpleNamespace(
            canonical_document=self.plan.model_dump(mode="json"),
            plan_id=self.plan.plan_id,
            workflow_id=self.plan.workflow_id,
            plan_sha256=self.plan.plan_sha256,
        )

    def get(self, *args):
        raise AssertionError("replay must not resolve latest mutable controls")


def test_public_plan_replay_reuses_exact_delivery_without_preset_or_publication(case):
    arguments, _ = creation_arguments(case)
    session = ReplaySession(case["plan"])
    prepared = PreparedPublicSimilarityPlan(case["delivery"], case["context"])
    assert resolve_knowledge_backed_execution_plan(session, **arguments) == case["plan"]
    assert (
        resolve_knowledge_backed_execution_plan(session, **arguments, similarity=prepared)
        == case["plan"]
    )


@pytest.mark.parametrize("stored", ("base", "legacy_plan"))
def test_historical_base_and_legacy_context_never_acquire_public_materials_on_replay(case, stored):
    arguments, _ = creation_arguments(case)
    session = ReplaySession(case[stored])
    with pytest.raises(ControlPlaneError) as error:
        resolve_knowledge_backed_execution_plan(
            session,
            **arguments,
            similarity=PreparedPublicSimilarityPlan(case["delivery"], case["context"]),
        )
    assert error.value.code == "CONTROL_PLAN_CONFLICT"
    assert resolve_knowledge_backed_execution_plan(session, **arguments) == case[stored]


def test_public_plan_does_not_fall_back_to_old_delivery_or_rebind_foreign_member(case):
    arguments, _ = creation_arguments(case)
    session = ReplaySession(case["plan"])
    old = PreparedSimilarityPlan(case["legacy_delivery"], case["legacy_context"])
    with pytest.raises(ControlPlaneError) as error:
        resolve_knowledge_backed_execution_plan(session, **arguments, similarity=old)
    assert error.value.code == "CONTROL_PLAN_CONFLICT"
    prepared = PreparedPublicSimilarityPlan(case["delivery"], case["context"])
    pin = prepared.delivery.model_copy(
        update={
            "context_member": prepared.delivery.context_member.model_copy(
                update={"artifact_id": "artifact_" + "0" * 32}
            )
        }
    )
    with pytest.raises(ControlPlaneError) as error:
        resolve_knowledge_backed_execution_plan(
            session, **arguments, similarity=replace(prepared, delivery=pin)
        )
    assert error.value.code == "CONTROL_PLAN_CONFLICT"


@pytest.mark.parametrize("role", ("authoring", "review"))
@pytest.mark.parametrize("operation", ("allowlist", "workspace"))
def test_unconnected_public_staging_cannot_silently_run_as_plain_plan19(
    case, tmp_path, role, operation
):
    record = case["session"].records[(ResolvedExecutionPlanRecord, case["plan_id"])]
    record.canonical_document = case["plan"].model_dump(mode="json")
    record.plan_sha256 = case["plan"].plan_sha256
    record.workflow_id = case["plan"].workflow_id
    workspace = _workspace(tmp_path, "public-staging-not-yet-connected")
    with pytest.raises(ControlPlaneError) as error:
        if operation == "allowlist":
            authorized_execution_artifact_revisions(
                case["session"], plan_id=case["plan_id"], step_key=role
            )
        else:
            materialize_execution_step(
                case["session"],
                plan_id=case["plan_id"],
                step_key=role,
                workspace=workspace,
                canonical_artifact_root=case["artifact_root"],
                worker_group_id=GROUP_ID,
                authorized_artifact_revision_ids=case["authorized"],
            )
    assert error.value.code == "CONTROL_SIMILARITY_AUTHORITY_UNAVAILABLE"
    assert not tuple(workspace.iterdir())
    # Reading the original approved Graph Evidence is a separate permission,
    # never an auxiliary similarity grant or a reason to drop the reference.
    evidence = authorized_evidence_artifact_revisions(
        case["session"], plan_id=case["plan_id"], step_key=role
    )
    assert case["plan"].similarity_delivery.context_member.artifact_revision_id not in evidence
