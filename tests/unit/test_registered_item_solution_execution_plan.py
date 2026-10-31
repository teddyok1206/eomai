"""Pinned plan resolution and real local file integrity, without a live database or model."""

from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from eom_catalog_contracts import (
    KnowledgeAnalysisProposalReceipt,
    KnowledgeAnalysisRequestV2,
    KnowledgeAnalysisRequestV11,
    KnowledgeAnalysisResultV2,
)
from eom_catalog_contracts.knowledge import (
    KnowledgeProposalArtifactMember,
    knowledge_proposal_member_set_sha256,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_orchestrator.control_models import ExecutionPresetRecord, ExecutionPresetRevisionRecord
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.execution_materializer import _materialize_base_analysis
from eom_orchestrator.execution_resolver import resolve_knowledge_analysis_plan
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord
from eom_workflow import ResolvedExecutionPlanV29
from eom_workflow.control_schemas import validate_control_contract
from pydantic import ValidationError

from tests.unit.test_content_team_v3_protocol import _content_v3
from tests.unit.test_execution_resolver import _preset
from tests.unit.test_registered_item_solution_analysis_candidate_schemas import request_value
from tests.unit.test_registered_item_solution_analysis_models import result_value

NOW = datetime(2026, 10, 31, tzinfo=UTC)


def plan_value(request=None):
    request = request or request_value()
    policy = deepcopy(_preset()["role_policies"][0])
    policy.update(role="support", worker_pool_key="support", reference_bundle=None)
    step = {key: value for key, value in policy.items() if key != "model_candidates"}
    step.update(
        step_key="analyze", general_knowledge_mode="DENIED", **policy["model_candidates"][0]
    )
    value = dict(
        schema_version="resolved-execution-plan/29.0",
        plan_id="execplan_" + "1" * 32,
        workflow_id="workflow_" + "2" * 32,
        workload_class="KNOWLEDGE_ANALYSIS",
        preset_id=request["execution_preset_id"],
        preset_revision_id=request["execution_preset_revision_id"],
        preset_sha256=request["execution_preset_sha256"],
        workflow_definition_key="knowledge-analysis",
        workflow_definition_version="11.0.0",
        workflow_definition_sha256="sha256:" + "3" * 64,
        analysis_request_id=request["analysis_request_id"],
        analysis_request_sha256=request["request_sha256"],
        item_source=request["source"],
        base_analysis=request["base_analysis"],
        capacity_policy_revision_id="capacityrev_" + "4" * 32,
        steps=[step],
        resolver_version="29.0.0",
        resolved_at=NOW.isoformat().replace("+00:00", "Z"),
    )
    return value | {"plan_sha256": content_sha256(value)}


def test_registered_plan_is_its_own_closed_source_family_not_a_visual_exam_plan():
    value = plan_value()
    validate_control_contract("resolved-execution-plan-v29", value)
    parsed = ResolvedExecutionPlanV29.model_validate(value)
    assert parsed.base_analysis.analysis_run_id == request_value()["predecessor_analysis_run_id"]
    assert parsed.item_source.source_class == "APPROVED_ITEM"
    changed = deepcopy(value)
    changed["item_source"]["source_class"] = "PAST_EXAM"
    changed["plan_sha256"] = content_sha256(
        {key: item for key, item in changed.items() if key != "plan_sha256"}
    )
    with pytest.raises(ValidationError):
        ResolvedExecutionPlanV29.model_validate(changed)


@pytest.mark.parametrize(
    "field,value",
    [
        ("workflow_id", "workflow_" + "0" * 32),
        ("preset_id", "execpreset_" + "0" * 32),
        ("preset_revision_id", "execpresetrev_" + "0" * 32),
        ("preset_sha256", "sha256:" + "0" * 64),
    ],
)
def test_registered_plan_replay_cannot_substitute_other_execution_pins(field, value):
    document = plan_value()
    original_workflow = document["workflow_id"]
    document[field] = value
    document["plan_sha256"] = content_sha256(
        {key: item for key, item in document.items() if key != "plan_sha256"}
    )
    session = Mock()
    session.scalar.return_value = NS(canonical_document=document)
    with pytest.raises(ControlPlaneError, match="stored registered solution plan differs"):
        resolve_knowledge_analysis_plan(
            session,
            workflow_id=original_workflow,
            workflow_definition_version=document["workflow_definition_version"],
            workflow_definition_sha256=document["workflow_definition_sha256"],
            workflow_role_schema_version="workflow-role/1.35.0",
            request=KnowledgeAnalysisRequestV11.model_validate(request_value()),
        )
    session.get.assert_not_called()


def test_resolver_creates_and_replays_one_exact_registered_plan_without_latest_lookup():
    document = deepcopy(_preset())
    document["role_policies"][0].update(
        role="support", worker_pool_key="support", reference_bundle=None
    )
    document["compatible_workflow_protocols"] = ["workflow-role/1.35.0"]
    document["content_sha256"] = content_sha256(
        {key: item for key, item in document.items() if key != "content_sha256"}
    )
    request_document = request_value() | {
        "execution_preset_id": document["preset_id"],
        "execution_preset_revision_id": document["preset_revision_id"],
        "execution_preset_sha256": document["content_sha256"],
    }
    request_document["request_sha256"] = content_sha256(
        {key: item for key, item in request_document.items() if key != "request_sha256"}
    )
    request = KnowledgeAnalysisRequestV11.model_validate(request_document)
    revision = NS(
        canonical_document=document,
        **{
            name: document[name]
            for name in ("preset_id", "state", "content_sha256", "compatible_workflow_protocols")
        },
    )
    session = Mock()
    session.scalar.return_value = None
    session.get.side_effect = lambda model, key: (
        revision
        if model is ExecutionPresetRevisionRecord
        else NS(preset_id=document["preset_id"])
        if model is ExecutionPresetRecord
        else None
    )
    options = dict(
        workflow_id="workflow_" + "2" * 32,
        workflow_definition_version="11.0.0",
        workflow_definition_sha256="sha256:" + "3" * 64,
        workflow_role_schema_version="workflow-role/1.35.0",
        request=request,
        resolved_at=NOW,
    )
    parsed = resolve_knowledge_analysis_plan(session, **options)
    assert isinstance(parsed, ResolvedExecutionPlanV29)
    assert parsed.base_analysis == request.base_analysis
    assert parsed.item_source == request.source
    assert session.add.call_count == 2
    replay = Mock()
    replay.scalar.return_value = NS(canonical_document=parsed.model_dump(mode="json"))
    assert resolve_knowledge_analysis_plan(replay, **options) == parsed
    replay.get.assert_not_called()
    replay.add.assert_not_called()
    changed = request.model_dump(mode="json")
    changed["source"]["artifact_member"]["sha256"] = "sha256:" + "0" * 64
    changed["request_sha256"] = content_sha256(
        {key: item for key, item in changed.items() if key != "request_sha256"}
    )
    with pytest.raises(ControlPlaneError, match="stored registered solution plan differs"):
        resolve_knowledge_analysis_plan(
            replay, **(options | {"request": KnowledgeAnalysisRequestV11.model_validate(changed)})
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("workflow_definition_version", "10.0.0"),
        ("workflow_role_schema_version", "workflow-role/1.21.0"),
    ],
)
def test_old_definition_or_protocol_is_rejected_before_any_plan_lookup(field, value):
    session = Mock()
    options = dict(
        workflow_id="workflow_" + "2" * 32,
        workflow_definition_version="11.0.0",
        workflow_definition_sha256="sha256:" + "3" * 64,
        workflow_role_schema_version="workflow-role/1.35.0",
        request=KnowledgeAnalysisRequestV11.model_validate(request_value()),
    )
    with pytest.raises(ControlPlaneError, match="exact admitted definition/protocol"):
        resolve_knowledge_analysis_plan(session, **(options | {field: value}))
    session.scalar.assert_not_called()


