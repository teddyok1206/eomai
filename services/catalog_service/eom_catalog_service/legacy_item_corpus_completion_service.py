"""Purely injected Catalog use case for deterministic corpus coverage completion.

This use case performs no database or NAS access by itself. A source adapter must resolve all
documents and rows in one stable transaction; an orchestrator-owned Artifact boundary performs the
single canonical coverage commit; and the existing registry performs the final registration.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, NoReturn, Protocol

from eom_catalog_contracts import (
    AcceptedCoverageItem,
    AssessmentArtifactMemberPointer,
    AssessmentBundleCoverage,
    AssessmentSourceBundlePointer,
    LegacyExtractionBatchWorkUnitV2,
    LegacyItemCorpusCoverage,
    LegacyItemExtractionAcceptance,
    LegacyItemExtractionBatchManifestV2,
    LegacyItemExtractionReceipt,
    LegacyItemExtractionResult,
    LegacyItemExtractionValidationRecovery,
    LegacySourceInventoryV2,
    derive_legacy_item_extraction_recovery_successor,
    validate_contract,
    validate_legacy_item_extraction_result_for_request,
)
from eom_catalog_contracts.legacy_item_corpus_completion import (
    LegacyExtractionBatchCompletionEvidence,
    LegacyItemCorpusCompletionCommand,
    LegacyItemCorpusCompletionReceipt,
    verify_corpus_completion_receipt_command,
    verify_corpus_completion_recovery_authority,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from jsonschema import ValidationError as JsonSchemaValidationError


class LegacyItemCorpusCompletionError(RuntimeError):
    """Stable, content-free failure at the completion application boundary."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ResolvedArtifactRevision:
    """Content-free proof that one pinned member passed canonical Artifact resolution."""

    pointer: AssessmentArtifactMemberPointer
    logical_artifact_type: str
    manifest_artifact_type: str
    approved: Literal[True]
    producing_job_state: Literal["SUCCEEDED"]


@dataclass(frozen=True)
class AcceptedTerminalWorkUnit:
    """Resolved accepted row plus its three canonical typed documents."""

    extraction_batch_id: str
    work_unit_id: str
    ordinal: int
    state: Literal["ACCEPTED"]
    extraction_request_id: str
    request_sha256: str
    result_artifact: AssessmentArtifactMemberPointer
    result_artifact_resolution: ResolvedArtifactRevision
    extraction_result_id: str
    result_sha256: str
    result: LegacyItemExtractionResult
    extraction_receipt_sha256: str
    extraction_receipt: LegacyItemExtractionReceipt
    acceptance_id: str
    acceptance_sha256: str
    acceptance_artifact: AssessmentArtifactMemberPointer
    acceptance_artifact_resolution: ResolvedArtifactRevision
    acceptance: LegacyItemExtractionAcceptance
    completed_at: datetime


@dataclass(frozen=True)
class FailedTerminalWorkUnit:
    """Resolved failed row; absence flags prevent a failed predecessor carrying output."""

    extraction_batch_id: str
    work_unit_id: str
    ordinal: int
    state: Literal["FAILED"]
    extraction_request_id: str
    request_sha256: str
    error_code: str
    workflow_id: str
    platform_job_id: str
    workflow_failure_code: str
    job_error_code: str
    failure_message_sha256: str
    result_present: Literal[False]
    receipt_present: Literal[False]
    acceptance_present: Literal[False]
    completed_at: datetime


type TerminalWorkUnit = AcceptedTerminalWorkUnit | FailedTerminalWorkUnit


@dataclass(frozen=True)
class ResolvedBatchSnapshot:
    """One immutable manifest and the exact terminal rows observed for it."""

    manifest: LegacyItemExtractionBatchManifestV2
    manifest_artifact: AssessmentArtifactMemberPointer
    manifest_artifact_resolution: ResolvedArtifactRevision
    state: Literal["COMPLETED_WITH_GAPS", "SUCCEEDED"]
    work_units: tuple[TerminalWorkUnit, ...]


@dataclass(frozen=True)
class ResolvedCorpusCompletionSnapshot:
    """All completion inputs resolved under one stable read transaction."""

    requested_by: str
    requester_active: Literal[True]
    requester_authorized: Literal[True]
    recovery: LegacyItemExtractionValidationRecovery
    recovery_artifact_resolution: ResolvedArtifactRevision
    inventory: LegacySourceInventoryV2
    inventory_artifact_resolution: ResolvedArtifactRevision
    original_batch: ResolvedBatchSnapshot
    successor_batch: ResolvedBatchSnapshot


