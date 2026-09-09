from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from eom_catalog_contracts import (
    AssessmentArtifactMemberPointer,
    LegacyCorpusSourceBinding,
    LegacyExtractionBatchWorkUnitV2,
    LegacyExtractionResultIdentityCollisionMember,
    LegacyItemCorpusCompletionCommand,
    LegacyItemExtractionAcceptance,
    LegacyItemExtractionBatchManifestV2,
    LegacyItemExtractionReceipt,
    LegacyItemExtractionRequest,
    LegacyItemExtractionResult,
    LegacyItemExtractionValidationRecovery,
    LegacySourceInventoryV2,
    derive_legacy_extraction_result_identity_collisions,
    derive_legacy_item_extraction_recovery_successor,
    validate_contract,
)
from eom_catalog_service.legacy_item_corpus_completion_service import (
    AcceptedTerminalWorkUnit,
    CoverageRegistrationEvidence,
    FailedTerminalWorkUnit,
    LegacyItemCorpusCompletionError,
    LegacyItemCorpusCompletionService,
    ResolvedArtifactRevision,
    ResolvedBatchSnapshot,
    ResolvedCorpusCompletionSnapshot,
)
from eom_catalog_service.legacy_item_corpus_completion_source import (
    PostgresLegacyItemCorpusCompletionSource,
)
from eom_catalog_service.legacy_item_extraction_batch_models import (
    LegacyItemExtractionBatchWorkUnitRecord,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_orchestrator.models import JobRecord
from eom_workflow import WorkflowRequest
from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord
from test_legacy_extraction_recovery_contracts import recovery_document


def _id(prefix: str, value: int) -> str:
    return f"{prefix}_{value:032x}"


def _pointer(
    value: int,
    *,
    member_path: str,
    schema_ref: str,
    sha256: str,
) -> AssessmentArtifactMemberPointer:
    return AssessmentArtifactMemberPointer(
        artifact_id=_id("artifact", value),
        artifact_revision_id=_id("rev", value),
        member_path=member_path,
        schema_ref=schema_ref,
        media_type="application/json",
        sha256=sha256,
    )


def _resolution(
    pointer: AssessmentArtifactMemberPointer,
    artifact_type: str,
) -> ResolvedArtifactRevision:
    return ResolvedArtifactRevision(
        pointer=pointer,
        logical_artifact_type=artifact_type,
        manifest_artifact_type=artifact_type,
        approved=True,
        producing_job_state="SUCCEEDED",
    )


def _request(ordinal: int, replacement: dict[str, Any] | None) -> LegacyItemExtractionRequest:
    seed = f"{ordinal + 1000:032x}"
    request_id = (
        str(replacement["predecessor_extraction_request_id"])
        if replacement is not None
        else "itemextractreq_" + seed
    )
    bundle_revision_id = (
        str(replacement["predecessor_bundle_revision_id"])
        if replacement is not None
        else "assessbundlerev_" + seed
    )
    item_numbers = (
        list(replacement["expected_item_numbers"]) if replacement is not None else [ordinal + 1]
    )
    document: dict[str, Any] = {
        "schema_version": "legacy-item-extraction-request/1.0",
        "extraction_request_id": request_id,
        "bundle": {
            "assessment_source_bundle_id": "assessbundle_" + f"{ordinal:032x}",
            "assessment_source_bundle_revision_id": bundle_revision_id,
            "bundle_manifest_sha256": "sha256:" + f"{ordinal + 1:064x}",
        },
        "occurrence": {
            "assessment_occurrence_id": "occurrence_" + seed,
            "assessment_occurrence_revision_id": "occurrev_" + seed,
            "occurrence_revision_sha256": "sha256:" + f"{ordinal + 2:064x}",
        },
        "layout_observation": {
            "assessment_layout_observation_id": "assessmentlayout_" + seed,
            "artifact": _pointer(
                40_000 + ordinal,
                member_path="layout.json",
                schema_ref=("eom://schemas/legacy-assessment/assessment-layout-observation/1.0"),
                sha256="sha256:" + f"{ordinal + 3:064x}",
            ).model_dump(mode="json"),
            "workspace_relative_path": "source/layout-observation.json",
            "observation_sha256": "sha256:" + f"{ordinal + 3:064x}",
        },
        "work_unit_ordinal": ordinal,
        "expected_item_numbers": item_numbers,
        "page_inputs": [
            {
                "page_input_id": "assessmentpage_" + seed,
                "source_role": "PROBLEM_DOCUMENT",
                "physical_page": 1,
                "source": _pointer(
                    50_000 + ordinal,
                    member_path="source.pdf",
                    schema_ref="eom://schemas/test/source/1.0",
                    sha256="sha256:" + "9" * 64,
                ).model_dump(mode="json"),
                "image": AssessmentArtifactMemberPointer(
                    artifact_id=_id("artifact", 60_000 + ordinal),
                    artifact_revision_id=_id("rev", 60_000 + ordinal),
                    member_path="page.png",
                    schema_ref="eom://schemas/test/page-image/1.0",
                    media_type="image/png",
                    sha256="sha256:" + f"{ordinal + 4:064x}",
                ).model_dump(mode="json"),
                "workspace_relative_path": f"source/pages/assessmentpage_{seed}.png",
                "width_px": 2480,
                "height_px": 3508,
            }
        ],
        "source_materializations": [],
        "execution_preset_id": "execpreset_" + "1" * 32,
        "execution_preset_revision_id": "execpresetrev_" + "2" * 32,
        "execution_preset_sha256": "sha256:" + "3" * 64,
        "worker_result_schema_ref": (
            "eom://schemas/legacy-assessment/legacy-item-extraction-result/1.0"
        ),
        "created_at": "2026-09-01T00:00:00Z",
        "request_sha256": "sha256:" + "0" * 64,
    }
    document["request_sha256"] = content_sha256(
        {key: value for key, value in document.items() if key != "request_sha256"}
    )
    return LegacyItemExtractionRequest.model_validate(document)


def _corpus_binding() -> LegacyCorpusSourceBinding:
    return LegacyCorpusSourceBinding(
        bundle_member_id="assessbundlemember_" + "8" * 32,
        reviewed_inventory_source={
            "inventory_id": "legacyinventory_" + "8" * 32,
            "inventory_sha256": "sha256:" + "8" * 64,
            "entry_key": "legacyentry_" + "9" * 32,
            "content_sha256": "sha256:" + "9" * 64,
        },
        corpus_inventory_source={
            "inventory_id": "legacyinventory_" + "c" * 32,
            "inventory_sha256": "sha256:" + "c" * 64,
            "entry_key": "legacyentry_" + "a" * 32,
            "content_sha256": "sha256:" + "9" * 64,
        },
    )


def _predecessor_and_recovery() -> tuple[
    LegacyItemExtractionBatchManifestV2,
    LegacyItemExtractionValidationRecovery,
]:
    authorization = recovery_document()
    replacements = authorization["replacements"]
    assert isinstance(replacements, list)
    replacements_by_ordinal = {
        int(value["predecessor_ordinal"]): value
        for value in replacements
        if isinstance(value, dict)
    }
    units: list[LegacyExtractionBatchWorkUnitV2] = []
    for ordinal in range(108):
        replacement = replacements_by_ordinal.get(ordinal)
        request = _request(ordinal, replacement)
        if replacement is not None:
            replacement["predecessor_request_sha256"] = request.request_sha256
        units.append(
            LegacyExtractionBatchWorkUnitV2(
                work_unit_id=(
                    str(replacement["predecessor_work_unit_id"])
                    if replacement is not None
                    else "legacyworkunit_" + f"{ordinal + 1000:032x}"
                ),
                ordinal=ordinal,
                request=request,
                expected_item_numbers_sha256=content_sha256(
                    {"item_numbers": list(request.expected_item_numbers)}
                ),
                execution_mode="EXECUTE",
                reuse_accepted=None,
                corpus_source_bindings=(_corpus_binding(),),
            )
        )
    manifest_document: dict[str, Any] = {
        "schema_version": "legacy-item-extraction-batch/1.1",
        "extraction_batch_id": authorization["predecessor_batch_id"],
        "idempotency_key": "predecessor-corpus",
        "inventory_id": "legacyinventory_" + "c" * 32,
        "inventory_sha256": "sha256:" + "c" * 64,
        "inventory_artifact": _pointer(
            1,
            member_path="legacy-source-inventory.json",
            schema_ref="eom://schemas/legacy-knowledge/legacy-source-inventory/2.0",
            sha256="sha256:" + "d" * 64,
        ).model_dump(mode="json"),
        "failure_policy": "CONTINUE_AND_COLLECT",
        "work_units": [value.model_dump(mode="json") for value in units],
        "created_at": "2026-09-04T00:00:00Z",
        "manifest_sha256": "sha256:" + "0" * 64,
    }
    manifest_document["manifest_sha256"] = content_sha256(
        {key: value for key, value in manifest_document.items() if key != "manifest_sha256"}
    )
    predecessor = LegacyItemExtractionBatchManifestV2.model_validate(manifest_document)
    authorization["predecessor_manifest_sha256"] = predecessor.manifest_sha256
    authorization["recovery_sha256"] = content_sha256(
        {key: value for key, value in authorization.items() if key != "recovery_sha256"}
    )
    return predecessor, LegacyItemExtractionValidationRecovery.model_validate(authorization)


def _inventory() -> LegacySourceInventoryV2:
    entry = {
        "entry_key": "legacyentry_" + "a" * 32,
        "relative_path": "past-exams/source.pdf",
        "file_observation": "REGULAR",
        "size_bytes": 100,
        "media_type": "application/pdf",
        "content_sha256": "sha256:" + "9" * 64,
        "preliminary_class": "ORIGINAL_SOURCE_CANDIDATE",
        "source_family": "ITEM",
        "canonicality": "ORIGINAL",
        "rights_state": "UNREVIEWED",
        "relation_group_key": None,
        "exclusion_reasons": [],
    }
    summary = {
        "original_source_candidates": {"file_count": 1, "byte_count": 100},
        "derived_migration_evidence": {"file_count": 0, "byte_count": 0},
        "excluded_runtime_state": {"file_count": 0, "byte_count": 0},
        "total_file_count": 1,
        "total_byte_count": 100,
    }
    source = {
        "schema_version": "legacy-source-set/1.0",
        "scanner_version": "1.0.0",
        "scanner_policy_revision_id": "legacyinventorypolicyrev_" + "1" * 32,
        "scanner_policy_sha256": "sha256:" + "1" * 64,
        "root_alias": "EOMIS_LEGACY_SOURCE",
        "root_configuration_sha256": "sha256:" + "2" * 64,
        "entries": [entry],
        "summary": summary,
    }
    source_set_sha256 = content_sha256(source)
    document: dict[str, object] = {
        "schema_version": "legacy-source-inventory/2.0",
        "inventory_id": "legacyinventory_" + source_set_sha256.removeprefix("sha256:")[:32],
        "observed_at": "2026-09-04T00:00:00Z",
        "scanner_version": "1.0.0",
        "scanner_policy_revision_id": source["scanner_policy_revision_id"],
        "scanner_policy_sha256": source["scanner_policy_sha256"],
        "root_alias": source["root_alias"],
        "root_configuration_sha256": source["root_configuration_sha256"],
        "entries": [entry],
        "summary": summary,
        "source_set_sha256": source_set_sha256,
        "inventory_sha256": "sha256:" + "0" * 64,
    }
    document["inventory_sha256"] = content_sha256(
        {
            key: value
            for key, value in document.items()
            if key not in {"observed_at", "inventory_sha256"}
        }
    )
    return LegacySourceInventoryV2.model_validate(document)


def _authority() -> tuple[
    LegacySourceInventoryV2,
    LegacyItemExtractionBatchManifestV2,
    LegacyItemExtractionValidationRecovery,
    LegacyItemExtractionBatchManifestV2,
    AssessmentArtifactMemberPointer,
]:
    predecessor, recovery = _predecessor_and_recovery()
    inventory = _inventory()
    inventory_pointer = _pointer(
        1,
        member_path="legacy-source-inventory.json",
        schema_ref="eom://schemas/legacy-knowledge/legacy-source-inventory/2.0",
        sha256=sha256_bytes(canonical_json_bytes(inventory.model_dump(mode="json")) + b"\n"),
    )
    predecessor_document = predecessor.model_dump(mode="json")
    predecessor_document.update(
        {
            "inventory_id": inventory.inventory_id,
            "inventory_sha256": inventory.inventory_sha256,
            "inventory_artifact": inventory_pointer.model_dump(mode="json"),
        }
    )
    work_units = predecessor_document["work_units"]
    assert isinstance(work_units, list)
    for work_unit in work_units:
        assert isinstance(work_unit, dict)
        bindings = work_unit["corpus_source_bindings"]
        assert isinstance(bindings, list)
        for binding in bindings:
            assert isinstance(binding, dict)
            corpus_source = binding["corpus_inventory_source"]
            assert isinstance(corpus_source, dict)
            corpus_source["inventory_id"] = inventory.inventory_id
            corpus_source["inventory_sha256"] = inventory.inventory_sha256
    predecessor_document["manifest_sha256"] = content_sha256(
        {key: value for key, value in predecessor_document.items() if key != "manifest_sha256"}
    )
    predecessor = LegacyItemExtractionBatchManifestV2.model_validate(predecessor_document)
    recovery_document = recovery.model_dump(mode="json")
    recovery_document["predecessor_manifest_sha256"] = predecessor.manifest_sha256
    recovery_document["recovery_sha256"] = content_sha256(
        {key: value for key, value in recovery_document.items() if key != "recovery_sha256"}
    )
    recovery = type(recovery).model_validate(recovery_document)
    successor = derive_legacy_item_extraction_recovery_successor(recovery, predecessor)
    recovery_pointer = _pointer(
        2,
        member_path="validation-recovery.json",
        schema_ref=(
            "eom://schemas/legacy-assessment/legacy-item-extraction-validation-recovery/1.0"
        ),
        sha256=sha256_bytes(canonical_json_bytes(recovery) + b"\n"),
    )
    return inventory, predecessor, recovery, successor, recovery_pointer


def _proposal(
    request: LegacyItemExtractionRequest,
    item_number: int,
    serial: int,
) -> dict[str, object]:
    request_page = request.page_inputs[0]
    anchor_id = _id("assessmentanchor", serial)
    return {
        "item_proposal_id": _id("itemproposal", serial),
        "item_number": item_number,
        "item_content": {
            "schema_version": "1.0",
            "locale": "ko-KR",
            "title": "자료 해석 문항",
            "body": [
                {
                    "block_id": "block_stem",
                    "type": "paragraph",
                    "purpose": "stem",
                    "text": "다음 자료를 해석하시오.",
                }
            ],
            "interaction": {
                "type": "single_choice",
                "choices": [
                    {"choice_id": f"choice_{number}", "label": str(number), "text": str(number)}
                    for number in range(1, 6)
                ],
            },
            "solution": {
                "correct_choice_ids": ["choice_1"],
                "accepted_answers": [],
                "explanation": "근거를 비교한다.",
                "authoring_intent": "자료 해석 능력을 평가한다.",
                "statement_explanations": [],
            },
            "score": {"points": 2},
        },
        "authoring_intent_evidence_state": "ANALYST_RECONSTRUCTED",
        "source_anchors": [
            {
                "anchor_id": anchor_id,
                "source": request_page.image.model_dump(mode="json"),
                "source_role": request_page.source_role,
                "physical_page": request_page.physical_page,
                "bounding_box": {"left": 100, "top": 100, "right": 9000, "bottom": 9000},
                "locator_detail": f"page item {item_number}",
            }
        ],
        "content_anchor_map": [
            {"content_path": path, "source_anchor_ids": [anchor_id]}
            for path in ("title", "body[0]", "interaction", "solution")
        ],
        "curriculum_observations": [],
        "linguistic_patterns": [
            {
                "pattern_id": _id("linguisticpattern", serial),
                "prompt_form": "SELECT_CORRECT",
                "polarity": "POSITIVE",
                "condition_placement": "INLINE",
                "choice_grammar": "COMPLETE_SENTENCE",
                "uses_statement_set": False,
                "closing_expression": "옳은 것은?",
                "structure_summary": "자료를 해석한다.",
                "reusable_pattern": "자료를 비교해 선택한다.",
                "source_anchor_ids": [anchor_id],
            }
        ],
        "visual_patterns": [],
        "metadata_observations": [],
        "conflicts": [],
        "confidence_milli": 900,
    }


def _accepted(
    batch_id: str,
    unit: LegacyExtractionBatchWorkUnitV2,
    serial: int,
    *,
    extraction_result_id: str | None = None,
) -> AcceptedTerminalWorkUnit:
    request = unit.request
    items = [
        _proposal(request, number, serial * 10 + offset)
        for offset, number in enumerate(request.expected_item_numbers)
    ]
    result_document: dict[str, object] = {
        "schema_version": "legacy-item-extraction-result/1.0",
        "extraction_result_id": extraction_result_id or _id("itemextractresult", serial),
        "extraction_request_id": request.extraction_request_id,
        "request_sha256": request.request_sha256,
        "observed_page_input_ids": [value.page_input_id for value in request.page_inputs],
        "items": items,
        "result_sha256": "sha256:" + "0" * 64,
    }
    result_document["result_sha256"] = content_sha256(
        {key: value for key, value in result_document.items() if key != "result_sha256"}
    )
    result = LegacyItemExtractionResult.model_validate(result_document)
    result_pointer = _pointer(
        10_000 + serial,
        member_path="result.json",
        schema_ref="eom://schemas/legacy-assessment/legacy-item-extraction-result/1.0",
        sha256=sha256_bytes(canonical_json_bytes(result)),
    )
    completed_at = datetime(2026, 9, 9, 7, tzinfo=UTC) + timedelta(seconds=serial)
    receipt_document: dict[str, object] = {
        "schema_version": "legacy-item-extraction-receipt/1.0",
        "extraction_result_id": result.extraction_result_id,
        "extraction_request_id": result.extraction_request_id,
        "request_sha256": result.request_sha256,
        "result_artifact": result_pointer.model_dump(mode="json"),
        "result_sha256": result.result_sha256,
        "observed_page_input_ids": list(result.observed_page_input_ids),
        "item_numbers": [value.item_number for value in result.items],
        "completed_at": completed_at.isoformat().replace("+00:00", "Z"),
        "receipt_sha256": "sha256:" + "0" * 64,
    }
    receipt_document["receipt_sha256"] = content_sha256(
        {key: value for key, value in receipt_document.items() if key != "receipt_sha256"}
    )
    receipt = LegacyItemExtractionReceipt.model_validate(receipt_document)
    acceptance_document: dict[str, object] = {
        "schema_version": "legacy-item-extraction-acceptance/1.0",
        "acceptance_id": _id("itemacceptance", serial),
        "extraction_result": {
            "artifact": result_pointer.model_dump(mode="json"),
            "extraction_result_id": result.extraction_result_id,
            "result_sha256": result.result_sha256,
        },
        "state": "ACCEPTED",
        "item_decisions": [
            {
                "item_proposal_id": value.item_proposal_id,
                "item_number": value.item_number,
                "decision": "ACCEPT",
                "accepted_content_paths": ["title", "body[0]", "interaction", "solution"],
                "rejected_content_paths": [],
                "required_corrections": [],
            }
            for value in result.items
        ],
        "coverage_state": "COMPLETE",
        "reviewed_at": (completed_at + timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
        "reviewed_by": "operator-stage-c",
        "acceptance_sha256": "sha256:" + "0" * 64,
    }
    acceptance_document["acceptance_sha256"] = content_sha256(
        {key: value for key, value in acceptance_document.items() if key != "acceptance_sha256"}
    )
    acceptance = LegacyItemExtractionAcceptance.model_validate(acceptance_document)
    acceptance_pointer = _pointer(
        20_000 + serial,
        member_path="acceptance.json",
        schema_ref=("eom://schemas/legacy-assessment/legacy-item-extraction-acceptance/1.0"),
        sha256=sha256_bytes(canonical_json_bytes(acceptance.model_dump(mode="json"))),
    )
    return AcceptedTerminalWorkUnit(
        extraction_batch_id=batch_id,
        work_unit_id=unit.work_unit_id,
        ordinal=unit.ordinal,
        state="ACCEPTED",
        extraction_request_id=request.extraction_request_id,
        request_sha256=request.request_sha256,
        result_artifact=result_pointer,
        result_artifact_resolution=_resolution(result_pointer, "legacy-item-extraction-result"),
        extraction_result_id=result.extraction_result_id,
        result_sha256=result.result_sha256,
        result=result,
        extraction_receipt_sha256=receipt.receipt_sha256,
        extraction_receipt=receipt,
        acceptance_id=acceptance.acceptance_id,
        acceptance_sha256=acceptance.acceptance_sha256,
        acceptance_artifact=acceptance_pointer,
        acceptance_artifact_resolution=_resolution(
            acceptance_pointer, "legacy-item-extraction-acceptance"
        ),
        acceptance=acceptance,
        completed_at=completed_at + timedelta(seconds=1),
    )


def _manifest_pointer(
    manifest: LegacyItemExtractionBatchManifestV2,
    serial: int,
) -> AssessmentArtifactMemberPointer:
    return _pointer(
        serial,
        member_path="legacy-item-extraction-batch.json",
        schema_ref="eom://schemas/legacy-assessment/legacy-item-extraction-batch/1.1",
        sha256=sha256_bytes(canonical_json_bytes(manifest.model_dump(mode="json"))),
    )


def _fixture() -> tuple[
    LegacyItemCorpusCompletionCommand,
    ResolvedCorpusCompletionSnapshot,
]:
    inventory, predecessor, recovery, successor, recovery_pointer = _authority()
    replacements = {value.predecessor_work_unit_id: value for value in recovery.replacements}
    original_terminals = []
    for serial, unit in enumerate(predecessor.work_units, start=1):
        replacement = replacements.get(unit.work_unit_id)
        if replacement is None:
            original_terminals.append(_accepted(predecessor.extraction_batch_id, unit, serial))
        else:
            original_terminals.append(
                FailedTerminalWorkUnit(
                    extraction_batch_id=predecessor.extraction_batch_id,
                    work_unit_id=unit.work_unit_id,
                    ordinal=unit.ordinal,
                    state="FAILED",
                    extraction_request_id=unit.request.extraction_request_id,
                    request_sha256=unit.request.request_sha256,
                    error_code=replacement.failure_code,
                    workflow_id=replacement.predecessor_workflow_id,
                    platform_job_id=replacement.predecessor_platform_job_id,
                    workflow_failure_code=replacement.workflow_failure_code,
                    job_error_code=replacement.job_error_code,
                    failure_message_sha256=replacement.failure_message_sha256,
                    result_present=False,
                    receipt_present=False,
                    acceptance_present=False,
                    completed_at=datetime(2026, 9, 9, 7, tzinfo=UTC) + timedelta(seconds=serial),
                )
            )
    successor_terminals = tuple(
        _accepted(successor.extraction_batch_id, unit, 1_000 + serial)
        for serial, unit in enumerate(successor.work_units, start=1)
    )
    predecessor_pointer = _manifest_pointer(predecessor, 3)
    successor_pointer = _manifest_pointer(successor, 4)
    inventory_pointer = predecessor.inventory_artifact
    original = ResolvedBatchSnapshot(
        manifest=predecessor,
        manifest_artifact=predecessor_pointer,
        manifest_artifact_resolution=_resolution(
            predecessor_pointer, "legacy-item-extraction-batch"
        ),
        state="COMPLETED_WITH_GAPS",
        work_units=tuple(original_terminals),
    )
    successor_batch = ResolvedBatchSnapshot(
        manifest=successor,
        manifest_artifact=successor_pointer,
        manifest_artifact_resolution=_resolution(successor_pointer, "legacy-item-extraction-batch"),
        state="SUCCEEDED",
        work_units=successor_terminals,
    )
    command_document: dict[str, object] = {
        "schema_version": "legacy-item-corpus-completion-command/1.0",
        "inventory_id": inventory.inventory_id,
        "inventory_sha256": inventory.inventory_sha256,
        "original_batch": {
            "extraction_batch_id": predecessor.extraction_batch_id,
            "manifest_sha256": predecessor.manifest_sha256,
        },
        "successor_batch": {
            "extraction_batch_id": successor.extraction_batch_id,
            "manifest_sha256": successor.manifest_sha256,
        },
        "recovery_sha256": recovery.recovery_sha256,
        "recovery_artifact": recovery_pointer.model_dump(mode="json"),
        "requested_by": "operator-stage-c",
        "command_sha256": "sha256:" + "0" * 64,
    }
    command_document["command_sha256"] = content_sha256(
        {key: value for key, value in command_document.items() if key != "command_sha256"}
    )
    command = LegacyItemCorpusCompletionCommand.model_validate(command_document)
    snapshot = ResolvedCorpusCompletionSnapshot(
        requested_by=command.requested_by,
        requester_active=True,
        requester_authorized=True,
        recovery=recovery,
        recovery_artifact_resolution=_resolution(
            recovery_pointer, "control_legacy_item_extraction_validation_recovery"
        ),
        inventory=inventory,
        inventory_artifact_resolution=_resolution(inventory_pointer, "legacy-source-inventory"),
        original_batch=original,
        successor_batch=successor_batch,
    )
    return command, snapshot


class _Source:
    def __init__(self, snapshot: ResolvedCorpusCompletionSnapshot) -> None:
        self.snapshot = snapshot

    def resolve_completion_snapshot(
        self, command: LegacyItemCorpusCompletionCommand
    ) -> ResolvedCorpusCompletionSnapshot:
        return replace(self.snapshot, requested_by=command.requested_by)


class _Artifacts:
    def __init__(self) -> None:
        self.by_key: dict[str, AssessmentArtifactMemberPointer] = {}

    def commit_coverage(
        self,
        coverage: object,
        *,
        idempotency_key: str,
    ) -> AssessmentArtifactMemberPointer:
        value = coverage.model_dump(mode="json")  # type: ignore[attr-defined]
        pointer = _pointer(
            30_000,
            member_path="coverage.json",
            schema_ref="eom://schemas/legacy-assessment/legacy-item-corpus-coverage/1.0",
            sha256=sha256_bytes(canonical_json_bytes(value)),
        )
        existing = self.by_key.setdefault(idempotency_key, pointer)
        assert existing == pointer
        return existing


class _Registry:
    def __init__(self) -> None:
        self.by_id: dict[str, tuple[object, AssessmentArtifactMemberPointer]] = {}

    def register_coverage(
        self,
        coverage: object,
        *,
        coverage_artifact: AssessmentArtifactMemberPointer,
    ) -> CoverageRegistrationEvidence:
        coverage_id = coverage.coverage_id  # type: ignore[attr-defined]
        created = coverage_id not in self.by_id
        prior = self.by_id.setdefault(coverage_id, (coverage, coverage_artifact))
        assert prior == (coverage, coverage_artifact)
        return CoverageRegistrationEvidence(
            logical_id=coverage_id,
            revision_id=coverage_artifact.artifact_revision_id,
            created=created,
        )


def _service(
    snapshot: ResolvedCorpusCompletionSnapshot,
) -> tuple[LegacyItemCorpusCompletionService, _Artifacts, _Registry]:
    artifacts = _Artifacts()
    registry = _Registry()
    return (
        LegacyItemCorpusCompletionService(
            source=_Source(snapshot),
            artifacts=artifacts,
            registry=registry,
        ),
        artifacts,
        registry,
    )


def _historical_result_collision_fixture() -> tuple[
    LegacyItemCorpusCompletionCommand,
    LegacyItemCorpusCompletionCommand,
    ResolvedCorpusCompletionSnapshot,
]:
    unpinned_command, snapshot = _fixture()
    accepted_positions = [
        index
        for index, terminal in enumerate(snapshot.original_batch.work_units)
        if isinstance(terminal, AcceptedTerminalWorkUnit)
    ]
    first_position, second_position = accepted_positions[:2]
    first = snapshot.original_batch.work_units[first_position]
    assert isinstance(first, AcceptedTerminalWorkUnit)
    second_unit = snapshot.original_batch.manifest.work_units[second_position]
    colliding = _accepted(
        snapshot.original_batch.manifest.extraction_batch_id,
        second_unit,
        second_position + 1,
        extraction_result_id=first.extraction_result_id,
    )
    original_terminals = list(snapshot.original_batch.work_units)
    original_terminals[second_position] = colliding
    snapshot = replace(
        snapshot,
        original_batch=replace(snapshot.original_batch, work_units=tuple(original_terminals)),
    )
    effective_terminals = tuple(
        terminal
        for terminal in (
            *snapshot.original_batch.work_units,
            *snapshot.successor_batch.work_units,
        )
        if isinstance(terminal, AcceptedTerminalWorkUnit)
    )
    evidence = derive_legacy_extraction_result_identity_collisions(
        LegacyExtractionResultIdentityCollisionMember(
            effective_batch_id=terminal.extraction_batch_id,
            effective_work_unit_id=terminal.work_unit_id,
            effective_ordinal=terminal.ordinal,
            extraction_request_id=terminal.extraction_request_id,
            request_sha256=terminal.request_sha256,
            extraction_result_id=terminal.extraction_result_id,
            result_artifact=terminal.result_artifact,
            result_sha256=terminal.result_sha256,
            extraction_receipt_sha256=terminal.extraction_receipt_sha256,
            acceptance_id=terminal.acceptance_id,
            acceptance_sha256=terminal.acceptance_sha256,
            acceptance_artifact=terminal.acceptance_artifact,
        )
        for terminal in effective_terminals
    )
    assert evidence is not None
    command_document = unpinned_command.model_dump(mode="json")
    command_document["schema_version"] = "legacy-item-corpus-completion-command/1.1"
    command_document["historical_result_identity_collisions"] = evidence.model_dump(mode="json")
    command_document["command_sha256"] = content_sha256(
        {key: value for key, value in command_document.items() if key != "command_sha256"}
    )
    validate_contract("legacy-item-corpus-completion-command-v2", command_document)
    pinned_command = LegacyItemCorpusCompletionCommand.model_validate(command_document)
    return unpinned_command, pinned_command, snapshot


def test_completion_derives_exact_scope_and_semantically_replays() -> None:
    command, snapshot = _fixture()
    service, artifacts, registry = _service(snapshot)

    first = service.complete(command)
    command_document = command.model_dump(mode="json")
    command_document["requested_by"] = "other-authorized-operator"
    command_document["command_sha256"] = content_sha256(
        {key: value for key, value in command_document.items() if key != "command_sha256"}
    )
    replay = service.complete(LegacyItemCorpusCompletionCommand.model_validate(command_document))

    assert first.status == "COMPLETE"
    assert first.original_work_unit_count == 108
    assert first.effective_work_unit_count == 108
    assert first.recovered_work_unit_count == 3
    assert first.expected_item_count == first.accepted_item_count
    assert first.coverage_id == replay.coverage_id
    assert first.coverage_sha256 == replay.coverage_sha256
    assert len(artifacts.by_key) == len(registry.by_id) == 1


def test_completion_requires_exact_pinned_historical_result_identity_collisions() -> None:
    unpinned_command, pinned_command, snapshot = _historical_result_collision_fixture()
    service, artifacts, _ = _service(snapshot)

    with pytest.raises(LegacyItemCorpusCompletionError) as raised:
        service.complete(unpinned_command)

    assert raised.value.code == (
        "LEGACY_ITEM_CORPUS_COMPLETION_RESULT_IDENTITY_COLLISIONS_UNATTESTED"
    )
    assert artifacts.by_key == {}

    receipt = service.complete(pinned_command)
    assert receipt.schema_version == "legacy-item-corpus-completion-receipt/1.1"

    evidence = receipt.historical_result_identity_collisions
    assert evidence is not None
    assert evidence.collision_group_count == 1
    assert evidence.collision_membership_count == 2
    assert evidence.noncanonical_membership_count == 1


def test_completion_never_attests_duplicate_non_result_evidence() -> None:
    command, snapshot = _fixture()
    accepted = tuple(
        terminal
        for terminal in snapshot.original_batch.work_units
        if isinstance(terminal, AcceptedTerminalWorkUnit)
    )
    first, second = accepted[:2]
    changed = replace(second, extraction_receipt_sha256=first.extraction_receipt_sha256)
    work_units = tuple(
        changed if terminal is second else terminal
        for terminal in snapshot.original_batch.work_units
    )
    snapshot = replace(
        snapshot,
        original_batch=replace(snapshot.original_batch, work_units=work_units),
    )
    service, artifacts, _ = _service(snapshot)

    with pytest.raises(LegacyItemCorpusCompletionError) as raised:
        service.complete(command)

    assert raised.value.code == "LEGACY_ITEM_CORPUS_COMPLETION_EFFECTIVE_EVIDENCE_DUPLICATE"
    assert artifacts.by_key == {}


def test_completion_rejects_wrong_page_before_publication() -> None:
    command, snapshot = _fixture()
    accepted = next(
        value
        for value in snapshot.original_batch.work_units
        if isinstance(value, AcceptedTerminalWorkUnit)
    )
    wrong_result = accepted.result.model_copy(
        update={"observed_page_input_ids": (_id("assessmentpage", 99_999),)}
    )
    changed = replace(accepted, result=wrong_result)
    units = tuple(
        changed if value is accepted else value for value in snapshot.original_batch.work_units
    )
    snapshot = replace(
        snapshot,
        original_batch=replace(snapshot.original_batch, work_units=units),
    )
    service, artifacts, _ = _service(snapshot)

    with pytest.raises(LegacyItemCorpusCompletionError) as raised:
        service.complete(command)

    assert raised.value.code == "LEGACY_ITEM_CORPUS_COMPLETION_REQUEST_RESULT_INVALID"
    assert artifacts.by_key == {}


def test_completion_rejects_failed_predecessor_output_presence() -> None:
    command, snapshot = _fixture()
    failed = next(
        value
        for value in snapshot.original_batch.work_units
        if isinstance(value, FailedTerminalWorkUnit)
    )
    changed = replace(failed, result_present=True)  # type: ignore[arg-type]
    units = tuple(
        changed if value is failed else value for value in snapshot.original_batch.work_units
    )
    snapshot = replace(
        snapshot,
        original_batch=replace(snapshot.original_batch, work_units=units),
    )
    service, artifacts, _ = _service(snapshot)

    with pytest.raises(LegacyItemCorpusCompletionError) as raised:
        service.complete(command)

    assert raised.value.code == "LEGACY_ITEM_CORPUS_COMPLETION_FAILED_OUTPUT_PRESENT"
    assert artifacts.by_key == {}


def test_completion_rejects_missing_or_duplicate_terminal_set() -> None:
    command, snapshot = _fixture()
    first = snapshot.original_batch.work_units[0]
    units = (*snapshot.original_batch.work_units[:-1], first)
    snapshot = replace(
        snapshot,
        original_batch=replace(snapshot.original_batch, work_units=units),
    )
    service, artifacts, _ = _service(snapshot)

    with pytest.raises(LegacyItemCorpusCompletionError) as raised:
        service.complete(command)

    assert raised.value.code == "LEGACY_ITEM_CORPUS_COMPLETION_BATCH_SET_INVALID"
    assert artifacts.by_key == {}


def test_completion_rejects_result_artifact_pointer_drift() -> None:
    command, snapshot = _fixture()
    accepted = next(
        value
        for value in snapshot.successor_batch.work_units
        if isinstance(value, AcceptedTerminalWorkUnit)
    )
    pointer_document = accepted.result_artifact.model_dump(mode="json")
    pointer_document["sha256"] = "sha256:" + "f" * 64
    pointer = AssessmentArtifactMemberPointer.model_validate(pointer_document)
    changed = replace(accepted, result_artifact=pointer)
    units = tuple(
        changed if value is accepted else value for value in snapshot.successor_batch.work_units
    )
    snapshot = replace(
        snapshot,
        successor_batch=replace(snapshot.successor_batch, work_units=units),
    )
    service, artifacts, _ = _service(snapshot)

    with pytest.raises(LegacyItemCorpusCompletionError) as raised:
        service.complete(command)

    assert raised.value.code == "LEGACY_ITEM_CORPUS_COMPLETION_ACCEPTANCE_POINTER_INVALID"
    assert artifacts.by_key == {}


def _execute_binding_fixture() -> tuple[
    LegacyItemExtractionBatchWorkUnitRecord,
    LegacyItemExtractionRequest,
    WorkflowInstanceRecord,
    JobRecord,
    WorkflowStepRunRecord,
]:
    request = _request(0, None)
    workflow_id = _id("workflow", 91_001)
    job_id = _id("job", 91_002)
    workflow = WorkflowInstanceRecord(
        workflow_id=workflow_id,
        definition_key="legacy-item-extraction",
        state="COMPLETED",
        stage="COMPLETED",
        initial_request=WorkflowRequest(
            request_name="LEGACY_ITEM_EXTRACTION_REQUEST",
            image_mode="skip",
            legacy_extraction_request=request,
        ).model_dump(mode="json"),
        runtime_context={"legacy_item_extraction_request_sha256": request.request_sha256},
    )
    job = JobRecord(job_id=job_id, status="SUCCEEDED")
    step = WorkflowStepRunRecord(
        step_run_id=_id("steprun", 91_003),
        workflow_id=workflow_id,
        step_key="extract",
        attempt=1,
        step_type="agent",
        worker_role="support",
        result_schema="legacy-item-extraction-result@1.0",
        state="SUCCEEDED",
        platform_job_id=job_id,
    )
    row = LegacyItemExtractionBatchWorkUnitRecord(
        work_unit_id=_id("legacyworkunit", 91_004),
        extraction_batch_id=_id("legacyextractbatch", 91_005),
        extraction_request_id=request.extraction_request_id,
        request_sha256=request.request_sha256,
        workflow_id=workflow_id,
        platform_job_id=job_id,
        state="ACCEPTED",
    )
    return row, request, workflow, job, step


def test_execute_work_unit_requires_exact_workflow_step_and_job_binding() -> None:
    row, request, workflow, job, step = _execute_binding_fixture()

    PostgresLegacyItemCorpusCompletionSource._validate_execute_binding(
        row=row,
        request=request,
        workflow=workflow,
        job=job,
        step_runs=(step,),
    )

    row.platform_job_id = None
    with pytest.raises(LegacyItemCorpusCompletionError, match="provenance differs"):
        PostgresLegacyItemCorpusCompletionSource._validate_execute_binding(
            row=row,
            request=request,
            workflow=workflow,
            job=job,
            step_runs=(step,),
        )


def test_execute_work_unit_rejects_swapped_step_job() -> None:
    row, request, workflow, job, step = _execute_binding_fixture()
    step.platform_job_id = _id("job", 91_006)

    with pytest.raises(LegacyItemCorpusCompletionError, match="provenance differs"):
        PostgresLegacyItemCorpusCompletionSource._validate_execute_binding(
            row=row,
            request=request,
            workflow=workflow,
            job=job,
            step_runs=(step,),
        )
