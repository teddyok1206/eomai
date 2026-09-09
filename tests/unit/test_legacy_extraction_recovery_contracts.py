from __future__ import annotations

from copy import deepcopy

import pytest
from eom_catalog_contracts import (
    LegacyItemExtractionValidationRecovery,
    validate_contract,
)
from eom_identifiers import content_sha256
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError as PydanticValidationError


def _preset_pointer(*, successor: bool) -> dict[str, object]:
    return {
        "preset_id": "execpreset_" + "1" * 32,
        "preset_revision_id": "execpresetrev_" + ("3" if successor else "2") * 32,
        "preset_revision_number": 4 if successor else 2,
        "preset_sha256": "sha256:" + ("4" if successor else "3") * 64,
        "preset_policy_sha256": "sha256:" + ("6" if successor else "5") * 64,
        "capacity_policy_revision_id": "capacityrev_" + "7" * 32,
        "capacity_policy_sha256": "sha256:" + "8" * 64,
        "instruction_bundle_id": "instrbundle_" + "9" * 32,
        "instruction_bundle_revision_id": "instrrev_" + ("b" if successor else "a") * 32,
        "instruction_revision_number": 2 if successor else 1,
        "instruction_manifest_sha256": "sha256:" + ("d" if successor else "c") * 64,
        "instruction_content_sha256": "sha256:" + ("f" if successor else "e") * 64,
        "workflow_definition_id": "wfdef_" + "1" * 32,
        "workflow_definition_version": "1.0.0",
        "workflow_definition_sha256": "sha256:" + "2" * 64,
        "role_schema_version": "workflow-role/1.14.0",
        "role_schema_sha256": "sha256:" + "3" * 64,
    }


def _replacement(
    ordinal: int,
    successor_ordinal: int,
    first_item: int,
    diagnosis: str,
) -> dict[str, object]:
    seed = f"{ordinal:032x}"
    items = list(range(first_item, first_item + 5))
    return {
        "predecessor_work_unit_id": "legacyworkunit_" + seed,
        "predecessor_ordinal": ordinal,
        "predecessor_extraction_request_id": "itemextractreq_" + seed,
        "predecessor_request_sha256": "sha256:" + f"{ordinal:064x}",
        "predecessor_bundle_revision_id": "assessbundlerev_" + seed,
        "predecessor_workflow_id": "workflow_" + seed,
        "predecessor_platform_job_id": "job_" + seed,
        "failure_code": "LEGACY_ITEM_EXTRACTION_WORKFLOW_FAILED",
        "workflow_failure_code": "WORKER_RESULT_INVALID",
        "job_error_code": "WORKER_RESULT_INVALID",
        "failure_message_sha256": "sha256:" + f"{ordinal + 1:064x}",
        "diagnosis_code": diagnosis,
        "expected_item_numbers": items,
        "expected_item_numbers_sha256": content_sha256({"item_numbers": items}),
        "successor_work_unit_id": "legacyworkunit_" + f"{ordinal + 100:032x}",
        "successor_ordinal": successor_ordinal,
        "successor_extraction_request_id": "itemextractreq_" + f"{ordinal + 100:032x}",
    }


def recovery_document() -> dict[str, object]:
    document: dict[str, object] = {
        "schema_version": "legacy-item-extraction-validation-recovery/1.0",
        "predecessor_batch_id": "legacybatch_" + "4" * 32,
        "predecessor_manifest_sha256": "sha256:" + "5" * 64,
        "predecessor_preset": _preset_pointer(successor=False),
        "successor_batch_id": "legacybatch_" + "6" * 32,
        "successor_idempotency_key": "past-exam-validation-recovery-v1",
        "successor_preset": _preset_pointer(successor=True),
        "replacements": [
            _replacement(23, 0, 16, "DUPLICATE_STATEMENT_EXPLANATION_ID"),
            _replacement(65, 1, 6, "BODY_BLOCK_DISCRIMINATOR_MISMATCH"),
            _replacement(85, 2, 5, "NONE_VISUAL_RENDERING_CONFLICT"),
        ],
        "created_at": "2026-09-09T06:00:00Z",
        "recovery_sha256": "sha256:" + "0" * 64,
    }
    document["recovery_sha256"] = content_sha256(
        {key: value for key, value in document.items() if key != "recovery_sha256"}
    )
    return document


def _rehash(document: dict[str, object]) -> None:
    document["recovery_sha256"] = content_sha256(
        {key: value for key, value in document.items() if key != "recovery_sha256"}
    )


def test_validation_recovery_is_schema_first_and_canonically_hashed() -> None:
    document = recovery_document()

    validate_contract("legacy-item-extraction-validation-recovery", document)
    recovery = LegacyItemExtractionValidationRecovery.model_validate(document)

    assert len(recovery.replacements) == 3
    assert sum(len(value.expected_item_numbers) for value in recovery.replacements) == 15
    assert recovery.recovery_sha256 == document["recovery_sha256"]


def test_validation_recovery_json_schema_requires_exactly_three_ranges() -> None:
    document = recovery_document()
    document["replacements"] = document["replacements"][:2]  # type: ignore[index]
    _rehash(document)

    with pytest.raises(JsonSchemaValidationError):
        validate_contract("legacy-item-extraction-validation-recovery", document)


@pytest.mark.parametrize(
    "mutation",
    (
        "DUPLICATE_DIAGNOSIS",
        "NONCONTIGUOUS_SUCCESSOR",
        "REUSED_WORK_UNIT",
        "CAPACITY_DRIFT",
        "PRESET_REVISION_GAP",
        "INSTRUCTION_REVISION_GAP",
        "STALE_SELF_HASH",
    ),
)
def test_validation_recovery_rejects_semantic_or_pointer_drift(mutation: str) -> None:
    document = recovery_document()
    replacements = document["replacements"]
    assert isinstance(replacements, list)
    successor = document["successor_preset"]
    assert isinstance(successor, dict)
    if mutation == "DUPLICATE_DIAGNOSIS":
        replacements[1]["diagnosis_code"] = replacements[0]["diagnosis_code"]
    elif mutation == "NONCONTIGUOUS_SUCCESSOR":
        replacements[1]["successor_ordinal"] = 2
    elif mutation == "REUSED_WORK_UNIT":
        replacements[0]["successor_work_unit_id"] = replacements[0]["predecessor_work_unit_id"]
    elif mutation == "CAPACITY_DRIFT":
        successor["capacity_policy_revision_id"] = "capacityrev_" + "0" * 32
    elif mutation == "PRESET_REVISION_GAP":
        successor["preset_revision_number"] = 5
    elif mutation == "INSTRUCTION_REVISION_GAP":
        successor["instruction_revision_number"] = 3
    elif mutation == "STALE_SELF_HASH":
        document["created_at"] = "2026-09-09T06:00:01Z"
    if mutation != "STALE_SELF_HASH":
        _rehash(document)

    with pytest.raises(PydanticValidationError):
        LegacyItemExtractionValidationRecovery.model_validate(deepcopy(document))