class CompletionSourceBoundary(Protocol):
    """Resolve every source and row in one repeatable, read-only snapshot."""

    def resolve_completion_snapshot(
        self, command: LegacyItemCorpusCompletionCommand
    ) -> ResolvedCorpusCompletionSnapshot: ...


class OrchestratorCoverageArtifactBoundary(Protocol):
    """Port implemented only by the orchestrator-owned canonical Artifact committer."""

    def commit_coverage(
        self,
        coverage: LegacyItemCorpusCoverage,
        *,
        idempotency_key: str,
    ) -> AssessmentArtifactMemberPointer: ...


class CoverageRegistryBoundary(Protocol):
    """Narrow view of ``LegacyAssessmentRegistry.register_coverage``."""

    def register_coverage(
        self,
        coverage: LegacyItemCorpusCoverage,
        *,
        coverage_artifact: AssessmentArtifactMemberPointer,
    ) -> CoverageRegistrationEvidence: ...


@dataclass(frozen=True)
class CoverageRegistrationEvidence:
    """Content-free result returned by the existing Catalog coverage registry."""

    logical_id: str
    revision_id: str | None
    created: bool


@dataclass(frozen=True)
class _AcceptedKey:
    bundle: AssessmentSourceBundlePointer
    item_number: int
    acceptance_id: str
    acceptance_sha256: str
    reviewed_at: datetime


