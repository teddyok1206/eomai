"""Public workspace wiring with explicit resolver stub; physical reads are tested separately."""

from __future__ import annotations

from pathlib import Path

import pytest
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator import execution_materializer as module
from eom_orchestrator.control_models import ResolvedExecutionPlanRecord
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.execution_materializer import (
    authorized_execution_artifact_revisions,
    materialize_execution_step,
)
from eom_orchestrator.similarity_materialization import (
    SIMILARITY_MATERIALS_WORKSPACE_ALIAS,
    SIMILARITY_ROLE_CONTRACT,
    SIMILARITY_WORKSPACE_ALIAS,
    SimilarityWorkspaceMaterials,
)
from eom_workflow.similarity_control import parse_similarity_execution_plan
from eom_workflow_runner.engine import _parse_review_escalation_plan

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_execution_materializer import GROUP_ID, _workspace
from tests.unit.test_similarity_materialization import materialization_case


def workspace_case(tmp_path, monkeypatch):
    case = materialization_case(tmp_path, monkeypatch)
    record = case["session"].records[(ResolvedExecutionPlanRecord, case["plan_id"])]
    record.canonical_document = case["plan"].model_dump(mode="json")
    record.plan_sha256 = case["plan"].plan_sha256
    calls = []

    def resolved(session, **kwargs):
        calls.append((session, kwargs))
        return SimilarityWorkspaceMaterials(
            canonical_json_bytes(case["context"].model_dump(mode="json")),
            canonical_json_bytes(case["references"].model_dump(mode="json")),
        )

    monkeypatch.setattr(module, "resolve_similarity_materials", resolved)
    case["resolution_calls"] = calls
    return case


def materialize(case, workspace, **changes):
    arguments = {
        "plan_id": case["plan_id"],
        "step_key": "authoring",
        "workspace": workspace,
        "canonical_artifact_root": case["artifact_root"],
        "worker_group_id": GROUP_ID,
        "authorized_artifact_revision_ids": case["authorized"]
        | {case["plan"].similarity_delivery.context_member.artifact_revision_id},
        "similarity_context": case["bound"],
    }
    arguments.update(changes)
    return materialize_execution_step(case["session"], **arguments)


@pytest.mark.parametrize(
    "role,tier", (("authoring", "PRIMARY"), ("review", "PRIMARY"), ("review", "ESCALATED"))
)
def test_authoring_and_both_review_tiers_preserve_original_and_separate_auxiliary_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, role: str, tier: str
) -> None:
    case = workspace_case(tmp_path, monkeypatch)
    workspace = _workspace(tmp_path, "similarity")
    result = materialize(case, workspace, step_key=role, execution_tier=tier)
    assert (workspace / SIMILARITY_WORKSPACE_ALIAS).read_bytes() == canonical_json_bytes(
        case["context"].model_dump(mode="json")
    )
    assert (workspace / SIMILARITY_MATERIALS_WORKSPACE_ALIAS).read_bytes() == canonical_json_bytes(
        case["references"].model_dump(mode="json")
    )
    assert (workspace / "references/variation/source-item.json").read_bytes() == case[
        "source_payload"
    ]
    assert (workspace / "references/evidence/context.md").read_bytes() == case["context_payload"]
    assert (workspace / "references/evidence/manifest.json").read_bytes() == case[
        "manifest_payload"
    ]
    agents = (workspace / "AGENTS.md").read_bytes()
    assert agents.endswith(SIMILARITY_ROLE_CONTRACT)
    assert result.agents_sha256 == sha256_bytes(agents)
    assert result.materialized_member_count == 9
    assert result.plan_sha256 == case["plan"].plan_sha256
    assert result.evidence_manifest_sha256 == case["manifest"]["manifest_sha256"]
    ((session, arguments),) = case["resolution_calls"]
    assert session is case["session"]
    assert arguments["original_source"].model_dump(mode="json") == case["original_source"]
    assert arguments["context"] is case["bound"]
    assert arguments["step_key"] == role
    if tier == "ESCALATED":
        review = next(step for step in case["plan"].steps if step.role == "review")
        assert result.model == review.escalation_candidate.model
        assert result.reasoning_effort == review.escalation_candidate.reasoning_effort
    assert _parse_review_escalation_plan(case["plan"].model_dump(mode="json")) == case["plan"]


@pytest.mark.parametrize("operation", ("allowlist", "workspace"))
def test_context_is_mandatory_before_reference_disclosure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    case = workspace_case(tmp_path, monkeypatch)
    workspace = _workspace(tmp_path, "missing-reader")
    with pytest.raises(ControlPlaneError) as captured:
        if operation == "allowlist":
            authorized_execution_artifact_revisions(
                case["session"], plan_id=case["plan_id"], step_key="authoring"
            )
        else:
            materialize(case, workspace, similarity_context=None)
    assert captured.value.code == "CONTROL_SIMILARITY_AUTHORITY_UNAVAILABLE"
    assert not (workspace / "references").exists()
    assert not case["resolution_calls"]


@pytest.mark.parametrize("role", ("authoring", "review", "image", "item_management"))
def test_only_authoring_and_review_receive_the_auxiliary_member_allowlist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, role: str
) -> None:
    case = workspace_case(tmp_path, monkeypatch)
    if role in {"image", "item_management"}:
        raw = case["plan"].model_dump(mode="json")
        raw["steps"].append(
            raw["steps"][0] | {"step_key": role, "role": role, "evidence_access": "NONE"}
        )
        plan = parse_similarity_execution_plan(seal(raw, "plan_sha256"))
        record = case["session"].records[(ResolvedExecutionPlanRecord, case["plan_id"])]
        record.canonical_document = plan.model_dump(mode="json")
        record.plan_sha256 = plan.plan_sha256
    allowlist = authorized_execution_artifact_revisions(
        case["session"],
        plan_id=case["plan_id"],
        step_key=role,
        similarity_context=case["bound"] if role in {"authoring", "review"} else None,
    )
    pin = case["plan"].similarity_delivery.context_member
    assert (pin.artifact_revision_id in allowlist) == (role in {"authoring", "review"})
    if role in {"image", "item_management"}:
        workspace = _workspace(tmp_path, "unrelated")
        materialize(case, workspace, step_key=role, similarity_context=None)
        assert not (workspace / SIMILARITY_WORKSPACE_ALIAS).exists()
        assert not (workspace / SIMILARITY_MATERIALS_WORKSPACE_ALIAS).exists()
        assert SIMILARITY_ROLE_CONTRACT not in (workspace / "AGENTS.md").read_bytes()
    assert not case["resolution_calls"]


def test_failed_current_resolution_does_not_create_auxiliary_file_or_agents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = workspace_case(tmp_path, monkeypatch)

    def denied(*args, **kwargs):
        raise ControlPlaneError("CONTROL_SIMILARITY_AUTHORITY_DENIED", "synthetic revocation")

    monkeypatch.setattr(module, "resolve_similarity_materials", denied)
    workspace = _workspace(tmp_path, "revoked")
    with pytest.raises(ControlPlaneError) as captured:
        materialize(case, workspace)
    assert captured.value.code == "CONTROL_SIMILARITY_AUTHORITY_DENIED"
    assert not (workspace / SIMILARITY_WORKSPACE_ALIAS).exists()
    assert not (workspace / "AGENTS.md").exists()
