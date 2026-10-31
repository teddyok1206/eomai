"""Real local staging; synthetic current source/QUERY port is independently checked elsewhere."""

from dataclasses import replace

import pytest
from eom_catalog_contracts.inference_transfer_experiment import PopulationSource
from eom_identifiers import sha256_bytes
from eom_orchestrator.control_models import ResolvedExecutionPlanRecord
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.execution_materializer import (
    authorized_execution_artifact_revisions,
    materialize_execution_step,
)
from eom_orchestrator.public_similarity_materialization import (
    PUBLIC_SIMILARITY_ROLE_CONTRACT,
    resolve_public_similarity_materials,
)
from eom_orchestrator.similarity_materialization import SimilarityWorkspaceMaterials
from eom_workflow_runner.engine import _parse_review_escalation_plan
from pydantic import TypeAdapter

from tests.unit.public_similarity_materialization_fixtures import public_materialization_case
from tests.unit.test_execution_materializer import GROUP_ID, _workspace


@pytest.mark.parametrize("ordinary", (False, True))
@pytest.mark.parametrize("registered", (False, True))
@pytest.mark.parametrize(
    "role,tier", (("authoring", "PRIMARY"), ("review", "PRIMARY"), ("review", "ESCALATED"))
)
def test_actual_staging_passes_exact_public_materials_to_authoring_and_all_review_tiers(
    tmp_path, monkeypatch, ordinary, registered, role, tier
):
    case = public_materialization_case(
        tmp_path, monkeypatch, ordinary=ordinary, registered=registered
    )
    record = case["session"].records[(ResolvedExecutionPlanRecord, case["plan_id"])]
    record.canonical_document = case["plan"].model_dump(mode="json")
    record.plan_sha256 = case["plan"].plan_sha256
    record.workflow_id = case["plan"].workflow_id
    allowlist = authorized_execution_artifact_revisions(
        case["session"], plan_id=case["plan_id"], step_key=role, similarity_context=case["bound"]
    )
    workspace = _workspace(tmp_path, "actual-public-role")
    result = materialize_execution_step(
        case["session"],
        plan_id=case["plan_id"],
        step_key=role,
        workspace=workspace,
        canonical_artifact_root=case["artifact_root"],
        worker_group_id=GROUP_ID,
        authorized_artifact_revision_ids=allowlist,
        similarity_context=case["bound"],
        execution_tier=tier,
    )
    assert (workspace / "references/similarity/context.json").read_bytes() == case[
        "payload"
    ].context_payload
    assert (workspace / "references/similarity/materials.json").read_bytes() == case[
        "payload"
    ].references_payload
    agents = (workspace / "AGENTS.md").read_bytes()
    assert agents.endswith(PUBLIC_SIMILARITY_ROLE_CONTRACT)
    assert result.agents_sha256 == sha256_bytes(agents)
    assert _parse_review_escalation_plan(case["plan"].model_dump(mode="json")) == case["plan"]
    assert (workspace / "references/evidence/context.md").read_bytes() == case["context_payload"]
    if not ordinary:
        assert (workspace / "references/variation/source-item.json").read_bytes() == case[
            "source_payload"
        ]
    assert len(case["resolution_calls"]) == 1
    assert (
        case["resolution_calls"][0][1]["original_source"].model_dump(mode="json")
        == case["original_source"]
    )


@pytest.mark.parametrize(
    "fault",
    (
        "context_bytes",
        "material_bytes",
        "noncanonical",
        "foreign_workflow",
        "no_reader",
        "no_allowlist",
    ),
)
def test_public_handoff_rejects_unbound_noncanonical_or_foreign_values(
    tmp_path, monkeypatch, fault
):
    case = public_materialization_case(tmp_path, monkeypatch, registered=True)
    bound = case["bound"]
    allowed = frozenset({case["delivery"].context_member.artifact_revision_id})
    if fault == "foreign_workflow":
        bound = replace(bound, workflow_id="workflow_" + "0" * 32)
    elif fault == "no_reader":
        bound = None
    elif fault == "no_allowlist":
        allowed = frozenset()
    else:
        payload = case["payload"]
        payload = SimilarityWorkspaceMaterials(
            b"{}" if fault == "context_bytes" else payload.context_payload,
            b"{}" if fault == "material_bytes" else b" " + payload.references_payload,
        )

        class Reader:
            def resolve(self, session, **arguments):
                return payload

        bound = replace(bound, reader=Reader())
    with pytest.raises(ControlPlaneError):
        resolve_public_similarity_materials(
            case["session"],
            plan=case["plan"],
            step_key="authoring",
            context=bound,
            original_source=TypeAdapter(PopulationSource).validate_python(case["original_source"]),
            canonical_artifact_root=case["artifact_root"],
            authorized_artifact_revision_ids=allowed,
        )
