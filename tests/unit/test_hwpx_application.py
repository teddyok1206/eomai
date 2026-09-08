from __future__ import annotations

import os
import re
import stat
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from eom_catalog_contracts import MockExamAssemblyManifestV1, MockExamAssemblyManifestV2
from eom_hwpx_contracts import (
    CONTENT_TEAM_HANDOFF_MEMBERS,
    ContentTeamBuildResultV3,
    ContentTeamHandoffMember,
    ContentTeamHandoffSnapshot,
)
from eom_hwpx_manager import capability as capability_module
from eom_hwpx_manager import runner
from eom_hwpx_manager.application_adapter import (
    WORKSPACE_DIRECTORY_MODE,
    WORKSPACE_FILE_MODE,
    WORKSPACE_ROOT_MODE,
    FixedContentTeamBuilderAdapter,
    FixedKordocBuilderAdapter,
    FixedQuestionTemplateBuilderAdapter,
)
from eom_hwpx_manager.application_service import HwpxApplicationService
from eom_hwpx_manager.application_state import (
    ApplicationBuildState,
    require_application_transition,
)
from eom_hwpx_manager.assembly_render_projection import project_assembly_for_render
from eom_hwpx_manager.capability import HwpxCapabilityService
from eom_hwpx_manager.content_team_exam_service import ContentTeamExamBuildReceipt
from eom_hwpx_manager.content_team_service import ArtifactMemberPointer, ContentTeamHwpxService
from eom_hwpx_manager.errors import HwpxManagerError, HwpxManagerErrorCode
from eom_hwpx_manager.exam_application_service import (
    ExamHwpxApplicationService,
    ExamRecoveryResult,
    ExamRecoveryState,
)
from eom_hwpx_manager.markdown_structure import inspect_markdown_structure
from eom_hwpx_manager.settings import HwpxSettings
from eom_identifiers import content_sha256, sha256_file


def _v2_manifest() -> MockExamAssemblyManifestV2:
    planned_at = "2026-09-08T05:00:00Z"
    usage_value: dict[str, Any] = {
        "schema_version": "mock-exam-usage-snapshot/1.0",
        "captured_at": planned_at,
        "candidate_revision_count": 1,
        "usage_record_count": 0,
        "usage_records_sha256": content_sha256([]),
    }
    usage_sha256 = content_sha256(usage_value)
    usage = usage_value | {
        "usage_snapshot_id": "usagesnapshot_" + usage_sha256.removeprefix("sha256:")[:32],
        "snapshot_sha256": usage_sha256,
    }
    placement = {
        "slot_id": "slot-01",
        "position": 1,
        "display_number": "1",
        "item_id": "item_" + "1" * 32,
        "item_revision_id": "itemrev_" + "2" * 32,
        "item_manifest_sha256": "sha256:" + "3" * 64,
        "graph_item_node_id": "knode_" + "4" * 32,
        "graph_analysis_run_id": "analysisrun_" + "5" * 32,
        "graph_source_class": "APPROVED_ITEM",
        "graph_occurrence_placement_node_id": None,
        "curriculum_unit_keys": ["eom.is.middle.1-1"],
        "large_unit_key": "eom.is.large.1",
        "points_milli": 2000,
        "coverage_role": "BALANCE",
        "coverage_requirement_id": None,
        "coverage_unit_key": None,
        "is_inquiry": False,
        "item_type_key": "multiple-choice",
        "difficulty_band": "MEDIUM",
        "material_profile": "TEXT",
        "source_score_display": "2",
        "content": {
            "item_component_id": "itemcomponent_" + "6" * 32,
            "artifact_id": "artifact_" + "7" * 32,
            "artifact_revision_id": "rev_" + "8" * 32,
            "member_path": "assessment-item-content.json",
            "schema_ref": "eom.assessment.item-content/2.0",
            "media_type": "application/json",
            "sha256": "sha256:" + "9" * 64,
            "editorial_markdown_member": "content-team-item.md",
            "editorial_markdown_sha256": "sha256:" + "a" * 64,
        },
        "review": {
            "item_review_record_id": "itemreview_" + "b" * 32,
            "review_artifact_id": "artifact_" + "c" * 32,
            "review_artifact_revision_id": "rev_" + "d" * 32,
            "review_sha256": "sha256:" + "e" * 64,
            "decision": "APPROVE",
            "final_rating": "A",
        },
        "usage_count": 0,
        "latest_usage_at": None,
        "usage_fingerprint_sha256": content_sha256(
            {"item_revision_id": "itemrev_" + "2" * 32, "records": []}
        ),
        "selection_reason_sha256": "sha256:" + "f" * 64,
    }
    validation = {
        "item_count": 1,
        "total_points_milli": 2000,
        "score_distribution": {"2000": 1},
        "required_slot_count": 0,
        "balance_slot_count": 1,
        "inquiry_count": 0,
        "coverage_requirement_ids": [],
        "major_unit_counts": {"eom.is.large.1": 1},
    }
    plan_value: dict[str, Any] = {
        "schema_version": "mock-exam-assembly-plan/1.0",
        "status": "READY",
        "policy_revision_id": "assemblypolicyrev_" + "1" * 32,
        "policy_sha256": "sha256:" + "2" * 64,
        "layout_policy_revision_id": "layoutpolicyrev_" + "3" * 32,
        "layout_policy_sha256": "sha256:" + "4" * 64,
        "rating_policy_revision_id": "ratingpolicyrev_" + "5" * 32,
        "rating_policy_sha256": "sha256:" + "6" * 64,
        "graph_snapshot_revision_id": "graphrev_" + "7" * 32,
        "graph_snapshot_sha256": "sha256:" + "8" * 64,
        "usage_snapshot": usage,
        "resolved_candidate_count": 1,
        "rated_candidate_count": 1,
        "placements": [placement],
        "shortages": [],
        "validation": validation,
        "search_visited_nodes": 1,
        "planned_at": planned_at,
    }
    plan_value["plan_sha256"] = content_sha256(plan_value)
    manifest_value: dict[str, Any] = {
        "schema_version": "mock-exam-assembly-manifest/2.0",
        "assessment_assembly_revision_id": "assemblyrev_" + "9" * 32,
        "assessment_assembly_id": "assembly_" + "a" * 32,
        "assessment_form_id": "form_" + "b" * 32,
        "assessment_form_revision_id": "formrev_" + "c" * 32,
        "deliverable_id": "deliverable_" + "d" * 32,
        "deliverable_revision_id": "delivrev_" + "e" * 32,
        "form_key": "main",
        "display_label": "본시험지",
        "plan": plan_value,
        "revision_state": "RELEASED",
        "created_at": planned_at,
        "created_by": "operator_" + "f" * 32,
    }
    manifest_value["manifest_sha256"] = content_sha256(manifest_value)
    return MockExamAssemblyManifestV2.model_validate(manifest_value)