class LegacyItemCorpusCompletionService:
    """Derive, commit and register one exact COMPLETE coverage document."""

    def __init__(
        self,
        *,
        source: CompletionSourceBoundary,
        artifacts: OrchestratorCoverageArtifactBoundary,
        registry: CoverageRegistryBoundary,
    ) -> None:
        self.source = source
        self.artifacts = artifacts
        self.registry = registry

    def complete(
        self, command: LegacyItemCorpusCompletionCommand
    ) -> LegacyItemCorpusCompletionReceipt:
        resolved = self.source.resolve_completion_snapshot(command)
        if (
            resolved.requested_by != command.requested_by
            or resolved.requester_active is not True
            or resolved.requester_authorized is not True
        ):
            self._fail(
                "LEGACY_ITEM_CORPUS_COMPLETION_OPERATOR_INVALID",
                "completion requires an active authorized operator",
            )
        recovery = resolved.recovery
        try:
            verify_corpus_completion_recovery_authority(command, recovery)
            self._require_resolution(
                resolved.recovery_artifact_resolution,
                pointer=command.recovery_artifact,
                artifact_types={
                    "control_legacy_item_extraction_validation_recovery",
                    "legacy-item-extraction-validation-recovery",
                },
            )
        except ValueError as exc:
            self._fail(
                "LEGACY_ITEM_CORPUS_COMPLETION_RECOVERY_INVALID",
                "completion recovery authority is invalid",
                exc,
            )

        original = resolved.original_batch
        successor = resolved.successor_batch
        original_by_id = self._validate_batch(command, original, role="ORIGINAL")
        successor_by_id = self._validate_batch(command, successor, role="SUCCESSOR")
        try:
            derived_successor = derive_legacy_item_extraction_recovery_successor(
                recovery,
                original.manifest,
            )
        except ValueError as exc:
            self._fail(
                "LEGACY_ITEM_CORPUS_COMPLETION_RECOVERY_INVALID",
                "completion recovery successor cannot be derived",
                exc,
            )
        if successor.manifest != derived_successor:
            self._fail(
                "LEGACY_ITEM_CORPUS_COMPLETION_SUCCESSOR_MANIFEST_INVALID",
                "completion successor differs from the exact authorized derivation",
            )

        inventory = resolved.inventory
        if (
            inventory.inventory_id != command.inventory_id
            or inventory.inventory_sha256 != command.inventory_sha256
            or resolved.inventory_artifact_resolution.pointer
            != original.manifest.inventory_artifact
            or original.manifest.inventory_artifact.sha256
            != sha256_bytes(canonical_json_bytes(inventory.model_dump(mode="json")) + b"\n")
            or successor.manifest.inventory_artifact != original.manifest.inventory_artifact
        ):
            self._fail(
                "LEGACY_ITEM_CORPUS_COMPLETION_INVENTORY_INVALID",
                "completion inventory authority differs",
            )
        try:
            self._require_resolution(
                resolved.inventory_artifact_resolution,
                pointer=original.manifest.inventory_artifact,
                artifact_types={"legacy-source-inventory"},
            )
        except ValueError as exc:
            self._fail(
                "LEGACY_ITEM_CORPUS_COMPLETION_INVENTORY_INVALID",
                "completion inventory Artifact does not resolve exactly",
                exc,
            )

        replacements = {
            replacement.predecessor_work_unit_id: replacement
            for replacement in recovery.replacements
        }
        failed_original_ids = {
            key
            for key, value in original_by_id.items()
            if isinstance(value, FailedTerminalWorkUnit)
        }
        if failed_original_ids != set(replacements):
            self._fail(
                "LEGACY_ITEM_CORPUS_COMPLETION_RECOVERY_PARTITION_INVALID",
                "completion recovery does not exactly cover failed originals",
            )
        successor_manifest_by_id = {
            unit.work_unit_id: unit for unit in successor.manifest.work_units
        }
        if set(successor_by_id) != {
            replacement.successor_work_unit_id for replacement in recovery.replacements
        }:
            self._fail(
                "LEGACY_ITEM_CORPUS_COMPLETION_SUCCESSOR_SCOPE_INVALID",
                "completion successor scope differs from recovery authority",
            )

        effective: list[
            tuple[
                LegacyExtractionBatchWorkUnitV2,
                LegacyExtractionBatchWorkUnitV2,
                AcceptedTerminalWorkUnit,
            ]
        ] = []
        for original_unit in original.manifest.work_units:
            terminal = original_by_id[original_unit.work_unit_id]
            replacement = replacements.get(original_unit.work_unit_id)
            if replacement is None:
                if not isinstance(terminal, AcceptedTerminalWorkUnit):
                    self._fail(
                        "LEGACY_ITEM_CORPUS_COMPLETION_ORIGINAL_STATE_INVALID",
                        "non-recovered original is not accepted",
                    )
                effective.append((original_unit, original_unit, terminal))
                continue
            if not isinstance(terminal, FailedTerminalWorkUnit):
                self._fail(
                    "LEGACY_ITEM_CORPUS_COMPLETION_RECOVERY_PARTITION_INVALID",
                    "authorized predecessor is not failed",
                )
            successor_unit = successor_manifest_by_id.get(replacement.successor_work_unit_id)
            successor_terminal = successor_by_id.get(replacement.successor_work_unit_id)
            if (
                successor_unit is None
                or not isinstance(successor_terminal, AcceptedTerminalWorkUnit)
                or replacement.predecessor_ordinal != original_unit.ordinal
                or replacement.predecessor_extraction_request_id
                != original_unit.request.extraction_request_id
                or replacement.predecessor_request_sha256 != original_unit.request.request_sha256
                or replacement.predecessor_bundle_revision_id
                != original_unit.request.bundle.assessment_source_bundle_revision_id
                or replacement.expected_item_numbers != original_unit.request.expected_item_numbers
                or replacement.expected_item_numbers_sha256
                != original_unit.expected_item_numbers_sha256
                or replacement.successor_ordinal != successor_unit.ordinal
                or replacement.successor_extraction_request_id
                != successor_unit.request.extraction_request_id
                or terminal.error_code != replacement.failure_code
                or terminal.workflow_id != replacement.predecessor_workflow_id
                or terminal.platform_job_id != replacement.predecessor_platform_job_id
                or terminal.workflow_failure_code != replacement.workflow_failure_code
                or terminal.job_error_code != replacement.job_error_code
                or terminal.failure_message_sha256 != replacement.failure_message_sha256
                or terminal.result_present is not False
                or terminal.receipt_present is not False
                or terminal.acceptance_present is not False
            ):
                self._fail(
                    "LEGACY_ITEM_CORPUS_COMPLETION_RECOVERY_POINTER_DRIFT",
                    "completion replacement differs from pinned manifests",
                )
            effective.append((original_unit, successor_unit, successor_terminal))

        accepted_terminals = tuple(value[2] for value in effective)
        evidence_identity_groups = (
            tuple(value.extraction_request_id for value in accepted_terminals),
            tuple(value.extraction_result_id for value in accepted_terminals),
            tuple(value.result_artifact.artifact_revision_id for value in accepted_terminals),
            tuple(value.extraction_receipt_sha256 for value in accepted_terminals),
            tuple(value.acceptance_id for value in accepted_terminals),
            tuple(value.acceptance_artifact.artifact_revision_id for value in accepted_terminals),
        )
        if any(len(values) != len(set(values)) for values in evidence_identity_groups):
            self._fail(
                "LEGACY_ITEM_CORPUS_COMPLETION_EFFECTIVE_EVIDENCE_DUPLICATE",
                "completion effective work-unit evidence is not one-to-one",
            )

        expected_keys: set[tuple[str, int]] = set()
        accepted_by_key: dict[tuple[str, int], _AcceptedKey] = {}
        for original_unit, effective_unit, terminal in effective:
            keys = {
                (
                    original_unit.request.bundle.assessment_source_bundle_revision_id,
                    item_number,
                )
                for item_number in original_unit.request.expected_item_numbers
            }
            if expected_keys.intersection(keys):
                self._fail(
                    "LEGACY_ITEM_CORPUS_COMPLETION_EXPECTED_DUPLICATE",
                    "completion expected item scope contains duplicates",
                )
            expected_keys.update(keys)
            for accepted in self._accepted_items(effective_unit, terminal):
                key = (
                    accepted.bundle.assessment_source_bundle_revision_id,
                    accepted.item_number,
                )
                if key in accepted_by_key:
                    self._fail(
                        "LEGACY_ITEM_CORPUS_COMPLETION_ACCEPTANCE_CONFLICT",
                        "completion item has multiple effective acceptances",
                    )
                accepted_by_key[key] = accepted
        if set(accepted_by_key) != expected_keys:
            self._fail(
                "LEGACY_ITEM_CORPUS_COMPLETION_NOT_EXACT",
                "completion accepted item set differs from expected scope",
            )

        expected_key_documents = [
            {"bundle_revision_id": bundle_revision_id, "item_number": item_number}
            for bundle_revision_id, item_number in sorted(expected_keys)
        ]
        accepted_map_documents = [
            {
                "bundle_revision_id": bundle_revision_id,
                "item_number": item_number,
                "acceptance_id": accepted_by_key[(bundle_revision_id, item_number)].acceptance_id,
                "acceptance_sha256": accepted_by_key[
                    (bundle_revision_id, item_number)
                ].acceptance_sha256,
            }
            for bundle_revision_id, item_number in sorted(expected_keys)
        ]
        expected_sha256 = content_sha256(expected_key_documents)
        accepted_sha256 = content_sha256(accepted_map_documents)
        coverage_id = (
            "itemcoverage_"
            + content_sha256(
                {
                    "inventory_id": command.inventory_id,
                    "inventory_sha256": command.inventory_sha256,
                    "original_manifest_sha256": original.manifest.manifest_sha256,
                    "successor_manifest_sha256": successor.manifest.manifest_sha256,
                    "recovery_sha256": recovery.recovery_sha256,
                    "expected_item_keys_sha256": expected_sha256,
                    "accepted_item_map_sha256": accepted_sha256,
                }
            ).removeprefix("sha256:")[:32]
        )
        coverage = self._coverage(
            coverage_id=coverage_id,
            inventory_id=command.inventory_id,
            inventory_sha256=command.inventory_sha256,
            expected_keys=expected_keys,
            accepted_by_key=accepted_by_key,
        )
        try:
            validate_contract("legacy-item-corpus-coverage", coverage.model_dump(mode="json"))
        except (JsonSchemaValidationError, ValueError) as exc:
            self._fail(
                "LEGACY_ITEM_CORPUS_COMPLETION_CONTRACT_INVALID",
                "derived completion coverage is invalid",
                exc,
            )

        coverage_artifact = self.artifacts.commit_coverage(
            coverage,
            # Caller/actor metadata is deliberately absent from the durable Artifact identity.
            idempotency_key=f"legacy-item-corpus-coverage:{coverage.coverage_id}",
        )
        if (
            coverage_artifact.member_path != "coverage.json"
            or coverage_artifact.schema_ref
            != "eom://schemas/legacy-assessment/legacy-item-corpus-coverage/1.0"
            or coverage_artifact.media_type != "application/json"
            or coverage_artifact.sha256
            != sha256_bytes(canonical_json_bytes(coverage.model_dump(mode="json")))
        ):
            self._fail(
                "LEGACY_ITEM_CORPUS_COMPLETION_ARTIFACT_INVALID",
                "committed completion coverage pointer differs",
            )
        registered = self.registry.register_coverage(
            coverage,
            coverage_artifact=coverage_artifact,
        )
        if (
            registered.logical_id != coverage.coverage_id
            or registered.revision_id != coverage_artifact.artifact_revision_id
        ):
            self._fail(
                "LEGACY_ITEM_CORPUS_COMPLETION_REGISTRATION_INVALID",
                "completion coverage registry result differs",
            )

        original_evidence = self._batch_evidence(original)
        successor_evidence = self._batch_evidence(successor)
        receipt_document: dict[str, object] = {
            "schema_version": "legacy-item-corpus-completion-receipt/1.0",
            "status": "COMPLETE",
            "requested_by": command.requested_by,
            "command_sha256": command.command_sha256,
            "inventory_id": command.inventory_id,
            "inventory_sha256": command.inventory_sha256,
            "inventory_artifact": original.manifest.inventory_artifact.model_dump(mode="json"),
            "original_batch": original_evidence.model_dump(mode="json"),
            "successor_batch": successor_evidence.model_dump(mode="json"),
            "recovery_sha256": recovery.recovery_sha256,
            "recovery_artifact": command.recovery_artifact.model_dump(mode="json"),
            "coverage_id": coverage.coverage_id,
            "coverage_sha256": coverage.coverage_sha256,
            "coverage_artifact": coverage_artifact.model_dump(mode="json"),
            "original_work_unit_count": len(original.manifest.work_units),
            "effective_work_unit_count": len(effective),
            "recovered_work_unit_count": len(replacements),
            "expected_item_count": len(expected_keys),
            "accepted_item_count": len(accepted_by_key),
            "missing_item_count": 0,
            "conflict_item_count": 0,
            "expected_item_keys_sha256": expected_sha256,
            "accepted_item_map_sha256": accepted_sha256,
            # Max accepted review time is immutable and deterministic; replay does not read a clock.
            "created_at": coverage.created_at.isoformat().replace("+00:00", "Z"),
            "receipt_sha256": "sha256:" + "0" * 64,
        }
        receipt_document["receipt_sha256"] = content_sha256(
            {key: value for key, value in receipt_document.items() if key != "receipt_sha256"}
        )
        receipt = LegacyItemCorpusCompletionReceipt.model_validate(receipt_document)
        verify_corpus_completion_receipt_command(receipt, command)
        return receipt

    def _validate_batch(
        self,
        command: LegacyItemCorpusCompletionCommand,
        batch: ResolvedBatchSnapshot,
        *,
        role: Literal["ORIGINAL", "SUCCESSOR"],
    ) -> dict[str, TerminalWorkUnit]:
        identity = command.original_batch if role == "ORIGINAL" else command.successor_batch
        manifest = batch.manifest
        if (
            manifest.extraction_batch_id != identity.extraction_batch_id
            or manifest.manifest_sha256 != identity.manifest_sha256
            or manifest.inventory_id != command.inventory_id
            or manifest.inventory_sha256 != command.inventory_sha256
            or batch.manifest_artifact.member_path != "legacy-item-extraction-batch.json"
            or batch.manifest_artifact.schema_ref
            != "eom://schemas/legacy-assessment/legacy-item-extraction-batch/1.1"
            or batch.manifest_artifact.media_type != "application/json"
            or batch.manifest_artifact.sha256
            != sha256_bytes(canonical_json_bytes(manifest.model_dump(mode="json")))
        ):
            self._fail(
                "LEGACY_ITEM_CORPUS_COMPLETION_BATCH_POINTER_INVALID",
                "completion batch manifest pointer differs",
            )
        try:
            self._require_resolution(
                batch.manifest_artifact_resolution,
                pointer=batch.manifest_artifact,
                artifact_types={"legacy-item-extraction-batch"},
            )
        except ValueError as exc:
            self._fail(
                "LEGACY_ITEM_CORPUS_COMPLETION_BATCH_POINTER_INVALID",
                "completion batch manifest Artifact does not resolve exactly",
                exc,
            )
        manifest_ids = tuple(unit.work_unit_id for unit in manifest.work_units)
        manifest_order = {work_unit_id: index for index, work_unit_id in enumerate(manifest_ids)}
        terminal_ids = tuple(value.work_unit_id for value in batch.work_units)
        if (
            any(value not in manifest_order for value in terminal_ids)
            or terminal_ids
            != tuple(sorted(terminal_ids, key=lambda value: manifest_order.get(value, -1)))
            or len(set(terminal_ids)) != len(terminal_ids)
            or set(terminal_ids) != set(manifest_ids)
        ):
            self._fail(
                "LEGACY_ITEM_CORPUS_COMPLETION_BATCH_SET_INVALID",
                "completion terminal work-unit set differs from its manifest",
            )
        by_id = {value.work_unit_id: value for value in batch.work_units}
        for unit in manifest.work_units:
            terminal = by_id[unit.work_unit_id]
            if (
                terminal.extraction_batch_id != manifest.extraction_batch_id
                or terminal.ordinal != unit.ordinal
                or terminal.extraction_request_id != unit.request.extraction_request_id
                or terminal.request_sha256 != unit.request.request_sha256
                or terminal.completed_at.tzinfo is None
                or terminal.completed_at.utcoffset() != UTC.utcoffset(terminal.completed_at)
            ):
                self._fail(
                    "LEGACY_ITEM_CORPUS_COMPLETION_WORK_UNIT_POINTER_INVALID",
                    "completion terminal work unit differs from its manifest",
                )
            if isinstance(terminal, FailedTerminalWorkUnit) and (
                terminal.result_present is not False
                or terminal.receipt_present is not False
                or terminal.acceptance_present is not False
                or not terminal.error_code
            ):
                self._fail(
                    "LEGACY_ITEM_CORPUS_COMPLETION_FAILED_OUTPUT_PRESENT",
                    "completion failed work unit carries output or lacks an error",
                )
        expected_state = "COMPLETED_WITH_GAPS" if role == "ORIGINAL" else "SUCCEEDED"
        accepted_count = sum(
            isinstance(value, AcceptedTerminalWorkUnit) for value in batch.work_units
        )
        failed_count = sum(isinstance(value, FailedTerminalWorkUnit) for value in batch.work_units)
        if (
            batch.state != expected_state
            or accepted_count + failed_count != len(batch.work_units)
            or (role == "ORIGINAL" and failed_count == 0)
            or (role == "SUCCESSOR" and failed_count != 0)
        ):
            self._fail(
                "LEGACY_ITEM_CORPUS_COMPLETION_BATCH_STATE_INVALID",
                "completion batch terminal distribution differs",
            )
        return by_id

    def _accepted_items(
        self,
        effective_unit: LegacyExtractionBatchWorkUnitV2,
        terminal: AcceptedTerminalWorkUnit,
    ) -> tuple[_AcceptedKey, ...]:
        result = terminal.result
        receipt = terminal.extraction_receipt
        acceptance = terminal.acceptance
        result_artifact_hash = sha256_bytes(canonical_json_bytes(result))
        acceptance_artifact_hash = sha256_bytes(
            canonical_json_bytes(acceptance.model_dump(mode="json"))
        )
        try:
            self._require_resolution(
                terminal.result_artifact_resolution,
                pointer=terminal.result_artifact,
                artifact_types={"workflow_support", "legacy-item-extraction-result"},
                manifest_artifact_types={"legacy-item-extraction-result"},
            )
            self._require_resolution(
                terminal.acceptance_artifact_resolution,
                pointer=terminal.acceptance_artifact,
                artifact_types={"legacy-item-extraction-acceptance"},
            )
        except ValueError as exc:
            self._fail(
                "LEGACY_ITEM_CORPUS_COMPLETION_ACCEPTANCE_POINTER_INVALID",
                "completion effective Artifact chain does not resolve exactly",
                exc,
            )
        try:
            validate_legacy_item_extraction_result_for_request(
                result=result,
                request=effective_unit.request,
            )
        except ValueError as exc:
            self._fail(
                "LEGACY_ITEM_CORPUS_COMPLETION_REQUEST_RESULT_INVALID",
                "completion extraction result is outside its effective request",
                exc,
            )
        if (
            terminal.state != "ACCEPTED"
            or terminal.extraction_request_id != result.extraction_request_id
            or terminal.request_sha256 != result.request_sha256
            or terminal.extraction_result_id != result.extraction_result_id
            or terminal.result_sha256 != result.result_sha256
            or terminal.result_artifact.sha256 != result_artifact_hash
            or terminal.result_artifact.member_path != "result.json"
            or terminal.result_artifact.schema_ref
            != "eom://schemas/legacy-assessment/legacy-item-extraction-result/1.0"
            or terminal.result_artifact.media_type != "application/json"
            or receipt.extraction_result_id != result.extraction_result_id
            or receipt.extraction_request_id != result.extraction_request_id
            or receipt.request_sha256 != result.request_sha256
            or receipt.result_artifact != terminal.result_artifact
            or receipt.result_sha256 != result.result_sha256
            or receipt.observed_page_input_ids != result.observed_page_input_ids
            or receipt.item_numbers != tuple(item.item_number for item in result.items)
            or terminal.extraction_receipt_sha256 != receipt.receipt_sha256
            or terminal.acceptance_id != acceptance.acceptance_id
            or terminal.acceptance_sha256 != acceptance.acceptance_sha256
            or terminal.acceptance_artifact.member_path != "acceptance.json"
            or terminal.acceptance_artifact.schema_ref
            != "eom://schemas/legacy-assessment/legacy-item-extraction-acceptance/1.0"
            or terminal.acceptance_artifact.media_type != "application/json"
            or terminal.acceptance_artifact.sha256 != acceptance_artifact_hash
            or acceptance.extraction_result.artifact != terminal.result_artifact
            or acceptance.extraction_result.extraction_result_id != result.extraction_result_id
            or acceptance.extraction_result.result_sha256 != result.result_sha256
            or acceptance.acceptance_id != terminal.acceptance_id
            or acceptance.acceptance_sha256 != terminal.acceptance_sha256
            or acceptance.state not in {"ACCEPTED", "ACCEPTED_WITH_CORRECTIONS"}
            or acceptance.coverage_state != "COMPLETE"
            or receipt.completed_at > acceptance.reviewed_at
        ):
            self._fail(
                "LEGACY_ITEM_CORPUS_COMPLETION_ACCEPTANCE_POINTER_INVALID",
                "completion effective acceptance chain differs",
            )
        expected_numbers = tuple(effective_unit.request.expected_item_numbers)
        result_by_number = {item.item_number: item for item in result.items}
        decision_by_number = {item.item_number: item for item in acceptance.item_decisions}
        if (
            tuple(sorted(result_by_number)) != expected_numbers
            or tuple(sorted(decision_by_number)) != expected_numbers
            or len(result_by_number) != len(result.items)
            or len(decision_by_number) != len(acceptance.item_decisions)
        ):
            self._fail(
                "LEGACY_ITEM_CORPUS_COMPLETION_ACCEPTANCE_SET_INVALID",
                "completion decision set differs from expected item numbers",
            )
        values: list[_AcceptedKey] = []
        for item_number in expected_numbers:
            proposal = result_by_number[item_number]
            decision = decision_by_number[item_number]
            if decision.item_proposal_id != proposal.item_proposal_id or decision.decision not in {
                "ACCEPT",
                "CORRECT_AND_ACCEPT",
            }:
                self._fail(
                    "LEGACY_ITEM_CORPUS_COMPLETION_DECISION_INVALID",
                    "completion expected item is not accepting",
                )
            values.append(
                _AcceptedKey(
                    bundle=effective_unit.request.bundle,
                    item_number=item_number,
                    acceptance_id=acceptance.acceptance_id,
                    acceptance_sha256=acceptance.acceptance_sha256,
                    reviewed_at=acceptance.reviewed_at,
                )
            )
        return tuple(values)

    @staticmethod
    def _require_resolution(
        resolution: ResolvedArtifactRevision,
        *,
        pointer: AssessmentArtifactMemberPointer,
        artifact_types: set[str],
        manifest_artifact_types: set[str] | None = None,
    ) -> None:
        expected_manifest_types = (
            artifact_types if manifest_artifact_types is None else manifest_artifact_types
        )
        if (
            resolution.pointer != pointer
            or resolution.logical_artifact_type not in artifact_types
            or resolution.manifest_artifact_type not in expected_manifest_types
            or resolution.approved is not True
            or resolution.producing_job_state != "SUCCEEDED"
        ):
            raise ValueError("pinned Artifact Revision resolution differs")

    @staticmethod
    def _coverage(
        *,
        coverage_id: str,
        inventory_id: str,
        inventory_sha256: str,
        expected_keys: set[tuple[str, int]],
        accepted_by_key: dict[tuple[str, int], _AcceptedKey],
    ) -> LegacyItemCorpusCoverage:
        bundle_revisions = sorted({bundle_revision_id for bundle_revision_id, _ in expected_keys})
        bundle_coverages: list[AssessmentBundleCoverage] = []
        for bundle_revision_id in bundle_revisions:
            item_numbers = tuple(
                item_number
                for observed_bundle_revision_id, item_number in sorted(expected_keys)
                if observed_bundle_revision_id == bundle_revision_id
            )
            accepted = tuple(
                accepted_by_key[(bundle_revision_id, number)] for number in item_numbers
            )
            bundle_pointer = accepted[0].bundle
            if any(value.bundle != bundle_pointer for value in accepted[1:]):
                raise LegacyItemCorpusCompletionError(
                    "LEGACY_ITEM_CORPUS_COMPLETION_BUNDLE_CONFLICT",
                    "completion bundle pointer differs within one revision",
                )
            bundle_coverages.append(
                AssessmentBundleCoverage(
                    bundle=bundle_pointer,
                    expected_item_numbers=item_numbers,
                    accepted_items=tuple(
                        AcceptedCoverageItem(
                            item_number=value.item_number,
                            acceptance_id=value.acceptance_id,
                            acceptance_sha256=value.acceptance_sha256,
                        )
                        for value in accepted
                    ),
                    missing_item_numbers=(),
                    conflict_item_numbers=(),
                )
            )
        created_at = max(value.reviewed_at for value in accepted_by_key.values())
        document: dict[str, object] = {
            "schema_version": "legacy-item-corpus-coverage/1.0",
            "coverage_id": coverage_id,
            "inventory_id": inventory_id,
            "inventory_sha256": inventory_sha256,
            "bundle_coverages": [value.model_dump(mode="json") for value in bundle_coverages],
            "expected_item_count": len(expected_keys),
            "accepted_item_count": len(accepted_by_key),
            "missing_item_count": 0,
            "conflict_item_count": 0,
            "state": "COMPLETE",
            "created_at": created_at.isoformat().replace("+00:00", "Z"),
            "coverage_sha256": "sha256:" + "0" * 64,
        }
        document["coverage_sha256"] = content_sha256(
            {key: value for key, value in document.items() if key != "coverage_sha256"}
        )
        return LegacyItemCorpusCoverage.model_validate(document)

    @staticmethod
    def _batch_evidence(
        batch: ResolvedBatchSnapshot,
    ) -> LegacyExtractionBatchCompletionEvidence:
        accepted = sum(isinstance(value, AcceptedTerminalWorkUnit) for value in batch.work_units)
        failed = sum(isinstance(value, FailedTerminalWorkUnit) for value in batch.work_units)
        return LegacyExtractionBatchCompletionEvidence(
            extraction_batch_id=batch.manifest.extraction_batch_id,
            manifest_sha256=batch.manifest.manifest_sha256,
            manifest_artifact=batch.manifest_artifact,
            state=batch.state,
            total_work_unit_count=len(batch.work_units),
            accepted_work_unit_count=accepted,
            failed_work_unit_count=failed,
            other_work_unit_count=len(batch.work_units) - accepted - failed,
        )

    @staticmethod
    def _fail(
        code: str,
        message: str,
        cause: BaseException | None = None,
    ) -> NoReturn:
        error = LegacyItemCorpusCompletionError(code, message)
        if cause is None:
            raise error
        raise error from cause


__all__ = [
    "AcceptedTerminalWorkUnit",
    "CompletionSourceBoundary",
    "CoverageRegistrationEvidence",
    "CoverageRegistryBoundary",
    "FailedTerminalWorkUnit",
    "LegacyItemCorpusCompletionError",
    "LegacyItemCorpusCompletionService",
    "OrchestratorCoverageArtifactBoundary",
    "ResolvedBatchSnapshot",
    "ResolvedCorpusCompletionSnapshot",
    "TerminalWorkUnit",
]
