from __future__ import annotations

import re
from datetime import UTC, datetime

import pytest
from eom_identifiers import (
    canonical_json_bytes,
    content_sha256,
    new_auth_binding_id,
    new_capability_snapshot_id,
    new_capacity_policy_id,
    new_capacity_policy_revision_id,
    new_codex_control_command_id,
    new_execution_plan_id,
    new_execution_preset_evaluation_id,
    new_execution_preset_id,
    new_execution_preset_revision_id,
    new_hwpx_build_id,
    new_hwpx_template_id,
    new_hwpx_template_revision_id,
    new_hwpx_validation_id,
    new_instruction_bundle_id,
    new_instruction_bundle_revision_id,
    new_job_id,
    new_knowledge_analysis_decision_id,
    new_knowledge_analysis_request_id,
    new_knowledge_analysis_result_id,
    new_knowledge_analysis_run_id,
    new_logical_artifact_id,
    new_reference_bundle_id,
    new_reference_bundle_revision_id,
    new_revision_id,
    new_worker_lease_id,
)


def test_ids_have_distinct_namespaces() -> None:
    assert re.fullmatch(r"job_[0-9a-f]{32}", new_job_id())
    assert re.fullmatch(r"artifact_[0-9a-f]{32}", new_logical_artifact_id())
    assert re.fullmatch(r"rev_[0-9a-f]{32}", new_revision_id())
    assert re.fullmatch(r"hwpxtpl_[0-9a-f]{32}", new_hwpx_template_id())
    assert re.fullmatch(r"hwpxrev_[0-9a-f]{32}", new_hwpx_template_revision_id())
    assert re.fullmatch(r"hwpxbuild_[0-9a-f]{32}", new_hwpx_build_id())
    assert re.fullmatch(r"hwpxval_[0-9a-f]{32}", new_hwpx_validation_id())
    assert re.fullmatch(r"instrbundle_[0-9a-f]{32}", new_instruction_bundle_id())
    assert re.fullmatch(r"instrrev_[0-9a-f]{32}", new_instruction_bundle_revision_id())
    assert re.fullmatch(r"refbundle_[0-9a-f]{32}", new_reference_bundle_id())
    assert re.fullmatch(r"refrev_[0-9a-f]{32}", new_reference_bundle_revision_id())
    assert re.fullmatch(r"execpreset_[0-9a-f]{32}", new_execution_preset_id())
    assert re.fullmatch(r"execpresetrev_[0-9a-f]{32}", new_execution_preset_revision_id())
    assert re.fullmatch(r"capacity_[0-9a-f]{32}", new_capacity_policy_id())
    assert re.fullmatch(r"capacityrev_[0-9a-f]{32}", new_capacity_policy_revision_id())
    assert re.fullmatch(r"execplan_[0-9a-f]{32}", new_execution_plan_id())
    assert re.fullmatch(r"authbinding_[0-9a-f]{32}", new_auth_binding_id())
    assert re.fullmatch(r"capsnap_[0-9a-f]{32}", new_capability_snapshot_id())
    assert re.fullmatch(r"workerlease_[0-9a-f]{32}", new_worker_lease_id())
    assert re.fullmatch(r"codexcmd_[0-9a-f]{32}", new_codex_control_command_id())
    assert re.fullmatch(r"preseteval_[0-9a-f]{32}", new_execution_preset_evaluation_id())
    assert re.fullmatch(r"knowledgeanalysis_[0-9a-f]{32}", new_knowledge_analysis_request_id())
    assert re.fullmatch(r"analysisrun_[0-9a-f]{32}", new_knowledge_analysis_run_id())
    assert re.fullmatch(r"knowledgeanalysisresult_[0-9a-f]{32}", new_knowledge_analysis_result_id())
    assert re.fullmatch(r"analysisdecision_[0-9a-f]{32}", new_knowledge_analysis_decision_id())


def test_canonical_serialization_and_hash_are_stable() -> None:
    first = {"b": 2, "a": [True, "한글"], "at": datetime(2026, 8, 15, tzinfo=UTC)}
    second = {"at": datetime(2026, 8, 15, tzinfo=UTC), "a": [True, "한글"], "b": 2}
    assert canonical_json_bytes(first) == canonical_json_bytes(second)
    assert content_sha256(first) == content_sha256(second)
    assert content_sha256(first).startswith("sha256:")


def test_canonical_serialization_rejects_floats() -> None:
    with pytest.raises(TypeError, match="floats"):
        canonical_json_bytes({"unsafe": 1.5})
