"""Source registration preserves discrepancies and their immutable evidence."""

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.creative_source_lineage import CreativeSourceLineage
from eom_catalog_contracts.external_item_learning_authorization import (
    ExternalItemLearningRoleSelection,
)
from eom_catalog_contracts.external_item_learning_result import ExternalItemLearningResult
from eom_catalog_contracts.external_item_learning_work import ExternalItemLearningWorkInput
from eom_catalog_service import creative_registered_report as reports
from eom_catalog_service.creative_item_registration import CreativeItemRegistrationService
from eom_catalog_service.creative_learning_proposal import ResolvedCreativeLearningProposal
from eom_catalog_service.creative_source_content import materialize_creative_source_content
from eom_identifiers import content_sha256
from eom_protocol.artifact_members import ArtifactMemberPointer
from jsonschema import ValidationError as SchemaError
from sqlalchemy.orm import Session

from tests.unit.test_creative_source_content import _disagreement
from tests.unit.test_external_item_learning_work_contract import _work


def proposal():
    work = ExternalItemLearningWorkInput.model_validate(_work())
    result = ExternalItemLearningResult.model_validate(_disagreement())
    selection = ExternalItemLearningRoleSelection(
        workflow_id="workflow_" + "a" * 32,
        step_run_id="steprun_" + "b" * 32,
        plan_id="execplan_" + "c" * 32,
        plan_sha256="sha256:" + "d" * 64,
        work_input_sha256=work.request_sha256,
    )
    role = SimpleNamespace(
        completed_at=datetime(2026, 10, 28, tzinfo=UTC),
        output=SimpleNamespace(learning_result=result),
    )
    pointer = ArtifactMemberPointer(
        artifact_id="artifact_" + "e" * 32,
        artifact_revision_id="rev_" + "f" * 32,
        member_path="result.json",
        sha256="sha256:" + "9" * 64,
        schema_ref="external-item-learning-result@1.0",
        media_type="application/json",
    )
    resolved = ResolvedCreativeLearningProposal(
        selection, "operator_" + "a" * 32, work, role, pointer
    )
    lineage = CreativeItemRegistrationService._lineage(
        resolved, materialize_creative_source_content(result)
    )
    return resolved, lineage


def registered_fixture(monkeypatch):
    resolved, lineage = proposal()
    components = [
        SimpleNamespace(
            component_type="ITEM_CONTENT", ordinal=0, sha256=lineage.registered_content_sha256
        ),
        SimpleNamespace(
            component_type="SOURCE_REFERENCE",
            ordinal=0,
            schema_ref="eom://schemas/external-item/creative-source-lineage/1.0",
            artifact_id="artifact_" + "1" * 32,
            artifact_revision_id="rev_" + "2" * 32,
            sha256=content_sha256(lineage.model_dump(mode="json")),
            media_type="application/json",
            logical_name="lineage.json",
        ),
        SimpleNamespace(
            component_type="REVIEW_REPORT",
            ordinal=0,
            artifact_id=resolved.pointer.artifact_id,
            artifact_revision_id=resolved.pointer.artifact_revision_id,
            sha256=resolved.pointer.sha256,
            schema_ref=resolved.pointer.schema_ref,
            logical_name="result.json",
            media_type="application/json",
        ),
    ]
    revision = SimpleNamespace(
        item_revision_id="itemrev_" + "3" * 32,
        workflow_id=resolved.selection.workflow_id,
        source_workflow_step_run_id=resolved.selection.step_run_id,
        metadata_json={
            "source_kind": "CREATIVE",
            "source_id": lineage.source_id,
            "source_revision_id": lineage.source_revision_id,
            "external_number": lineage.external_number,
            "lineage_sha256": lineage.lineage_sha256,
        },
    )
    session = Mock(spec=Session)
    session.scalars.return_value = components
    artifacts = Mock()
    artifacts.read_member.return_value = lineage.model_dump_json().encode()
    monkeypatch.setattr(
        reports, "resolve_completed_creative_learning_proposal", lambda *args: resolved
    )
    return session, artifacts, revision, components, resolved, lineage


def test_lineage_schema_mirror_and_deterministic_content_hash():
    resolved, lineage = proposal()
    assert lineage == CreativeItemRegistrationService._lineage(
        resolved, materialize_creative_source_content(resolved.role.output.learning_result)
    )
    root = Path(__file__).resolve().parents[2]
    name = "external-item/creative-source-lineage-v1.schema.json"
    assert (root / "schemas" / name).read_bytes() == (
        root / "packages/catalog_contracts/eom_catalog_contracts/resources" / name
    ).read_bytes()


def test_read_exposes_disagreement_original_status_and_all_steps(monkeypatch):
    session, artifacts, revision, _, _, _ = registered_fixture(monkeypatch)
    report = reports.load_registered_creative_report(session, artifacts, revision)
    text = report.context_text()
    assert "ANSWER_DISAGREEMENT" in text and "NEEDS_DECISION" in text
    assert "choice_1" in text and "답: 3" in text
    assert "정확성 보장" in text and "solution_steps" in text
    with pytest.raises(reports.CreativeRegisteredReportError, match="CONTEXT_TOO_LARGE"):
        report.context_text(maximum_chars=10)


@pytest.mark.parametrize(
    "field", ["source_id", "source_revision_id", "external_number", "lineage_sha256"]
)
def test_report_rejects_cross_source_metadata(monkeypatch, field):
    session, artifacts, revision, _, _, _ = registered_fixture(monkeypatch)
    revision.metadata_json[field] = "wrong"
    with pytest.raises(reports.CreativeRegisteredReportError, match="LINEAGE_MISMATCH"):
        reports.load_registered_creative_report(session, artifacts, revision)


@pytest.mark.parametrize("component_index", [0, 2])
def test_report_rejects_changed_content_or_result_hash(monkeypatch, component_index):
    session, artifacts, revision, components, _, _ = registered_fixture(monkeypatch)
    components[component_index].sha256 = "sha256:" + "0" * 64
    with pytest.raises(reports.CreativeRegisteredReportError, match="LINEAGE_MISMATCH"):
        reports.load_registered_creative_report(session, artifacts, revision)


def test_report_requires_exact_components_and_propagates_bounded_artifact_failure(monkeypatch):
    session, artifacts, revision, components, _, _ = registered_fixture(monkeypatch)
    artifacts.read_member.side_effect = ValueError("HASH_MISMATCH")
    with pytest.raises(ValueError, match="HASH_MISMATCH"):
        reports.load_registered_creative_report(session, artifacts, revision)
    components.pop()
    with pytest.raises(reports.CreativeRegisteredReportError, match="COMPONENT_INVALID"):
        reports.load_registered_creative_report(session, artifacts, revision)


def test_lineage_hash_and_unique_warning_validation():
    _, lineage = proposal()
    value = lineage.model_dump(mode="json")
    value["external_number"] = "99999"
    with pytest.raises(ValueError, match="hash differs"):
        CreativeSourceLineage.model_validate(value)
    value["warning_codes"] *= 2
    value["lineage_sha256"] = content_sha256(
        {key: entry for key, entry in value.items() if key != "lineage_sha256"}
    )
    with pytest.raises((ValueError, SchemaError)):
        CreativeSourceLineage.model_validate(value)
