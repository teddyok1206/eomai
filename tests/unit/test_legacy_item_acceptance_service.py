from __future__ import annotations

from contextlib import nullcontext
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

from eom_catalog_contracts import (
    AssessmentArtifactMemberPointer,
    LegacyExtractionResultPointer,
    LegacyItemExtractionAcceptance,
    LegacyItemExtractionResult,
)
from eom_catalog_service.artifacts import CatalogArtifact
from eom_catalog_service.legacy_assessment_registry import LegacyAssessmentRegistration
from eom_catalog_service.legacy_item_acceptance_service import (
    AUTOMATIC_ACCEPTANCE_ACTOR,
    AutomaticLegacyItemAcceptanceService,
    LegacyItemAcceptanceRegistration,
    LegacyItemAcceptanceService,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from test_legacy_assessment_contracts import _result


def _acceptance() -> LegacyItemExtractionAcceptance:
    document: dict[str, Any] = {
        "schema_version": "legacy-item-extraction-acceptance/1.0",
        "acceptance_id": "itemacceptance_" + "1" * 32,
        "extraction_result": {
            "artifact": {
                "artifact_id": "artifact_" + "2" * 32,
                "artifact_revision_id": "rev_" + "3" * 32,
                "member_path": "result.json",
                "schema_ref": ("eom://schemas/legacy-assessment/legacy-item-extraction-result/1.0"),
                "media_type": "application/json",
                "sha256": "sha256:" + "4" * 64,
            },
            "extraction_result_id": "itemextractresult_" + "5" * 32,
            "result_sha256": "sha256:" + "6" * 64,
        },
        "state": "ACCEPTED",
        "item_decisions": [
            {
                "item_proposal_id": "itemproposal_" + "7" * 32,
                "item_number": 1,
                "decision": "ACCEPT",
                "accepted_content_paths": ["title", "body[0]"],
                "rejected_content_paths": [],
                "required_corrections": [],
            }
        ],
        "coverage_state": "COMPLETE",
        "reviewed_at": "2026-09-03T00:00:00Z",
        "reviewed_by": "operator_reviewer",
    }
    document["acceptance_sha256"] = content_sha256(document)
    return LegacyItemExtractionAcceptance.model_validate(document)


def test_acceptance_service_commits_canonical_bytes_before_registry_pointer() -> None:
    acceptance = _acceptance()
    committed_payloads: list[bytes] = []
    artifacts = Mock()

    def commit_file_set(**arguments: Any) -> CatalogArtifact:
        source = arguments["files"]["acceptance.json"]
        committed_payloads.append(source.read_bytes())
        assert arguments["expected_file_sha256"] == {
            "acceptance.json": sha256_bytes(committed_payloads[0])
        }
        return CatalogArtifact(
            job_id="job_" + "8" * 32,
            artifact_id="artifact_" + "9" * 32,
            revision_id="rev_" + "a" * 32,
            content_hash=sha256_bytes(committed_payloads[0]),
            manifest_hash="sha256:" + "b" * 64,
            content_bytes=len(committed_payloads[0]),
            nas_path="unused",
            manifest={},
        )

    artifacts.commit_file_set.side_effect = commit_file_set
    registry = Mock()
    registry.register_acceptance.return_value = LegacyAssessmentRegistration(
        logical_id=acceptance.acceptance_id,
        revision_id="rev_" + "a" * 32,
        created=True,
    )
    service = object.__new__(LegacyItemAcceptanceService)
    service.artifacts = artifacts
    service.registry = registry

    result = service.register(acceptance)

    assert committed_payloads == [canonical_json_bytes(acceptance.model_dump(mode="json"))]
    pointer = registry.register_acceptance.call_args.kwargs["acceptance_artifact"]
    assert pointer.artifact_id == result.artifact_id
    assert pointer.artifact_revision_id == result.artifact_revision_id
    assert pointer.sha256 == sha256_bytes(committed_payloads[0])
    assert result.created is True


def test_automatic_acceptance_is_replay_stable_and_covers_every_anchored_path() -> None:
    result = LegacyItemExtractionResult.model_validate(_result())
    pointer = LegacyExtractionResultPointer(
        artifact=AssessmentArtifactMemberPointer(
            artifact_id="artifact_" + "2" * 32,
            artifact_revision_id="rev_" + "3" * 32,
            member_path="result.json",
            schema_ref="eom://schemas/legacy-assessment/legacy-item-extraction-result/1.0",
            media_type="application/json",
            sha256="sha256:" + "4" * 64,
        ),
        extraction_result_id=result.extraction_result_id,
        result_sha256=result.result_sha256,
    )
    artifacts = Mock()
    artifacts.read_member.return_value = canonical_json_bytes(result.model_dump(mode="json"))
    acceptance = Mock()
    acceptance.register.return_value = LegacyItemAcceptanceRegistration(
        acceptance_id="unused",
        acceptance_sha256="sha256:" + "5" * 64,
        artifact_id="artifact_" + "6" * 32,
        artifact_revision_id="rev_" + "7" * 32,
        created=True,
    )
    service = object.__new__(AutomaticLegacyItemAcceptanceService)
    service.artifacts = artifacts
    service.acceptance = acceptance
    service.sessions = cast(
        Any,
        lambda: nullcontext(
            SimpleNamespace(
                get=lambda _model, _identity: SimpleNamespace(
                    approved=True,
                    logical_artifact_id=pointer.artifact.artifact_id,
                    content_hash=pointer.artifact.sha256,
                    created_at=datetime(2026, 9, 4, tzinfo=UTC),
                )
            )
        ),
    )

    service.register_validated_result(pointer)
    first = acceptance.register.call_args.args[0]
    service.register_validated_result(pointer)
    replay = acceptance.register.call_args.args[0]

    assert first == replay
    assert first.reviewed_by == AUTOMATIC_ACCEPTANCE_ACTOR
    assert first.state == "ACCEPTED"
    assert first.coverage_state == "COMPLETE"
    assert tuple(decision.item_number for decision in first.item_decisions) == (1,)
    assert first.item_decisions[0].accepted_content_paths == tuple(
        mapping.content_path for mapping in result.items[0].content_anchor_map
    )