def _v1_manifest() -> MockExamAssemblyManifestV1:
    created_at = "2026-09-08T05:00:00Z"
    placement = {
        "placement_id": "placement_" + "1" * 32,
        "position": 1,
        "display_number": "1",
        "item_id": "item_" + "2" * 32,
        "item_revision_id": "itemrev_" + "3" * 32,
        "item_manifest_sha256": "sha256:" + "4" * 64,
        "graph_placement_node_id": "knode_" + "5" * 32,
        "curriculum_unit_keys": ["eom.is.middle.1-1"],
        "major_unit_key": "eom.is.large.1",
        "points_milli": 2000,
        "coverage_role": "BALANCE",
        "coverage_requirement_id": None,
        "is_inquiry": False,
        "material_type": "TEXT",
        "item_type_key": "multiple-choice",
        "difficulty_band": "MEDIUM",
        "review_annotation_sha256": "sha256:" + "6" * 64,
    }
    value: dict[str, Any] = {
        "schema_version": "mock-exam-assembly-manifest/1.0",
        "assessment_assembly_revision_id": "assemblyrev_" + "7" * 32,
        "assessment_assembly_id": "assembly_" + "8" * 32,
        "assessment_form_id": "form_" + "9" * 32,
        "assessment_form_revision_id": "formrev_" + "a" * 32,
        "deliverable_id": "deliverable_" + "b" * 32,
        "deliverable_revision_id": "delivrev_" + "c" * 32,
        "policy_revision_id": "assemblypolicyrev_" + "d" * 32,
        "policy_sha256": "sha256:" + "e" * 64,
        "outline_key": "integrated-science",
        "outline_revision": "1",
        "outline_sha256": "sha256:" + "f" * 64,
        "graph_snapshot_revision_id": "graphrev_" + "1" * 32,
        "graph_snapshot_sha256": "sha256:" + "2" * 64,
        "placements": [placement],
        "validation": {
            "item_count": 1,
            "total_points_milli": 2000,
            "score_distribution": {"2000": 1},
            "required_slot_count": 0,
            "balance_slot_count": 1,
            "inquiry_count": 0,
            "coverage_requirement_ids": [],
            "major_unit_counts": {"eom.is.large.1": 1},
        },
        "revision_state": "RELEASED",
        "created_at": created_at,
        "created_by": "operator_" + "3" * 32,
    }
    value["manifest_sha256"] = content_sha256(value)
    return MockExamAssemblyManifestV1.model_validate(value)


def test_capability_is_prepared_when_runtime_is_absent(tmp_path: Path) -> None:
    service = HwpxCapabilityService(HwpxSettings(builder_binary=tmp_path / "missing"))
    value = service.inspect()
    assert value.state == "PREPARED_NOT_DEPLOYED"
    assert value.detail_code == "HWPX_BUILDER_NOT_DEPLOYED"


def test_capability_ready_requires_fixed_version_offline_and_manager(tmp_path: Path) -> None:
    binary = tmp_path / "eom-hwpx"
    binary.write_text(
        "#!/bin/sh\nprintf '%s\\n' "
        '\'{"status":"READY","node_major":22,"kordoc_version":"4.9.0",'
        '"offline_required":true}\'\n',
        encoding="utf-8",
    )
    binary.chmod(0o755)
    ready = HwpxCapabilityService(
        HwpxSettings(builder_binary=binary),
        isolation_preflight=lambda: (True, "HWPX_ISOLATED_BUILDER_READY"),
    ).inspect()
    assert ready.state == "READY"
    assert ready.native_equations and ready.native_tables
    unregistered = HwpxCapabilityService(
        HwpxSettings(builder_binary=binary),
        manager_registered=False,
        isolation_preflight=lambda: (True, "HWPX_ISOLATED_BUILDER_READY"),
    ).inspect()
    assert unregistered.state == "DEGRADED"
    assert unregistered.detail_code == "HWPX_MANAGER_NOT_REGISTERED"

    not_deployed = HwpxCapabilityService(
        HwpxSettings(builder_binary=binary),
        isolation_preflight=lambda: (False, "HWPX_ISOLATED_BUILDER_NOT_DEPLOYED"),
    ).inspect()
    assert not_deployed.state == "PREPARED_NOT_DEPLOYED"
    assert not_deployed.detail_code == "HWPX_ISOLATED_BUILDER_NOT_DEPLOYED"


def test_capability_mismatch_is_degraded_and_sanitized(tmp_path: Path) -> None:
    binary = tmp_path / "eom-hwpx"
    binary.write_text("#!/bin/sh\nprintf 'not-json SECRET_VALUE\\n'\n", encoding="utf-8")
    binary.chmod(0o755)
    value = HwpxCapabilityService(HwpxSettings(builder_binary=binary)).inspect()
    assert value.state == "DEGRADED"
    assert "SECRET" not in value.detail_code


def test_capability_rejects_end_of_life_node_20(tmp_path: Path) -> None:
    binary = tmp_path / "eom-hwpx"
    binary.write_text(
        "#!/bin/sh\nprintf '%s\\n' "
        '\'{"status":"READY","node_major":20,"kordoc_version":"4.9.0",'
        '"offline_required":true}\'\n',
        encoding="utf-8",
    )
    binary.chmod(0o755)

    value = HwpxCapabilityService(HwpxSettings(builder_binary=binary)).inspect()

    assert value.state == "DEGRADED"
    assert value.detail_code == "HWPX_CAPABILITY_INTEGRITY_MISMATCH"


