"""Successor registration preserves source answers, independent work and warnings."""

import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.external_item_learning_result_v2 import ExternalItemLearningResultV2
from eom_catalog_service import creative_registered_report as reports
from eom_catalog_service.content_pack_files import compile_pack
from eom_catalog_service.creative_item_registration import CreativeItemRegistrationService
from eom_catalog_service.creative_source_content import materialize_creative_source_content_v2
from eom_identifiers import content_sha256
from eom_workflow.schemas import validate_role_result

from tests.unit.test_creative_learning_protocol_v2 import role_result
from tests.unit.test_creative_registered_report import registered_fixture


def v2_registered(monkeypatch):
    session, artifacts, revision, components, resolved, _ = registered_fixture(monkeypatch)
    role = role_result()
    value = role["output"]["learning_result"]
    source = resolved.work.source
    for field in ("source_id", "source_revision_id", "external_number"):
        value[field] = getattr(source, field)
    value["input_sha256"] = source.input_sha256
    value["status"] = "NEEDS_DECISION"
    value["solution_report"]["answer_labels"] = ["2"]
    value["solution_report"]["answer_cross_check"] = "DISAGREES"
    value["conflicts"] = [
        {
            "conflict_code": "ANSWER_DISAGREEMENT",
            "description": "독립 답안과 편집 답안 불일치",
            "source_region_ids": value["solution_report"]["editorial_region_ids"],
            "blocking": True,
        }
    ]
    parsed_role = validate_role_result(role, "support", "external-item-learning-result@2.0")
    resolved = replace(
        resolved,
        role=parsed_role,
        pointer=resolved.pointer.model_copy(
            update={"schema_ref": "external-item-learning-result@2.0"}
        ),
    )
    result = resolved.role.output.learning_result
    assert isinstance(result, ExternalItemLearningResultV2)
    content = materialize_creative_source_content_v2(result, resolved_images={})
    lineage = CreativeItemRegistrationService._lineage(resolved, content)
    components[0].sha256 = content.registered_content_sha256
    components[1].sha256 = content_sha256(lineage.model_dump(mode="json"))
    components[2].schema_ref = resolved.pointer.schema_ref
    revision.metadata_json.update(
        lineage_id=lineage.lineage_id, lineage_sha256=lineage.lineage_sha256
    )
    artifacts.read_member.return_value = lineage.model_dump_json().encode()
    monkeypatch.setattr(
        reports, "resolve_completed_creative_learning_proposal", lambda *args: resolved
    )
    return session, artifacts, revision, components, resolved, lineage, content


def test_native_source_answer_is_not_replaced_by_independent_disagreement(monkeypatch):
    *_, resolved, lineage, content = v2_registered(monkeypatch)
    original = resolved.role.output.learning_result
    assert original.status == "NEEDS_DECISION" and original.conflicts[0].blocking
    assert content.content.solution.correct_choice_ids == ("choice_1",)
    assert original.solution_report.answer_labels == ("2",)
    assert content.content.score.points == 0
    assert lineage.source_answer_mode == "EDITORIAL_SOURCE"
    assert lineage.warning_codes == ("ANSWER_DISAGREEMENT", "SOURCE_SCORE_NOT_PRINTED")
    assert content.proposed_content_sha256 == content_sha256(
        original.proposal.content.model_dump(mode="json")
    )
    assert content.registered_content_sha256 == content_sha256(
        content.content.model_dump(mode="json")
    )


def test_official_report_exposes_original_and_independent_answers_with_all_issues(monkeypatch):
    session, artifacts, revision, _, resolved, lineage, _ = v2_registered(monkeypatch)
    report = reports.load_registered_creative_report(session, artifacts, revision)
    text = json.loads(report.context_text())
    assert text["report_kind"] == "CREATIVE_SOURCE_SOLUTION_AND_WARNINGS_V2"
    assert text["source_score_state"] == "UNPRINTED"
    assert text["source_solution"]["correct_choice_ids"] == ["choice_1"]
    assert text["independent_proposal_answer"] == ["2"]
    assert text["original_proposal_status"] == "NEEDS_DECISION"
    assert text["warning_codes"] == list(lineage.warning_codes)
    result = resolved.role.output.learning_result
    assert text["issues"] == [entry.model_dump(mode="json") for entry in result.conflicts]
    assert text["solution_steps"] == [
        step.model_dump(mode="json") for step in result.solution_report.solution_steps
    ]


def test_missing_score_warning_is_not_silently_interpreted_as_printed_zero(monkeypatch):
    session, artifacts, revision, components, _, lineage, _ = v2_registered(monkeypatch)
    value = lineage.model_dump(mode="json")
    value["warning_codes"].remove("SOURCE_SCORE_NOT_PRINTED")
    value["lineage_sha256"] = content_sha256(
        {k: v for k, v in value.items() if k != "lineage_sha256"}
    )
    artifacts.read_member.return_value = json.dumps(value).encode()
    components[1].sha256 = content_sha256(value)
    revision.metadata_json["lineage_sha256"] = value["lineage_sha256"]
    with pytest.raises(reports.CreativeRegisteredReportError, match="SOURCE_MISMATCH"):
        reports.load_registered_creative_report(session, artifacts, revision)


def test_report_context_never_silently_truncates_the_disagreement(monkeypatch):
    session, artifacts, revision, *_ = v2_registered(monkeypatch)
    report = reports.load_registered_creative_report(session, artifacts, revision)
    with pytest.raises(reports.CreativeRegisteredReportError, match="CONTEXT_TOO_LARGE"):
        report.context_text(maximum_chars=64)


def test_non_visual_registration_does_not_read_pdf_or_request_crop(monkeypatch):
    _, _, _, _, resolved, _, expected = v2_registered(monkeypatch)
    service = object.__new__(CreativeItemRegistrationService)
    service.artifacts = Mock()
    service.publisher = Mock()
    assert service._prepare_successor_content(resolved) == expected
    service.artifacts.read_member.assert_not_called()
    service.publisher.publish_first_observation.assert_not_called()


def test_successor_pack_preserves_metadata_and_admits_only_the_two_explicit_families():
    root = Path(__file__).resolve().parents[2] / "content/packs/external-creative-item"
    previous = compile_pack(root / "1.0.0")
    successor = compile_pack(root / "1.1.0")
    assert previous.manifest.pack.version == "1.0.0"
    assert successor.manifest.pack.version == "1.1.0"
    assert successor.manifest.compatibility.workflow_definitions[0].versions == ("1.0.0", "2.0.0")
    assert previous.manifest.compatibility.workflow_definitions[0].versions == ("1.0.0",)
    for relative in (
        "metadata-schemas/item-metadata.schema.json",
        "item-types/external-creative-multiple-choice.yaml",
    ):
        assert (root / "1.0.0" / relative).read_bytes() == (root / "1.1.0" / relative).read_bytes()