def base_files(tmp_path: Path):
    root, workspace = tmp_path / "artifacts", tmp_path / "workspace"
    root.mkdir(parents=True)
    workspace.mkdir(mode=0o750)
    request = request_value()
    base = request["base_analysis"]
    records = {}

    def store(pointer, payload):
        directory = root / pointer["artifact_id"] / pointer["artifact_revision_id"]
        target = directory / pointer["member_path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        pointer.update(bytes=len(payload), sha256=sha256_bytes(payload))
        records[(ArtifactRecord, pointer["artifact_id"])] = NS(
            approved=True, logical_artifact_id=pointer["artifact_id"]
        )
        revision_key = (ArtifactRevisionRecord, pointer["artifact_revision_id"])
        revision = records.setdefault(
            revision_key,
            NS(
                approved=True,
                logical_artifact_id=pointer["artifact_id"],
                nas_path=str(directory),
                manifest={"files": []},
            ),
        )
        revision.manifest["files"].append(
            dict(
                file_name=pointer["member_path"],
                bytes=len(payload),
                sha256=pointer["sha256"],
                media_type=pointer["media_type"],
                schema_ref=pointer["schema_ref"],
            )
        )

    source_value = _content_v3().model_dump(mode="json")
    source_value["stem"] = "조건"
    source_value["explanations"]["correct_answer"] = "해설"
    request["source"]["artifact_member"]["schema_ref"] = "eom.assessment.item-content/3.0"
    store(request["source"]["artifact_member"], canonical_json_bytes(source_value))
    base_request_value = {key: value for key, value in request.items() if key != "base_analysis"}
    base_request_value.update(
        schema_version="knowledge-analysis-request/2.0",
        analysis_request_id=base["analysis_request_id"],
        predecessor_analysis_run_id=None,
        worker_proposal_schema_ref="eom://schemas/knowledge/knowledge-analysis-worker-proposal/1.0",
        accepted_result_schema_ref="eom://schemas/knowledge/knowledge-analysis-result/2.0",
        requested_outputs=[
            "NORMALIZED_MARKDOWN",
            "SOURCE_ANCHORS",
            "NODES",
            "EDGES",
            "CLAIMS",
            "COMPONENT_OBSERVATIONS",
            "UNRESOLVED_AMBIGUITIES",
        ],
    )
    base_request_value["request_sha256"] = content_sha256(
        {key: value for key, value in base_request_value.items() if key != "request_sha256"}
    )
    base_request = KnowledgeAnalysisRequestV2.model_validate(base_request_value)

    # Actual JSONL rows, including legitimate empty optional member sets.
    rows = dict(
        anchors=[
            dict(
                anchor_id=key,
                artifact_revision_id=request["source"]["artifact_member"]["artifact_revision_id"],
                member_path=request["source"]["artifact_member"]["member_path"],
                anchor_kind="ITEM_ELEMENT",
                locator="/stem" if key == "anchor_problem" else "/explanations/correct_answer",
                excerpt_sha256=content_sha256("조건" if key == "anchor_problem" else "해설"),
            )
            for key in base["reference_index"]["anchor_ids"]
        ],
        nodes=[
            dict(
                node_id=node["node_id"],
                node_type=node["node_type"],
                stable_key="test." + node["node_id"],
                label=node["node_type"],
                anchor_ids=["anchor_problem"],
            )
            for node in base["reference_index"]["nodes"]
        ],
        edges=[],
        claims=[],
        component_observations=[],
        unresolved_ambiguities=[],
    )
    for name, pointer in base["base_members"].items():
        payload = (
            b"# Source\n"
            if name == "normalized_markdown"
            else b"".join(canonical_json_bytes(row) + b"\n" for row in rows[name])
        )
        store(pointer, payload)
    base["base_counts"].update(edges=0, claims=0, component_observations=0, ambiguities=0)
    base["proposal_content_set_sha256"] = knowledge_proposal_member_set_sha256(
        tuple(
            KnowledgeProposalArtifactMember.model_validate(row)
            for row in base["base_members"].values()
        )
    )
    receipt = KnowledgeAnalysisProposalReceipt.model_validate(
        dict(
            schema_version="knowledge-analysis-proposal-receipt/1.0",
            analysis_request_id=base["analysis_request_id"],
            source=request["source"],
            members=base["base_members"],
            counts=base["base_counts"],
            general_knowledge_used=False,
            blocking_ambiguity_count=0,
            content_set_sha256=base["proposal_content_set_sha256"],
            completed_at=NOW,
        )
    )
    store(base["proposal_receipt"], canonical_json_bytes(receipt.model_dump(mode="json")))
    accepted = result_value()
    accepted.pop("base_analysis")
    accepted.pop("solution_counts")
    accepted.update(
        schema_version="knowledge-analysis-result/2.0",
        analysis_result_id=base["analysis_result_id"],
        analysis_request_id=base["analysis_request_id"],
        analysis_request_sha256=base_request.request_sha256,
        source=request["source"],
        proposal_receipt=base["proposal_receipt"],
        counts=base["base_counts"],
        proposal_content_set_sha256=base["proposal_content_set_sha256"],
    )
    accepted["result_sha256"] = content_sha256(
        {key: value for key, value in accepted.items() if key != "result_sha256"}
    )
    validated = KnowledgeAnalysisResultV2.model_validate(accepted)
    base["accepted_result_sha256"] = validated.result_sha256
    store(base["accepted_result_artifact"], canonical_json_bytes(validated.model_dump(mode="json")))
    accepted_pointer = base["accepted_result_artifact"]
    accepted_revision = records[(ArtifactRevisionRecord, accepted_pointer["artifact_revision_id"])]
    accepted_revision.result = validated.model_dump(mode="json")
    accepted_revision.content_hash = accepted_pointer["sha256"]
    accepted_revision.content_bytes = accepted_pointer["bytes"]
    accepted_revision.manifest.update(
        artifact_type="knowledge-analysis-accepted-result",
        primary_file="evidence/accepted-result.json",
    )
    request["request_sha256"] = content_sha256(
        {key: value for key, value in request.items() if key != "request_sha256"}
    )
    plan = ResolvedExecutionPlanV29.model_validate(plan_value(request))
    session = Mock()
    session.get.side_effect = lambda model, key: records.get((model, key))
    return NS(
        plan=plan,
        session=session,
        root=root,
        workspace=workspace,
        base_request=base_request,
        base_receipt=receipt,
        accepted_revision=accepted_revision,
    )


def test_real_registered_base_materialization_keeps_original_7_member_shape_and_empty_sets(
    tmp_path,
):
    import os

    fixture = base_files(tmp_path)
    allowed = frozenset(
        {
            fixture.plan.base_analysis.accepted_result_artifact.artifact_revision_id,
            fixture.plan.base_analysis.proposal_receipt.artifact_revision_id,
        }
    )
    size, count = _materialize_base_analysis(
        fixture.session,
        plan=fixture.plan,
        workspace=fixture.workspace,
        artifact_root=fixture.root,
        worker_group_id=os.getgid(),
        authorized_artifact_revision_ids=allowed,
    )
    assert size > 0 and count == 9
    assert not (fixture.workspace / "source/base-analysis/page-images.jsonl").exists()
    assert (fixture.workspace / "source/base-analysis/edges.jsonl").read_bytes() == b""


def test_base_materialization_never_dereferences_an_unapproved_revision_or_repairs_bad_bytes(
    tmp_path,
):
    import os

    fixture = base_files(tmp_path)
    arguments = dict(
        plan=fixture.plan,
        workspace=fixture.workspace,
        artifact_root=fixture.root,
        worker_group_id=os.getgid(),
    )
    with pytest.raises(ControlPlaneError, match="not authorized"):
        _materialize_base_analysis(
            fixture.session, **arguments, authorized_artifact_revision_ids=frozenset()
        )
    fixture = base_files(tmp_path / "tamper")
    pointer = fixture.plan.base_analysis.accepted_result_artifact
    (
        fixture.root / pointer.artifact_id / pointer.artifact_revision_id / pointer.member_path
    ).write_bytes(b"{}")
    with pytest.raises(ControlPlaneError):
        _materialize_base_analysis(
            fixture.session,
            plan=fixture.plan,
            workspace=fixture.workspace,
            artifact_root=fixture.root,
            worker_group_id=os.getgid(),
            authorized_artifact_revision_ids=frozenset({pointer.artifact_revision_id}),
        )
