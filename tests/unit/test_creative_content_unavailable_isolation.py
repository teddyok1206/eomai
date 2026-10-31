"""Allowed worker absence remains canonical; it cannot starve independent sources."""

from contextlib import nullcontext
from dataclasses import replace
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.external_item_learning_result import ExternalItemLearningResult
from eom_catalog_service import creative_item_registration as registration
from eom_catalog_service.creative_item_registration import (
    CreativeItemContentUnavailable,
    CreativeItemRegistrationService,
)
from eom_identifiers import content_sha256
from eom_workflow.schemas import validate_role_result

from tests.unit.test_creative_parallel_execution import driver_case
from tests.unit.test_creative_registered_report import proposal
from tests.unit.test_creative_registration_v2 import v2_registered


def unavailable(monkeypatch, version=2):
    resolved = v2_registered(monkeypatch)[4] if version == 2 else proposal()[0]
    result = resolved.role.output.learning_result.model_dump(mode="json")
    result.pop("result_sha256")
    result["proposal"] = None
    result["status"] = "NEEDS_DECISION"
    if version == 2:
        raw = resolved.role.model_dump(mode="json")
        raw["output"]["learning_result"] = result
        parsed = validate_role_result(raw, "support", "external-item-learning-result@2.0")
    else:
        result["result_sha256"] = content_sha256(result)
        parsed = NS(output=NS(learning_result=ExternalItemLearningResult.model_validate(result)))
    return replace(resolved, role=parsed)


@pytest.mark.parametrize("version", (1, 2))
def test_authorized_missing_content_is_classified_before_any_registration_write(
    monkeypatch, version
):
    resolved = unavailable(monkeypatch, version)
    session = NS(scalar=Mock(return_value=None))
    service = object.__new__(CreativeItemRegistrationService)
    service.sessions = Mock(return_value=nullcontext(session))
    service.sessions.begin = Mock(side_effect=AssertionError("registration write"))
    service.artifacts = Mock()
    service._authorize = Mock()
    service._prepare_successor_content = Mock(side_effect=AssertionError("invented source"))
    monkeypatch.setattr(
        registration, "resolve_completed_creative_learning_proposal", lambda *_: resolved
    )
    with pytest.raises(CreativeItemContentUnavailable) as caught:
        service.register_completed(
            resolved.selection, requested_by_operator_id=resolved.operator_id
        )
    issue = caught.value
    assert issue.code == "CREATIVE_SOURCE_ITEM_UNREADABLE"
    assert issue.target.source_id == resolved.work.source.source_id
    assert issue.report == resolved.pointer and issue.selection == resolved.selection
    service._authorize.assert_called_once_with(session, resolved, resolved.operator_id)
    service.sessions.begin.assert_not_called()


@pytest.mark.parametrize("version", (1, 2))
def test_permission_denial_is_not_reclassified_as_source_absence(monkeypatch, version):
    resolved = unavailable(monkeypatch, version)
    service = object.__new__(CreativeItemRegistrationService)
    service.sessions = Mock(return_value=nullcontext(NS()))
    service.artifacts = Mock()
    service._authorize = Mock(side_effect=ValueError("SOURCE_PERMISSION_DENIED"))
    monkeypatch.setattr(
        registration, "resolve_completed_creative_learning_proposal", lambda *_: resolved
    )
    with pytest.raises(ValueError, match="SOURCE_PERMISSION_DENIED"):
        service.register_completed(
            resolved.selection, requested_by_operator_id=resolved.operator_id
        )


def test_source_absence_is_not_verified_but_other_targets_finish_once(monkeypatch):
    resolved = unavailable(monkeypatch)
    issue = CreativeItemContentUnavailable(resolved)
    case = driver_case(monkeypatch, count=11)
    target = case.targets[0]
    issue.target = target
    attempted = []

    def advance(source):
        attempted.append(source.target.source_id)
        if source.target == target:
            source.selection = issue.selection
            raise issue
        source.state = "READY_TO_PUBLISH"

    case.owner.advance_report.side_effect = advance
    for _ in range(12):
        result = case.driver.advance_once()
        if case.executor.pending:
            case.executor.complete()
        if result.state == "BLOCKED_SOURCES":
            break
    assert result.state == "BLOCKED_SOURCES" and result.verified_count == 10
    assert result.blocked_sources == ((target.external_number, issue.code),)
    assert len(attempted) == len(set(attempted)) == 11
    case.driver.close()


@pytest.mark.parametrize("fault", ("target", "selection"))
def test_foreign_unavailable_report_cannot_skip_a_different_target(monkeypatch, fault):
    issue = CreativeItemContentUnavailable(unavailable(monkeypatch))
    case = driver_case(monkeypatch)

    def advance(source):
        if fault == "selection":
            issue.target = source.target
        else:
            source.selection = issue.selection
        raise issue

    case.owner.advance_report.side_effect = advance
    with pytest.raises(ValueError, match="CONTENT_RESULT_IDENTITY_MISMATCH"):
        case.driver.advance_once()
    assert not case.driver.blocked and case.driver.verified_count == 0
    case.driver.close()