def test_capability_rejects_symlink_and_oversized_response(tmp_path: Path) -> None:
    target = tmp_path / "builder-target"
    target.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    target.chmod(0o755)
    link = tmp_path / "eom-hwpx"
    link.symlink_to(target)
    assert HwpxCapabilityService(HwpxSettings(builder_binary=link)).inspect().state == "DEGRADED"
    target.write_text(
        "#!/bin/sh\nprintf '%020000d' 0\n",
        encoding="utf-8",
    )
    value = HwpxCapabilityService(HwpxSettings(builder_binary=target)).inspect()
    assert value.state == "DEGRADED"
    assert value.detail_code == "HWPX_CAPABILITY_RESPONSE_INVALID"


def test_isolation_preflight_rejects_non_root_or_wrong_mode_units(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    builder = tmp_path / "eom-hwpx-kordoc@.service"
    question_builder = tmp_path / "eom-hwpx-builder@.service"
    content_team_builder = tmp_path / "eom-hwpx-content-team@.service"
    runner_unit = tmp_path / "eom-hwpx-application-runner.service"
    builder.write_text(
        "\n".join(sorted(capability_module.REQUIRED_BUILDER_DIRECTIVES)) + "\n",
        encoding="utf-8",
    )
    runner_unit.write_text(
        "\n".join(sorted(capability_module.REQUIRED_RUNNER_DIRECTIVES)) + "\n",
        encoding="utf-8",
    )
    builder.chmod(0o644)
    question_builder.write_text(
        "\n".join(sorted(capability_module.REQUIRED_QUESTION_TEMPLATE_BUILDER_DIRECTIVES)) + "\n",
        encoding="utf-8",
    )
    question_builder.chmod(0o644)
    content_team_builder.write_text(
        "\n".join(sorted(capability_module.REQUIRED_CONTENT_TEAM_BUILDER_DIRECTIVES)) + "\n",
        encoding="utf-8",
    )
    content_team_builder.chmod(0o644)
    runner_unit.chmod(0o644)
    monkeypatch.setattr(capability_module, "BUILDER_UNIT_PATH", builder)
    monkeypatch.setattr(
        capability_module,
        "QUESTION_TEMPLATE_BUILDER_UNIT_PATH",
        question_builder,
    )
    monkeypatch.setattr(
        capability_module,
        "CONTENT_TEAM_BUILDER_UNIT_PATH",
        content_team_builder,
    )
    monkeypatch.setattr(capability_module, "RUNNER_UNIT_PATH", runner_unit)
    monkeypatch.setattr(capability_module, "SYSTEMCTL", Path("/usr/bin/true"))

    assert capability_module.fixed_builder_isolation_preflight() == (
        False,
        "HWPX_ISOLATED_BUILDER_LAYOUT_INVALID",
    )

    runner_unit.chmod(0o600)
    assert capability_module.fixed_builder_isolation_preflight() == (
        False,
        "HWPX_ISOLATED_BUILDER_LAYOUT_INVALID",
    )


def test_markdown_native_structure_inventory_and_required_bounds() -> None:
    value = inspect_markdown_structure(
        b"# Item\n\n$$x = v_0 t$$\n\n| A | B |\n| --- | --- |\n| 1 | 2 |\n"
    )
    assert value.native_equation_count == 1
    assert value.native_table_count == 1
    with pytest.raises(HwpxManagerError):
        inspect_markdown_structure(b"")


def test_application_build_transition_table_fails_closed() -> None:
    require_application_transition(ApplicationBuildState.REQUESTED, ApplicationBuildState.RUNNING)
    require_application_transition(ApplicationBuildState.RUNNING, ApplicationBuildState.VALIDATING)
    require_application_transition(
        ApplicationBuildState.VALIDATING, ApplicationBuildState.SUCCEEDED
    )
    with pytest.raises(RuntimeError):
        require_application_transition(
            ApplicationBuildState.REQUESTED, ApplicationBuildState.SUCCEEDED
        )


@pytest.mark.parametrize("initial", ("RUNNING", "VALIDATING"))
def test_interrupted_assessment_build_is_terminalized_without_retry(initial: str) -> None:
    completed_at = datetime(2026, 9, 8, tzinfo=UTC)
    record = SimpleNamespace(
        state=initial,
        validation_state="PENDING",
        failure_code=None,
        failure_detail_sanitized=None,
        completed_at=None,
        resource_version=3,
    )

    ExamHwpxApplicationService._terminalize_interrupted(cast(Any, record), completed_at)

    assert record.state == "FAILED"
    assert record.validation_state == "FAIL"
    assert record.failure_code == "HWPX_BUILD_INTERRUPTED"
    assert record.completed_at == completed_at
    assert record.resource_version == 4


def test_interrupted_assessment_build_accepts_only_a_completed_immutable_receipt() -> None:
    completed_at = datetime(2026, 9, 8, tzinfo=UTC)
    record = SimpleNamespace(
        build_id="hwpxbuild_" + "2" * 32,
        state="RUNNING",
        assessment_assembly_revision_id="assemblyrev_" + "1" * 32,
        assembly_manifest_sha256="sha256:" + "7" * 64,
        item_set_sha256="sha256:" + "8" * 64,
        renderer_version="2.0.0",
        validation_state="PENDING",
        platform_job_id=None,
        item_count=25,
        section_count=None,
        native_equation_count=None,
        native_table_count=None,
        visual_count=None,
        output_artifact_id=None,
        output_artifact_revision_id=None,
        output_sha256=None,
        output_filename=None,
        completed_at=None,
        resource_version=2,
    )
    receipt = ContentTeamExamBuildReceipt(
        build_id="hwpxbuild_" + "2" * 32,
        job_id="job_" + "3" * 32,
        renderer_version="2.0.0",
        assessment_assembly_revision_id="assemblyrev_" + "1" * 32,
        assembly_manifest_sha256="sha256:" + "7" * 64,
        item_set_sha256="sha256:" + "8" * 64,
        artifact_id="artifact_" + "4" * 32,
        artifact_revision_id="rev_" + "5" * 32,
        output_sha256="sha256:" + "6" * 64,
        item_count=25,
        section_count=25,
        native_equation_count=12,
        native_table_count=8,
        visual_count=7,
    )

    ExamHwpxApplicationService._complete_build(cast(Any, record), receipt, completed_at)

    assert record.state == "SUCCEEDED"
    assert record.validation_state == "PASS"
    assert record.platform_job_id == receipt.job_id
    assert record.item_count == record.section_count == 25
    assert record.output_artifact_revision_id == receipt.artifact_revision_id
    assert record.completed_at == completed_at
    assert record.resource_version == 3

    mismatch = SimpleNamespace(**record.__dict__)
    mismatch.state = "RUNNING"
    mismatch.validation_state = "PENDING"
    mismatch.resource_version = 3
    with pytest.raises(RuntimeError, match="admitted Item set"):
        ExamHwpxApplicationService._complete_build(
            cast(Any, mismatch),
            ContentTeamExamBuildReceipt(
                **(receipt.__dict__ | {"section_count": receipt.section_count - 1})
            ),
            completed_at,
        )


def test_secure_download_fd_rejects_hash_mismatch_and_directory(tmp_path: Path) -> None:
    output = tmp_path / "output.hwpx"
    output.write_bytes(b"HWPX_TEST_BYTES")
    expected = sha256_file(output)
    fd = HwpxApplicationService._verified_fd(output, expected)
    try:
        assert os.read(fd, 4) == b"HWPX"
    finally:
        os.close(fd)
    with pytest.raises(HwpxManagerError):
        HwpxApplicationService._verified_fd(output, "sha256:" + "0" * 64)
    with pytest.raises(HwpxManagerError):
        HwpxApplicationService._verified_fd(tmp_path, expected)


def test_artifact_primary_file_rejects_traversal_and_symlink(tmp_path: Path) -> None:
    root = tmp_path / "artifact"
    root.mkdir()
    output = root / "document.hwpx"
    output.write_bytes(b"HWPX")
    revision = SimpleNamespace(nas_path=str(root), manifest={"primary_file": "document.hwpx"})
    assert HwpxApplicationService._primary_file(revision) == output  # type: ignore[arg-type]
    escaped = SimpleNamespace(nas_path=str(root), manifest={"primary_file": "../escape.hwpx"})
    with pytest.raises(HwpxManagerError):
        HwpxApplicationService._primary_file(escaped)  # type: ignore[arg-type]
    output.unlink()
    output.symlink_to(tmp_path / "elsewhere.hwpx")
    with pytest.raises(HwpxManagerError):
        HwpxApplicationService._primary_file(revision)  # type: ignore[arg-type]


def test_download_filename_is_ascii_and_fixed_extension() -> None:
    value = HwpxApplicationService._safe_filename("문항 item_01.hwpx")
    assert value.endswith(".hwpx")
    assert value.isascii()
    assert "/" not in value and "\\" not in value and ".." not in value


def test_markdown_component_requires_one_typed_pinned_pointer() -> None:
    component: dict[str, Any] = {
        "schema_ref": "eom.hwpx.markdown-document",
        "media_type": "text/markdown; charset=utf-8",
        "artifact_id": "artifact_" + "a" * 32,
        "artifact_revision_id": "rev_" + "b" * 32,
        "sha256": "sha256:" + "c" * 64,
    }
    assert HwpxApplicationService._markdown_component({"components": [component]}) == component
    with pytest.raises(HwpxManagerError):
        HwpxApplicationService._markdown_component({"components": []})
    with pytest.raises(HwpxManagerError):
        HwpxApplicationService._markdown_component({"components": [component, component]})


@pytest.mark.parametrize(
    ("schema_ref", "expected_renderer"),
    [
        ("eom.assessment.item-content/1.0", "eom-template"),
        ("eom.assessment.item-content/2.0", "content-team"),
    ],
)
def test_automatic_renderer_resolves_from_one_canonical_item_component(
    schema_ref: str, expected_renderer: str
) -> None:
    component: dict[str, Any] = {
        "component_type": "ITEM_CONTENT",
        "ordinal": 0,
        "schema_ref": schema_ref,
        "media_type": "application/json",
        "artifact_id": "artifact_" + "a" * 32,
        "artifact_revision_id": "rev_" + "b" * 32,
        "sha256": "sha256:" + "c" * 64,
    }

    renderer, resolved = HwpxApplicationService._resolve_build_source(
        {"components": [component]}, "auto"
    )

    assert renderer == expected_renderer
    assert resolved is component


def test_automatic_renderer_rejects_missing_or_mixed_canonical_sources() -> None:
    first = {
        "component_type": "ITEM_CONTENT",
        "ordinal": 0,
        "schema_ref": "eom.assessment.item-content/1.0",
        "media_type": "application/json",
    }
    second = first | {"schema_ref": "eom.assessment.item-content/2.0"}

    with pytest.raises(HwpxManagerError, match="exactly one automatic"):
        HwpxApplicationService._resolve_build_source({"components": []}, "auto")
    with pytest.raises(HwpxManagerError, match="exactly one automatic"):
        HwpxApplicationService._resolve_build_source({"components": [first, second]}, "auto")


def test_content_team_image_components_become_ordered_pinned_sources() -> None:
    image = {
        "component_type": "IMAGE",
        "ordinal": 1,
        "schema_ref": "eom://schemas/generated-item/stimulus-png/3.0",
        "media_type": "image/png",
        "artifact_id": "artifact_" + "a" * 32,
        "artifact_revision_id": "rev_" + "b" * 32,
        "sha256": "sha256:" + "c" * 64,
        "metadata": {
            "artifact_member": "generated-stimulus.png",
            "label": "(나)",
            "width_px": 800,
            "height_px": 500,
            "alt_text": "오른쪽에 배치할 교과서형 자료 그림",
        },
    }

    sources = HwpxApplicationService._content_team_image_sources({"components": [image]})

    assert sources == [
        {
            "visual_ordinal": 1,
            "label": "(나)",
            "artifact_id": image["artifact_id"],
            "artifact_revision_id": image["artifact_revision_id"],
            "artifact_member": "generated-stimulus.png",
            "sha256": image["sha256"],
            "schema_ref": image["schema_ref"],
            "media_type": "image/png",
            "width_px": 800,
            "height_px": 500,
            "alt_text": "오른쪽에 배치할 교과서형 자료 그림",
            "file_name": "input/visual-1.png",
        }
    ]
    with pytest.raises(HwpxManagerError, match="ordinals are ambiguous"):
        HwpxApplicationService._content_team_image_sources({"components": [image, image]})


def test_runner_returns_sanitized_failure_without_traceback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class FakeEngine:
        def dispose(self) -> None:
            pass

    class FailingService:
        def __init__(self, _engine: object, **_kwargs: object) -> None:
            pass

        def process_next(self) -> None:
            raise HwpxManagerError(
                HwpxManagerErrorCode.HWPX_KORDOC_SOURCE_INVALID,
                "SECRET_SOURCE_PATH",
            )

    class IdleExamService:
        def __init__(self, _engine: object, **_kwargs: object) -> None:
            pass

        @staticmethod
        def recover_interrupted() -> ExamRecoveryResult:
            return ExamRecoveryResult(ExamRecoveryState.NONE)

    monkeypatch.setattr(runner, "build_engine", FakeEngine)
    monkeypatch.setattr(runner, "_runtime_privileges_ready", lambda _engine: True)
    monkeypatch.setattr(runner, "_runtime_staging_ready", lambda _path: True)
    monkeypatch.setattr(runner, "RegistryService", lambda _engine: object())
    monkeypatch.setattr(runner, "HwpxApplicationService", FailingService)
    monkeypatch.setattr(runner, "ExamHwpxApplicationService", IdleExamService)

    assert runner.run_once() == 1
    captured = capsys.readouterr()
    assert "HWPX_KORDOC_SOURCE_INVALID" in captured.err
    assert "SECRET_SOURCE_PATH" not in captured.err
    assert "Traceback" not in captured.err


def test_runner_processes_assessment_queue_after_item_queue_is_idle(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class FakeEngine:
        def dispose(self) -> None:
            pass

    class IdleItemService:
        def __init__(self, _engine: object, **_kwargs: object) -> None:
            pass

        @staticmethod
        def process_next() -> None:
            return None

    class AssessmentService:
        def __init__(self, _engine: object, **_kwargs: object) -> None:
            pass

        @staticmethod
        def recover_interrupted() -> ExamRecoveryResult:
            return ExamRecoveryResult(ExamRecoveryState.NONE)

        @staticmethod
        def process_next() -> SimpleNamespace:
            return SimpleNamespace(build_id="hwpxbuild_" + "1" * 32, state="SUCCEEDED")

    monkeypatch.setattr(runner, "build_engine", FakeEngine)
    monkeypatch.setattr(runner, "_runtime_privileges_ready", lambda _engine: True)
    monkeypatch.setattr(runner, "_runtime_staging_ready", lambda _path: True)
    monkeypatch.setattr(runner, "RegistryService", lambda _engine: object())
    monkeypatch.setattr(runner, "HwpxApplicationService", IdleItemService)
    monkeypatch.setattr(runner, "ExamHwpxApplicationService", AssessmentService)

    assert runner.run_once() == 0
    assert "hwpxbuild_" + "1" * 32 + ":SUCCEEDED" in capsys.readouterr().out


def test_runner_preference_alternates_queue_precedence(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[str] = []

    class FakeEngine:
        def dispose(self) -> None:
            pass

    class ItemService:
        def __init__(self, _engine: object, **_kwargs: object) -> None:
            pass

        @staticmethod
        def process_next() -> SimpleNamespace:
            calls.append("item")
            return SimpleNamespace(build_id="hwpxbuild_" + "1" * 32, state="SUCCEEDED")

    class AssessmentService:
        def __init__(self, _engine: object, **_kwargs: object) -> None:
            pass

        @staticmethod
        def recover_interrupted() -> ExamRecoveryResult:
            return ExamRecoveryResult(ExamRecoveryState.NONE)

        @staticmethod
        def process_next() -> SimpleNamespace:
            calls.append("assessment")
            return SimpleNamespace(build_id="hwpxbuild_" + "2" * 32, state="SUCCEEDED")

    monkeypatch.setattr(runner, "build_engine", FakeEngine)
    monkeypatch.setattr(runner, "_runtime_privileges_ready", lambda _engine: True)
    monkeypatch.setattr(runner, "_runtime_staging_ready", lambda _path: True)
    monkeypatch.setattr(runner, "RegistryService", lambda _engine: object())
    monkeypatch.setattr(runner, "HwpxApplicationService", ItemService)
    monkeypatch.setattr(runner, "ExamHwpxApplicationService", AssessmentService)

    assert runner.run_once(prefer_exam=False) == 0
    assert calls == ["item"]
    calls.clear()
    assert runner.run_once(prefer_exam=True) == 0
    assert calls == ["assessment"]
    assert "queue=assessment" in capsys.readouterr().out


def test_assessment_build_request_identity_pins_content_team_handoff_revision() -> None:
    manifest = _v2_manifest()
    handoff = ContentTeamHandoffSnapshot(
        artifact_id="artifact_" + "b" * 32,
        artifact_revision_id="rev_" + "c" * 32,
        members=tuple(
            ContentTeamHandoffMember(purpose=purpose, sha256=sha256, size=size)
            for purpose, sha256, size in CONTENT_TEAM_HANDOFF_MEMBERS
        ),
    )

    admitted = ExamHwpxApplicationService._request_sha256(manifest, handoff)
    changed = ExamHwpxApplicationService._request_sha256(
        manifest,
        handoff.model_copy(update={"artifact_revision_id": "rev_" + "d" * 32}),
    )

    assert admitted != changed
    assert admitted == content_sha256(
        {
            **project_assembly_for_render(manifest).request_identity(),
            "renderer": "content-team-exam",
            "renderer_version": "2.0.0",
            "handoff": handoff.model_dump(mode="json"),
        }
    )


def test_v1_assessment_request_hash_remains_backward_compatible() -> None:
    manifest = _v1_manifest()
    handoff = ContentTeamHandoffSnapshot(
        artifact_id="artifact_" + "b" * 32,
        artifact_revision_id="rev_" + "c" * 32,
        members=tuple(
            ContentTeamHandoffMember(purpose=purpose, sha256=sha256, size=size)
            for purpose, sha256, size in CONTENT_TEAM_HANDOFF_MEMBERS
        ),
    )
    projection = project_assembly_for_render(manifest)
    identity = projection.request_identity()

    assert "assembly_schema_version" not in identity
    assert "plan_sha256" not in identity
    assert ExamHwpxApplicationService._request_sha256(manifest, handoff) == content_sha256(
        {
            "assessment_assembly_revision_id": manifest.assessment_assembly_revision_id,
            "assembly_manifest_sha256": manifest.manifest_sha256,
            "policy_revision_id": manifest.policy_revision_id,
            "policy_sha256": manifest.policy_sha256,
            "graph_snapshot_revision_id": manifest.graph_snapshot_revision_id,
            "graph_snapshot_sha256": manifest.graph_snapshot_sha256,
            "item_set_sha256": projection.item_set_sha256(),
            "renderer": "content-team-exam",
            "renderer_version": "1.0.0",
            "handoff": handoff.model_dump(mode="json"),
        }
    )


def test_v2_assembly_render_projection_preserves_plan_and_content_pointers() -> None:
    manifest = _v2_manifest()
    projection = project_assembly_for_render(manifest)
    placement = projection.placements[0]
    expected_placement_id = (
        "placement_"
        + content_sha256(
            {
                "assessment_assembly_revision_id": manifest.assessment_assembly_revision_id,
                "slot_id": "slot-01",
                "item_revision_id": "itemrev_" + "2" * 32,
            }
        ).removeprefix("sha256:")[:32]
    )

    assert projection.schema_version == "mock-exam-assembly-manifest/2.0"
    assert projection.plan_sha256 == manifest.plan.plan_sha256
    assert projection.policy_revision_id == manifest.plan.policy_revision_id
    assert placement.placement_id == expected_placement_id
    assert placement.display_number == "1"
    assert placement.points_milli == 2000
    assert placement.content == manifest.plan.placements[0].content
    assert projection.request_identity()["item_set_sha256"] == projection.item_set_sha256()


def test_v2_assembly_item_resolution_uses_and_cross_checks_direct_content_pointer() -> None:
    manifest = _v2_manifest()
    planned = manifest.plan.placements[0]
    component = {
        "item_component_id": planned.content.item_component_id,
        "component_type": "ITEM_CONTENT",
        "ordinal": 0,
        "logical_name": planned.content.member_path,
        "artifact_id": planned.content.artifact_id,
        "artifact_revision_id": planned.content.artifact_revision_id,
        "sha256": planned.content.sha256,
        "schema_ref": planned.content.schema_ref,
        "media_type": planned.content.media_type,
        "required": True,
        "metadata": {
            "editorial_markdown_member": planned.content.editorial_markdown_member,
            "editorial_markdown_sha256": planned.content.editorial_markdown_sha256,
        },
    }
    revision = {
        "item_id": planned.item_id,
        "item_revision_id": planned.item_revision_id,
        "manifest_sha256": planned.item_manifest_sha256,
        "revision_state": "APPROVED",
        "components": [component],
    }

    class Registry:
        @staticmethod
        def inspect_revisions(_revision_ids: tuple[str, ...]) -> tuple[dict[str, Any], ...]:
            return (revision,)

    service = object.__new__(ExamHwpxApplicationService)
    service.registry = Registry()  # type: ignore[assignment]
    resolved = service._resolve_items(manifest)

    assert len(resolved) == 1
    assert resolved[0].source.artifact_revision_id == planned.content.artifact_revision_id
    assert resolved[0].source.json_sha256 == planned.content.sha256
    assert resolved[0].display_number == planned.display_number
    assert resolved[0].points_milli == planned.points_milli
    component["artifact_revision_id"] = "rev_" + "0" * 32
    with pytest.raises(HwpxManagerError, match="differs from its Item Revision"):
        service._resolve_items(manifest)


def test_content_team_completed_v3_build_replays_exact_typed_receipt() -> None:
    build_id = "hwpxbuild_" + "1" * 32
    result = ContentTeamBuildResultV3(
        build_id=build_id,
        item_revision_id="itemrev_" + "2" * 32,
        source_artifact_id="artifact_" + "3" * 32,
        source_artifact_revision_id="rev_" + "4" * 32,
        source_json_sha256="sha256:" + "5" * 64,
        source_markdown_sha256="sha256:" + "6" * 64,
        status="SUCCEEDED",
        output_file="output/content-team-item.hwpx",
        output_sha256="sha256:" + "7" * 64,
        package_manifest_file="output/package-manifest.json",
        renderer_report_file="output/content-team-validation.json",
        equation_count=1,
        table_count=2,
        visual_count=0,
        labeled_block_count=0,
        warnings=(),
        errors=(),
        started_at=datetime(2026, 9, 8, tzinfo=UTC),
        completed_at=datetime(2026, 9, 8, 0, 0, 1, tzinfo=UTC),
        image_set_sha256=content_sha256([]),
        embedded_image_count=0,
    )

    class ReplaySession:
        def __init__(self, raw: dict[str, Any]) -> None:
            self.job = SimpleNamespace(
                job_id="job_" + "8" * 32,
                status="SUCCEEDED",
                revision_id="rev_" + "9" * 32,
                logical_artifact_id="artifact_" + "a" * 32,
            )
            self.revision = SimpleNamespace(
                result={
                    "builder_result": raw,
                    "native_equation_count": 1,
                    "native_table_count": 2,
                },
                content_hash="sha256:" + "b" * 64,
            )

        def __enter__(self) -> ReplaySession:
            return self

        def __exit__(self, *_args: object) -> None:
            pass

        def get(self, _model: object, identifier: str) -> SimpleNamespace | None:
            if identifier == self.job.job_id:
                return self.job
            if identifier == self.job.revision_id:
                return self.revision
            return None

    service = object.__new__(ContentTeamHwpxService)
    raw = result.model_dump(mode="json")
    service.sessions = lambda: ReplaySession(raw)  # type: ignore[assignment]

    receipt = service._completed_receipt("job_" + "8" * 32, expected_build_id=build_id)

    assert receipt.build_id == build_id
    assert receipt.output_sha256 == "sha256:" + "b" * 64
    assert receipt.native_equation_count == 1
    assert receipt.native_table_count == 2

    mixed = dict(raw)
    mixed["renderer_version"] = "2.0.0"
    service.sessions = lambda: ReplaySession(mixed)  # type: ignore[assignment]
    with pytest.raises(HwpxManagerError) as error:
        service._completed_receipt("job_" + "8" * 32, expected_build_id=build_id)
    assert error.value.code == HwpxManagerErrorCode.HWPX_RESULT_INVALID


def test_content_team_batch_member_resolver_uses_two_indexed_queries(tmp_path: Path) -> None:
    files: list[Path] = []
    artifacts: list[SimpleNamespace] = []
    revisions: list[SimpleNamespace] = []
    pointers: list[ArtifactMemberPointer] = []
    for index in (1, 2):
        root = tmp_path / str(index)
        root.mkdir()
        member = root / f"member-{index}.json"
        member.write_text(f'{{"index":{index}}}', encoding="utf-8")
        digest = sha256_file(member)
        artifact_id = f"artifact_{index:032x}"
        revision_id = f"rev_{index:032x}"
        files.append(member)
        artifacts.append(SimpleNamespace(logical_artifact_id=artifact_id, approved=True))
        revisions.append(
            SimpleNamespace(
                revision_id=revision_id,
                logical_artifact_id=artifact_id,
                approved=True,
                nas_path=str(root),
                manifest={
                    "files": [
                        {
                            "file_name": member.name,
                            "sha256": digest,
                            "media_type": "application/json",
                            "schema_ref": "eom.test/member/1.0",
                            "bytes": member.stat().st_size,
                        }
                    ]
                },
            )
        )
        pointers.append(
            ArtifactMemberPointer(
                artifact_id=artifact_id,
                revision_id=revision_id,
                member_name=member.name,
                expected_sha256=digest,
                media_type="application/json",
                schema_ref="eom.test/member/1.0",
                max_bytes=1024,
            )
        )

    class BatchSession:
        calls = 0

        def __enter__(self) -> BatchSession:
            return self

        def __exit__(self, *_args: object) -> None:
            pass

        def scalars(self, _statement: object) -> tuple[SimpleNamespace, ...]:
            self.calls += 1
            return tuple(artifacts if self.calls == 1 else revisions)

    session = BatchSession()
    service = object.__new__(ContentTeamHwpxService)
    service.sessions = lambda: session  # type: ignore[assignment]

    assert service._resolve_members(tuple(pointers)) == tuple(files)
    assert session.calls == 2


def test_runner_fails_closed_before_queue_access_when_manager_privileges_are_missing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class FakeEngine:
        def dispose(self) -> None:
            pass

    called = False

    class UnexpectedService:
        def __init__(self, _engine: object, **_kwargs: object) -> None:
            nonlocal called
            called = True

    monkeypatch.setattr(runner, "build_engine", FakeEngine)
    monkeypatch.setattr(runner, "_runtime_privileges_ready", lambda _engine: False)
    monkeypatch.setattr(runner, "HwpxApplicationService", UnexpectedService)

    assert runner.run_once() == 1
    captured = capsys.readouterr()
    assert "HWPX_MANAGER_DATABASE_PRIVILEGES_UNAVAILABLE" in captured.err
    assert "Traceback" not in captured.err
    assert not called


def test_runner_fails_closed_before_queue_access_when_private_staging_is_unavailable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class FakeEngine:
        def dispose(self) -> None:
            pass

    called = False

    class UnexpectedService:
        def __init__(self, _engine: object, **_kwargs: object) -> None:
            nonlocal called
            called = True

    monkeypatch.setattr(runner, "build_engine", FakeEngine)
    monkeypatch.setattr(runner, "_runtime_privileges_ready", lambda _engine: True)
    monkeypatch.setattr(runner, "_runtime_staging_ready", lambda _path: False)
    monkeypatch.setattr(runner, "HwpxApplicationService", UnexpectedService)

    assert runner.run_once() == 1
    captured = capsys.readouterr()
    assert "HWPX_MANAGER_STAGING_UNAVAILABLE" in captured.err
    assert "Traceback" not in captured.err
    assert not called


def test_application_adapter_root_contract_is_private_group_only() -> None:
    metadata = os.stat_result((stat.S_IFDIR | 0o2770, 1, 1, 1, 0, 986, 0, 0, 0, 0))
    assert FixedKordocBuilderAdapter._root_contract_ready(metadata, 986, [986])
    assert not FixedKordocBuilderAdapter._root_contract_ready(metadata, 986, [])
    wrong_mode = os.stat_result((stat.S_IFDIR | 0o2777, 1, 1, 1, 0, 986, 0, 0, 0, 0))
    assert not FixedKordocBuilderAdapter._root_contract_ready(wrong_mode, 986, [986])


def test_application_adapter_proves_fixed_unit_quiescence_or_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = "LoadState=loaded\nActiveState=inactive\n"

    def show_unit(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 0, output, "")

    monkeypatch.setattr("eom_hwpx_manager.application_adapter.subprocess.run", show_unit)
    adapter = FixedContentTeamBuilderAdapter(
        HwpxSettings(workspace_root=tmp_path, timeout_seconds=300)
    )
    build_id = "hwpxbuild_" + "a" * 32
    assert not adapter.build_may_be_active(build_id)

    output = "LoadState=loaded\nActiveState=activating\n"
    assert adapter.build_may_be_active(build_id)
    output = "unexpected"
    assert adapter.build_may_be_active(build_id)
    assert adapter.build_may_be_active("not-a-build-id")


def test_application_adapter_finalizes_private_group_paths_without_setgid(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    target = workspace / "request.json"
    target.write_text("{}", encoding="ascii")

    FixedQuestionTemplateBuilderAdapter._finalize_directory(workspace, os.getgid())
    FixedQuestionTemplateBuilderAdapter._finalize_file(target, os.getgid())

    workspace_metadata = workspace.stat()
    target_metadata = target.stat()
    assert stat.S_IMODE(workspace_metadata.st_mode) == WORKSPACE_DIRECTORY_MODE
    assert workspace_metadata.st_mode & stat.S_ISGID == 0
    assert workspace_metadata.st_gid == os.getgid()
    assert stat.S_IMODE(target_metadata.st_mode) == WORKSPACE_FILE_MODE
    assert target_metadata.st_gid == os.getgid()
    assert target_metadata.st_mode & 0o007 == 0


def test_application_adapter_uses_only_fixed_unit_and_arguments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()
    build_id = "hwpxbuild_" + "a" * 32
    workspace = workspace_root / build_id
    workspace.mkdir()
    workspace.chmod(WORKSPACE_DIRECTORY_MODE)
    log_root = tmp_path / "logs"
    calls: list[list[str]] = []

    def run_fixed(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr("eom_hwpx_manager.application_adapter.subprocess.run", run_fixed)
    adapter = FixedKordocBuilderAdapter(
        HwpxSettings(workspace_root=workspace_root, timeout_seconds=180)
    )
    result = adapter.run(
        workspace,
        "render-kordoc",
        ["--request", "request.json", "--result", "result.json"],
        log_root,
    )
    assert result.exit_code == 0
    assert calls == [
        [
            "/usr/bin/systemctl",
            "--no-ask-password",
            "--wait",
            "start",
            f"eom-hwpx-kordoc@{build_id}.service",
        ]
    ]
    with pytest.raises(HwpxManagerError):
        adapter.run(workspace, "render-kordoc", ["--request", "../../secret"], log_root)
    assert len(calls) == 1


def test_content_team_adapter_uses_only_its_fixed_unit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()
    build_id = "hwpxbuild_" + "b" * 32
    workspace = workspace_root / build_id
    workspace.mkdir()
    workspace.chmod(WORKSPACE_DIRECTORY_MODE)
    calls: list[list[str]] = []

    def run_fixed(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr("eom_hwpx_manager.application_adapter.subprocess.run", run_fixed)
    adapter = FixedContentTeamBuilderAdapter(
        HwpxSettings(workspace_root=workspace_root, timeout_seconds=300)
    )

    result = adapter.run(
        workspace,
        "render-content-team",
        ["--request", "request.json", "--result", "result.json"],
        tmp_path / "logs",
    )

    assert result.exit_code == 0
    assert calls == [
        [
            "/usr/bin/systemctl",
            "--no-ask-password",
            "--wait",
            "start",
            f"eom-hwpx-content-team@{build_id}.service",
        ]
    ]


def test_application_adapter_has_no_transient_or_chown_fallback() -> None:
    source = Path("services/hwpx_manager/eom_hwpx_manager/application_adapter.py").read_text(
        encoding="utf-8"
    )
    unit = Path("infra/systemd/eom-hwpx-kordoc@.service").read_text(encoding="utf-8")
    bootstrap = Path("scripts/hwpx/bootstrap_builder_user.sh").read_text(encoding="utf-8")
    assert "systemd-run" not in source
    assert "os.chown" not in source
    assert "shell=True" not in source
    assert "ExecStart=/srv/eom/conda/envs/eom-hwpx/bin/eom-hwpx render-kordoc" in unit
    assert "CapabilityBoundingSet=" in unit
    assert "UMask=0007" in unit
    assert "UMask=0077" not in unit
    assert "RestrictSUIDSGID=true" in unit
    handoff = Path("services/hwpx_builder/eom_hwpx_builder/handoff.py").read_text(encoding="utf-8")
    assert "HANDOFF_DIRECTORY_MODE = 0o750" in handoff
    assert "HANDOFF_DIRECTORY_MODE = 0o2750" not in handoff
    assert f"-m {WORKSPACE_ROOT_MODE:o} /srv/eom/hwpx-workspaces" in bootstrap


def test_question_template_adapter_uses_only_its_fixed_unit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()
    build_id = "hwpxbuild_" + "b" * 32
    workspace = workspace_root / build_id
    workspace.mkdir()
    workspace.chmod(WORKSPACE_DIRECTORY_MODE)
    calls: list[list[str]] = []

    def run_fixed(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr("eom_hwpx_manager.application_adapter.subprocess.run", run_fixed)
    adapter = FixedQuestionTemplateBuilderAdapter(
        HwpxSettings(workspace_root=workspace_root, timeout_seconds=180)
    )
    result = adapter.run(
        workspace,
        "render",
        ["--request", "request.json", "--result", "result.json"],
        tmp_path / "logs",
    )
    assert result.unit_name == f"eom-hwpx-builder@{build_id}.service"
    assert calls == [
        [
            "/usr/bin/systemctl",
            "--no-ask-password",
            "--wait",
            "start",
            f"eom-hwpx-builder@{build_id}.service",
        ]
    ]
    with pytest.raises(HwpxManagerError):
        adapter.run(workspace, "render-kordoc", ["--request", "request.json"], tmp_path / "logs")
    assert len(calls) == 1


def test_application_runner_separates_manager_state_from_builder_home() -> None:
    unit = Path("infra/systemd/eom-hwpx-application-runner.service").read_text(encoding="utf-8")
    assert "User=eom-hwpx-manager" in unit
    assert "SupplementaryGroups=eom eom-hwpx" in unit
    assert "StateDirectory=eom-hwpx-api" in unit
    assert "StateDirectoryMode=0700" in unit
    assert "WorkingDirectory=/var/lib/eom-hwpx-api" in unit
    assert "Environment=HOME=/var/lib/eom-hwpx-api" in unit
    assert "Environment=EOM_STAGING_ROOT=/var/lib/eom-hwpx-api/staging" in unit
    assert "ReadWritePaths=/var/lib/eom-hwpx-api" in unit
    assert "ReadWritePaths=/srv/eom/staging" not in unit
    assert "InaccessiblePaths=/var/lib/eom-hwpx" in unit
    assert "WorkingDirectory=/var/lib/eom-hwpx\n" not in unit


def test_runner_private_staging_preflight_fails_closed(tmp_path: Path) -> None:
    staging = tmp_path / "staging"

    assert runner._runtime_staging_ready(staging)
    assert stat.S_IMODE(staging.stat().st_mode) == 0o700

    staging.chmod(0o750)
    assert not runner._runtime_staging_ready(staging)

    staging.chmod(0o700)
    staging.rmdir()
    staging.symlink_to(tmp_path)
    assert not runner._runtime_staging_ready(staging)


def test_builder_bootstrap_group_matcher_uses_closed_exact_names() -> None:
    bootstrap = Path("scripts/hwpx/bootstrap_builder_user.sh").read_text(encoding="utf-8")
    match = re.search(r"^FORBIDDEN_GROUP_PATTERN='([^']+)'$", bootstrap, re.MULTILINE)
    assert match is not None
    pattern = re.compile(match.group(1))

    for allowed in ("eom-hwpx", "eom-api", "eom-cdx", "eom-cdx-admin"):
        assert pattern.fullmatch(allowed) is None
    for forbidden in ("sudo", "docker", "eom", "eom-cdx-01", "eom-cdx-999"):
        assert pattern.fullmatch(forbidden) is not None
