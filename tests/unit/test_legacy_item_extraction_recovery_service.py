from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from typing import Any, cast

import pytest
from eom_catalog_contracts import (
    LegacyCorpusSourceBinding,
    LegacyExtractionBatchWorkUnitV2,
    LegacyItemExtractionBatchManifestV2,
    LegacyItemExtractionRequest,
    LegacyItemExtractionValidationRecovery,
    derive_legacy_item_extraction_recovery_successor,
    validate_contract,
)
from eom_catalog_service.legacy_item_extraction_recovery_service import (
    LegacyItemExtractionRecoveryError,
    LegacyItemExtractionRecoveryService,
)
from eom_identifiers import content_sha256
from test_legacy_extraction_recovery_contracts import recovery_document
from test_legacy_item_extraction_service import _request


def _rehash_request(document: dict[str, Any]) -> LegacyItemExtractionRequest:
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
    predecessor_preset = authorization["predecessor_preset"]
    assert isinstance(replacements, list)
    assert isinstance(predecessor_preset, dict)
    replacements_by_ordinal = {
        int(replacement["predecessor_ordinal"]): replacement for replacement in replacements
    }
    units: list[LegacyExtractionBatchWorkUnitV2] = []
    for ordinal in range(108):
        replacement = replacements_by_ordinal.get(ordinal)
        seed = f"{ordinal:032x}"
        items = list(replacement["expected_item_numbers"]) if replacement is not None else [1]
        bundle_revision_id = (
            str(replacement["predecessor_bundle_revision_id"])
            if replacement is not None
            else "assessbundlerev_" + f"{ordinal + 1000:032x}"
        )
        request_document = _request().model_dump(mode="json")
        request_document.update(
            {
                "extraction_request_id": (
                    str(replacement["predecessor_extraction_request_id"])
                    if replacement is not None
                    else "itemextractreq_" + f"{ordinal + 1000:032x}"
                ),
                "bundle": {
                    "assessment_source_bundle_id": "assessbundle_" + seed,
                    "assessment_source_bundle_revision_id": bundle_revision_id,
                    "bundle_manifest_sha256": "sha256:" + f"{ordinal + 1:064x}",
                },
                "work_unit_ordinal": ordinal,
                "expected_item_numbers": items,
                "execution_preset_id": predecessor_preset["preset_id"],
                "execution_preset_revision_id": predecessor_preset["preset_revision_id"],
                "execution_preset_sha256": predecessor_preset["preset_sha256"],
            }
        )
        request = _rehash_request(request_document)
        work_unit_id = (
            str(replacement["predecessor_work_unit_id"])
            if replacement is not None
            else "legacyworkunit_" + f"{ordinal + 1000:032x}"
        )
        units.append(
            LegacyExtractionBatchWorkUnitV2(
                work_unit_id=work_unit_id,
                ordinal=ordinal,
                request=request,
                expected_item_numbers_sha256=content_sha256({"item_numbers": items}),
                execution_mode="EXECUTE",
                reuse_accepted=None,
                corpus_source_bindings=(_corpus_binding(),),
            )
        )
        if replacement is not None:
            replacement["predecessor_request_sha256"] = request.request_sha256

    manifest_document: dict[str, Any] = {
        "schema_version": "legacy-item-extraction-batch/1.1",
        "extraction_batch_id": authorization["predecessor_batch_id"],
        "idempotency_key": "predecessor-corpus",
        "inventory_id": "legacyinventory_" + "c" * 32,
        "inventory_sha256": "sha256:" + "c" * 64,
        "inventory_artifact": {
            "artifact_id": "artifact_" + "d" * 32,
            "artifact_revision_id": "rev_" + "d" * 32,
            "member_path": "legacy-source-inventory.json",
            "schema_ref": "eom://schemas/legacy-knowledge/legacy-source-inventory/2.0",
            "media_type": "application/json",
            "sha256": "sha256:" + "d" * 64,
        },
        "failure_policy": "CONTINUE_AND_COLLECT",
        "work_units": [unit.model_dump(mode="json") for unit in units],
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


def test_recovery_builder_is_deterministic_pointer_only_and_executes_exact_three() -> None:
    predecessor, recovery = _predecessor_and_recovery()

    first = derive_legacy_item_extraction_recovery_successor(
        recovery,
        predecessor,
    )
    replay = derive_legacy_item_extraction_recovery_successor(
        recovery,
        predecessor,
    )

    validate_contract("legacy-item-extraction-batch-v2", first.model_dump(mode="json"))
    assert first == replay
    assert first.manifest_sha256 == replay.manifest_sha256
    assert len(first.work_units) == 3
    assert tuple(unit.ordinal for unit in first.work_units) == (0, 1, 2)
    assert all(unit.execution_mode == "EXECUTE" for unit in first.work_units)
    assert all(unit.reuse_accepted is None for unit in first.work_units)
    assert sum(len(unit.request.expected_item_numbers) for unit in first.work_units) == 15
    assert {
        unit.request.bundle.assessment_source_bundle_revision_id for unit in first.work_units
    } == {value.predecessor_bundle_revision_id for value in recovery.replacements}
    assert all(
        unit.request.execution_preset_revision_id == recovery.successor_preset.preset_revision_id
        for unit in first.work_units
    )
    assert {unit.work_unit_id for unit in first.work_units}.isdisjoint(
        {value.predecessor_work_unit_id for value in recovery.replacements}
    )


def test_recovery_builder_does_not_mutate_predecessor_manifest() -> None:
    predecessor, recovery = _predecessor_and_recovery()
    before = deepcopy(predecessor.model_dump(mode="json"))

    derive_legacy_item_extraction_recovery_successor(recovery, predecessor)

    assert predecessor.model_dump(mode="json") == before


def test_recovery_derivation_preserves_every_unauthorized_request_field() -> None:
    predecessor, recovery = _predecessor_and_recovery()
    successor = derive_legacy_item_extraction_recovery_successor(recovery, predecessor)
    predecessor_by_id = {unit.work_unit_id: unit for unit in predecessor.work_units}

    mutable_request_fields = {
        "extraction_request_id",
        "work_unit_ordinal",
        "execution_preset_id",
        "execution_preset_revision_id",
        "execution_preset_sha256",
        "created_at",
        "request_sha256",
    }
    for replacement, successor_unit in zip(
        recovery.replacements,
        successor.work_units,
        strict=True,
    ):
        prior = predecessor_by_id[replacement.predecessor_work_unit_id]
        assert prior.request.model_dump(
            mode="json", exclude=mutable_request_fields
        ) == successor_unit.request.model_dump(mode="json", exclude=mutable_request_fields)
        assert successor_unit.corpus_source_bindings == prior.corpus_source_bindings

    assert successor.inventory_id == predecessor.inventory_id
    assert successor.inventory_sha256 == predecessor.inventory_sha256
    assert successor.inventory_artifact == predecessor.inventory_artifact
    assert successor.failure_policy == predecessor.failure_policy


def test_recovery_derivation_rejects_predecessor_work_unit_pointer_drift() -> None:
    predecessor, recovery = _predecessor_and_recovery()
    document = recovery.model_dump(mode="json")
    replacements = document["replacements"]
    assert isinstance(replacements, list)
    first = replacements[0]
    assert isinstance(first, dict)
    first["predecessor_request_sha256"] = "sha256:" + "f" * 64
    document["recovery_sha256"] = content_sha256(
        {key: value for key, value in document.items() if key != "recovery_sha256"}
    )
    drifted = LegacyItemExtractionValidationRecovery.model_validate(document)

    with pytest.raises(ValueError, match="predecessor work-unit pointer differs"):
        derive_legacy_item_extraction_recovery_successor(drifted, predecessor)


@pytest.mark.parametrize(
    ("replacement_field", "predecessor_value", "error"),
    [
        (
            "successor_work_unit_id",
            lambda unit: unit.work_unit_id,
            "successor work-unit identity is not globally fresh",
        ),
        (
            "successor_extraction_request_id",
            lambda unit: unit.request.extraction_request_id,
            "successor request identity is not globally fresh",
        ),
    ],
)
def test_recovery_derivation_rejects_successor_collision_with_unreplaced_predecessor(
    replacement_field: str,
    predecessor_value: Any,
    error: str,
) -> None:
    predecessor, recovery = _predecessor_and_recovery()
    document = recovery.model_dump(mode="json")
    replacements = document["replacements"]
    assert isinstance(replacements, list)
    first = replacements[0]
    assert isinstance(first, dict)
    unreplaced = predecessor.work_units[0]
    assert unreplaced.work_unit_id not in {
        replacement.predecessor_work_unit_id for replacement in recovery.replacements
    }
    first[replacement_field] = predecessor_value(unreplaced)
    document["recovery_sha256"] = content_sha256(
        {key: value for key, value in document.items() if key != "recovery_sha256"}
    )
    drifted = LegacyItemExtractionValidationRecovery.model_validate(document)

    with pytest.raises(ValueError, match=error):
        derive_legacy_item_extraction_recovery_successor(drifted, predecessor)


def test_recovery_requires_exact_105_accepted_plus_three_failed_distribution() -> None:
    predecessor, recovery = _predecessor_and_recovery()
    exact = SimpleNamespace(
        state="COMPLETED_WITH_GAPS",
        manifest_sha256=recovery.predecessor_manifest_sha256,
        total_work_unit_count=108,
        accepted_count=105,
        failed_count=3,
        pending_count=0,
        claimed_count=0,
        submitted_count=0,
        awaiting_review_count=0,
        cancelled_count=0,
    )

    LegacyItemExtractionRecoveryService._require_exact_predecessor_distribution(
        cast(Any, exact),
        predecessor,
        expected_manifest_sha256=recovery.predecessor_manifest_sha256,
    )
    exact.cancelled_count = 1
    exact.accepted_count = 104

    with pytest.raises(LegacyItemExtractionRecoveryError) as captured:
        LegacyItemExtractionRecoveryService._require_exact_predecessor_distribution(
            cast(Any, exact),
            predecessor,
            expected_manifest_sha256=recovery.predecessor_manifest_sha256,
        )

    assert captured.value.code == "LEGACY_EXTRACTION_RECOVERY_PREDECESSOR_STATE_INVALID"


def test_recovery_runtime_rejects_nonterminal_predecessor_batch_state() -> None:
    predecessor, recovery = _predecessor_and_recovery()

    class NonterminalSession:
        @staticmethod
        def get(_model: object, identity: str) -> object | None:
            if identity == recovery.predecessor_batch_id:
                return SimpleNamespace(
                    state="RUNNING",
                    manifest_sha256=recovery.predecessor_manifest_sha256,
                )
            return None

        @staticmethod
        def scalars(_statement: object) -> tuple[object, ...]:
            return ()

    service = object.__new__(LegacyItemExtractionRecoveryService)
    with pytest.raises(LegacyItemExtractionRecoveryError) as captured:
        service._validate_runtime_history(
            cast(Any, NonterminalSession()),
            recovery=recovery,
            predecessor_manifest=predecessor,
            require_successor_current=True,
        )

    assert captured.value.code == "LEGACY_EXTRACTION_RECOVERY_PREDECESSOR_STATE_INVALID"


def test_recovery_runtime_rejects_failure_message_hash_drift() -> None:
    predecessor, recovery = _predecessor_and_recovery()
    manifest_units = {unit.work_unit_id: unit for unit in predecessor.work_units}
    failed = tuple(
        SimpleNamespace(
            work_unit_id=replacement.predecessor_work_unit_id,
            ordinal=replacement.predecessor_ordinal,
            extraction_request_id=replacement.predecessor_extraction_request_id,
            request_sha256=replacement.predecessor_request_sha256,
            workflow_id=replacement.predecessor_workflow_id,
            platform_job_id=replacement.predecessor_platform_job_id,
            error_code=replacement.failure_code,
            execution_mode="EXECUTE",
            assessment_source_bundle_revision_id=replacement.predecessor_bundle_revision_id,
            expected_item_numbers_sha256=replacement.expected_item_numbers_sha256,
            submission_attempts=1,
            extraction_result_id=None,
            result_sha256=None,
            receipt_artifact_id=None,
            receipt_artifact_revision_id=None,
            receipt_artifact_sha256=None,
            acceptance_id=None,
            acceptance_sha256=None,
        )
        for replacement in recovery.replacements
    )

    class HashDriftSession:
        @staticmethod
        def get(_model: object, identity: str) -> object | None:
            if identity == recovery.predecessor_batch_id:
                return SimpleNamespace(
                    state="COMPLETED_WITH_GAPS",
                    manifest_sha256=recovery.predecessor_manifest_sha256,
                )
            for replacement in recovery.replacements:
                if identity == replacement.predecessor_workflow_id:
                    return SimpleNamespace(
                        definition_id=recovery.predecessor_preset.workflow_definition_id,
                        definition_key="legacy-item-extraction",
                        definition_version=(
                            recovery.predecessor_preset.workflow_definition_version
                        ),
                        definition_hash=recovery.predecessor_preset.workflow_definition_sha256,
                        role_schema_version=recovery.predecessor_preset.role_schema_version,
                        state="FAILED",
                        failure_code=replacement.workflow_failure_code,
                    )
                if identity == replacement.predecessor_platform_job_id:
                    return SimpleNamespace(
                        protocol_version=recovery.predecessor_preset.role_schema_version,
                        task_type="workflow_support",
                        status="FAILED",
                        error_code=replacement.job_error_code,
                        error_message="different immutable failure evidence",
                    )
            return None

        @staticmethod
        def scalars(_statement: object) -> tuple[SimpleNamespace, ...]:
            return failed

        @staticmethod
        def scalar(_statement: object) -> SimpleNamespace:
            return SimpleNamespace(
                workflow_id="workflow_" + "0" * 32,
                platform_job_id="job_" + "0" * 32,
                step_key="extract",
                attempt=1,
                step_type="agent",
                worker_role="support",
                result_schema="legacy-item-extraction-result@1.0",
                state="FAILED",
                error_code="WORKER_RESULT_INVALID",
            )

    assert {manifest_units[record.work_unit_id].request.request_sha256 for record in failed} == {
        replacement.predecessor_request_sha256 for replacement in recovery.replacements
    }
    service = object.__new__(LegacyItemExtractionRecoveryService)
    with pytest.raises(LegacyItemExtractionRecoveryError) as captured:
        service._validate_runtime_history(
            cast(Any, HashDriftSession()),
            recovery=recovery,
            predecessor_manifest=predecessor,
            require_successor_current=True,
        )

    assert captured.value.code == "LEGACY_EXTRACTION_RECOVERY_PREDECESSOR_POINTER_STALE"


def test_instruction_only_successor_rejects_skipped_bundle_revision() -> None:
    predecessor, recovery = _predecessor_and_recovery()
    predecessor_policy = _preset_document(recovery, successor=False)
    successor_policy = _preset_document(recovery, successor=True)

    class SessionWithGap:
        @staticmethod
        def get(_model: object, identity: str) -> object:
            revision_number = (
                1 if identity == recovery.predecessor_preset.instruction_bundle_revision_id else 3
            )
            return SimpleNamespace(revision_number=revision_number)

    with pytest.raises(LegacyItemExtractionRecoveryError) as captured:
        LegacyItemExtractionRecoveryService._require_instruction_only_successor(
            cast(Any, SessionWithGap()),
            predecessor=predecessor_policy,
            successor=successor_policy,
            recovery=recovery,
        )

    assert captured.value.code == "LEGACY_EXTRACTION_RECOVERY_SUCCESSOR_INVALID"
    assert predecessor.manifest_sha256 == recovery.predecessor_manifest_sha256


def test_instruction_only_successor_rejects_timeout_policy_drift() -> None:
    _predecessor, recovery = _predecessor_and_recovery()
    predecessor_policy = _preset_document(recovery, successor=False)
    successor_document = _preset_document(recovery, successor=True).model_dump(mode="json")
    successor_document["role_policies"][0]["timeout_seconds"] = 7199
    successor_document["content_sha256"] = content_sha256(
        {key: value for key, value in successor_document.items() if key != "content_sha256"}
    )
    successor_policy = type(predecessor_policy).model_validate(successor_document)

    class AdjacentSession:
        @staticmethod
        def get(_model: object, identity: str) -> object:
            revision_number = (
                1 if identity == recovery.predecessor_preset.instruction_bundle_revision_id else 2
            )
            return SimpleNamespace(revision_number=revision_number)

    with pytest.raises(LegacyItemExtractionRecoveryError) as captured:
        LegacyItemExtractionRecoveryService._require_instruction_only_successor(
            cast(Any, AdjacentSession()),
            predecessor=predecessor_policy,
            successor=successor_policy,
            recovery=recovery,
        )

    assert captured.value.code == "LEGACY_EXTRACTION_RECOVERY_SUCCESSOR_INVALID"


def _preset_document(
    recovery: LegacyItemExtractionValidationRecovery,
    *,
    successor: bool,
) -> Any:
    pointer = recovery.successor_preset if successor else recovery.predecessor_preset
    document: dict[str, Any] = {
        "schema_version": "execution-preset-revision/1.0",
        "preset_id": pointer.preset_id,
        "preset_revision_id": pointer.preset_revision_id,
        "revision_number": 4 if successor else 2,
        "state": "RELEASED",
        "display_name": "Legacy extraction",
        "description": "Exact extraction policy",
        "role_policies": [
            {
                "role": "support",
                "model_candidates": [{"model": "gpt-5.6-terra", "reasoning_effort": "xhigh"}],
                "instruction_bundle": {
                    "bundle_id": pointer.instruction_bundle_id,
                    "bundle_revision_id": pointer.instruction_bundle_revision_id,
                    "manifest_artifact": {
                        "artifact_id": "artifact_" + ("2" if successor else "1") * 32,
                        "artifact_revision_id": "rev_" + ("2" if successor else "1") * 32,
                        "sha256": pointer.instruction_manifest_sha256,
                        "schema_ref": ("eom://schemas/workflow/instruction-bundle-manifest/1.0"),
                        "media_type": "application/json",
                        "logical_name": "instruction-bundle.json",
                    },
                    "manifest_sha256": pointer.instruction_manifest_sha256,
                },
                "reference_bundle": None,
                "worker_pool_key": "legacy-extraction",
                "timeout_seconds": 7200,
                "sandbox": "read-only",
                "network": "disabled",
            }
        ],
        "capacity_policy_revision_id": pointer.capacity_policy_revision_id,
        "general_knowledge_policy": "DENY",
        "compatible_workflow_protocols": [pointer.role_schema_version],
        "content_sha256": "sha256:" + "0" * 64,
        "created_at": "2026-09-09T06:00:00Z" if successor else "2026-09-01T00:02:00Z",
    }
    document["content_sha256"] = content_sha256(
        {key: value for key, value in document.items() if key != "content_sha256"}
    )
    from eom_workflow import ExecutionPresetRevision

    return ExecutionPresetRevision.model_validate(document)
