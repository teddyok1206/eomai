from __future__ import annotations

from copy import deepcopy

import pytest
from eom_catalog_contracts import (
    LegacyItemCorpusCompletionCommand,
    LegacyItemCorpusCompletionReceipt,
    LegacyItemExtractionValidationRecovery,
    catalog_schema_inventory,
    load_schema,
    verify_corpus_completion_receipt_command,
    verify_corpus_completion_recovery_authority,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from jsonschema import Draft202012Validator
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError as PydanticValidationError
from referencing import Registry, Resource
from test_legacy_extraction_recovery_contracts import recovery_document


def _schema(name: str) -> dict[str, object]:
    routes = {
        "legacy-item-corpus-completion-command-v1.schema.json": (
            "legacy-item-corpus-completion-command"
        ),
        "legacy-item-corpus-completion-receipt-v1.schema.json": (
            "legacy-item-corpus-completion-receipt"
        ),
    }
    return load_schema(routes[name])


def _registry(*schemas: dict[str, object]) -> Registry[object]:
    resources: list[tuple[str, Resource[object]]] = []
    for name, _entry in catalog_schema_inventory():
        schema = load_schema(name)
        identifier = schema.get("$id")
        assert isinstance(identifier, str)
        resources.append((identifier, Resource.from_contents(schema)))
    for schema in schemas:
        identifier = schema.get("$id")
        assert isinstance(identifier, str)
        resources.append((identifier, Resource.from_contents(schema)))
    return Registry().with_resources(resources)


def _artifact(number: int, schema_ref: str, member_path: str) -> dict[str, str]:
    return {
        "artifact_id": f"artifact_{number:032x}",
        "artifact_revision_id": f"rev_{number:032x}",
        "member_path": member_path,
        "schema_ref": schema_ref,
        "media_type": "application/json",
        "sha256": f"sha256:{number:064x}",
    }


def _command() -> dict[str, object]:
    recovery = recovery_document()
    typed_recovery = LegacyItemExtractionValidationRecovery.model_validate(recovery)
    recovery_artifact = _artifact(
        9,
        "eom://schemas/legacy-assessment/legacy-item-extraction-validation-recovery/1.0",
        "validation-recovery.json",
    )
    recovery_artifact["sha256"] = sha256_bytes(canonical_json_bytes(typed_recovery) + b"\n")
    payload: dict[str, object] = {
        "schema_version": "legacy-item-corpus-completion-command/1.0",
        "inventory_id": "legacyinventory_" + "1" * 32,
        "inventory_sha256": "sha256:" + "2" * 64,
        "original_batch": {
            "extraction_batch_id": recovery["predecessor_batch_id"],
            "manifest_sha256": recovery["predecessor_manifest_sha256"],
        },
        "successor_batch": {
            "extraction_batch_id": recovery["successor_batch_id"],
            "manifest_sha256": "sha256:" + "7" * 64,
        },
        "recovery_sha256": recovery["recovery_sha256"],
        "recovery_artifact": recovery_artifact,
        "requested_by": "operator_stage_c",
        "command_sha256": "sha256:" + "0" * 64,
    }
    payload["command_sha256"] = content_sha256(
        {key: value for key, value in payload.items() if key != "command_sha256"}
    )
    return payload


def _receipt(command: dict[str, object]) -> dict[str, object]:
    original_batch = command["original_batch"]
    successor_batch = command["successor_batch"]
    assert isinstance(original_batch, dict)
    assert isinstance(successor_batch, dict)
    payload: dict[str, object] = {
        "schema_version": "legacy-item-corpus-completion-receipt/1.0",
        "status": "COMPLETE",
        "requested_by": command["requested_by"],
        "command_sha256": command["command_sha256"],
        "inventory_id": command["inventory_id"],
        "inventory_sha256": command["inventory_sha256"],
        "inventory_artifact": _artifact(
            1,
            "eom://schemas/legacy-knowledge/legacy-source-inventory/2.0",
            "legacy-source-inventory.json",
        ),
        "original_batch": {
            **original_batch,
            "manifest_artifact": _artifact(
                2,
                "eom://schemas/legacy-assessment/legacy-item-extraction-batch/1.1",
                "legacy-item-extraction-batch.json",
            ),
            "state": "COMPLETED_WITH_GAPS",
            "total_work_unit_count": 6,
            "accepted_work_unit_count": 3,
            "failed_work_unit_count": 3,
            "other_work_unit_count": 0,
        },
        "successor_batch": {
            **successor_batch,
            "manifest_artifact": _artifact(
                3,
                "eom://schemas/legacy-assessment/legacy-item-extraction-batch/1.1",
                "legacy-item-extraction-batch.json",
            ),
            "state": "SUCCEEDED",
            "total_work_unit_count": 3,
            "accepted_work_unit_count": 3,
            "failed_work_unit_count": 0,
            "other_work_unit_count": 0,
        },
        "recovery_sha256": command["recovery_sha256"],
        "recovery_artifact": command["recovery_artifact"],
        "coverage_id": "itemcoverage_" + "4" * 32,
        "coverage_sha256": "sha256:" + "5" * 64,
        "coverage_artifact": _artifact(
            4,
            "eom://schemas/legacy-assessment/legacy-item-corpus-coverage/1.0",
            "coverage.json",
        ),
        "original_work_unit_count": 6,
        "effective_work_unit_count": 6,
        "recovered_work_unit_count": 3,
        "expected_item_count": 27,
        "accepted_item_count": 27,
        "missing_item_count": 0,
        "conflict_item_count": 0,
        "expected_item_keys_sha256": "sha256:" + "6" * 64,
        "accepted_item_map_sha256": "sha256:" + "7" * 64,
        "created_at": "2026-09-09T06:00:00Z",
        "receipt_sha256": "sha256:" + "0" * 64,
    }
    payload["receipt_sha256"] = content_sha256(
        {key: value for key, value in payload.items() if key != "receipt_sha256"}
    )
    return payload


def test_command_and_receipt_are_schema_first_and_self_hashed() -> None:
    command_schema = _schema("legacy-item-corpus-completion-command-v1.schema.json")
    receipt_schema = _schema("legacy-item-corpus-completion-receipt-v1.schema.json")
    registry = _registry(command_schema, receipt_schema)
    command = _command()
    Draft202012Validator(command_schema, registry=registry).validate(command)
    typed_command = LegacyItemCorpusCompletionCommand.model_validate(command)
    receipt = _receipt(command)
    Draft202012Validator(receipt_schema, registry=registry).validate(receipt)
    typed_receipt = LegacyItemCorpusCompletionReceipt.model_validate(receipt)

    assert typed_receipt.expected_item_count == 27
    assert typed_receipt.original_work_unit_count == 6
    verify_corpus_completion_recovery_authority(
        typed_command,
        LegacyItemExtractionValidationRecovery.model_validate(recovery_document()),
    )
    verify_corpus_completion_receipt_command(typed_receipt, typed_command)


def test_generic_catalog_receipt_has_no_release_specific_cardinality() -> None:
    receipt = LegacyItemCorpusCompletionReceipt.model_validate(_receipt(_command()))

    assert receipt.expected_item_count != 520
    assert receipt.original_work_unit_count != 108


def test_command_rejects_mixed_recovery_lineage() -> None:
    command = _command()
    typed_command = LegacyItemCorpusCompletionCommand.model_validate(command)
    recovery = LegacyItemExtractionValidationRecovery.model_validate(recovery_document())
    recovery = recovery.model_copy(update={"predecessor_batch_id": "legacybatch_" + "9" * 32})

    with pytest.raises(ValueError, match="authority differs"):
        verify_corpus_completion_recovery_authority(typed_command, recovery)


def test_command_rejects_self_hash_drift() -> None:
    command = _command()
    command["command_sha256"] = "sha256:" + "9" * 64

    with pytest.raises(PydanticValidationError, match="command hash"):
        LegacyItemCorpusCompletionCommand.model_validate(command)


def test_command_rejects_recovery_artifact_document_hash_drift() -> None:
    command = _command()
    recovery_artifact = command["recovery_artifact"]
    assert isinstance(recovery_artifact, dict)
    recovery_artifact["sha256"] = "sha256:" + "9" * 64
    command["command_sha256"] = content_sha256(
        {key: value for key, value in command.items() if key != "command_sha256"}
    )

    typed_command = LegacyItemCorpusCompletionCommand.model_validate(command)
    recovery = LegacyItemExtractionValidationRecovery.model_validate(recovery_document())

    with pytest.raises(ValueError, match="authority differs"):
        verify_corpus_completion_recovery_authority(typed_command, recovery)


def test_recovery_document_self_hash_and_artifact_member_byte_hash_are_distinct() -> None:
    command = LegacyItemCorpusCompletionCommand.model_validate(_command())
    recovery = LegacyItemExtractionValidationRecovery.model_validate(recovery_document())

    assert recovery.recovery_sha256 == content_sha256(
        recovery.model_dump(mode="json", exclude={"recovery_sha256"})
    )
    assert command.recovery_artifact.sha256 == sha256_bytes(canonical_json_bytes(recovery) + b"\n")
    assert command.recovery_artifact.sha256 != recovery.recovery_sha256


def test_receipt_rejects_recovery_artifact_cross_bind_drift() -> None:
    command = LegacyItemCorpusCompletionCommand.model_validate(_command())
    receipt_document = _receipt(command.model_dump(mode="json"))
    receipt_document["recovery_artifact"] = _artifact(
        99,
        "eom://schemas/legacy-assessment/legacy-item-extraction-validation-recovery/1.0",
        "validation-recovery.json",
    )
    receipt_document["receipt_sha256"] = content_sha256(
        {key: value for key, value in receipt_document.items() if key != "receipt_sha256"}
    )
    receipt = LegacyItemCorpusCompletionReceipt.model_validate(receipt_document)

    with pytest.raises(ValueError, match="exact command authority"):
        verify_corpus_completion_receipt_command(receipt, command)


def test_receipt_rejects_subset_claimed_complete() -> None:
    receipt = _receipt(_command())
    receipt["accepted_item_count"] = 26
    receipt["receipt_sha256"] = content_sha256(
        {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    )

    with pytest.raises(PydanticValidationError, match="expected and accepted"):
        LegacyItemCorpusCompletionReceipt.model_validate(receipt)


def test_receipt_rejects_wrong_recovery_distribution() -> None:
    receipt = _receipt(_command())
    successor = receipt["successor_batch"]
    assert isinstance(successor, dict)
    successor["accepted_work_unit_count"] = 2
    successor["failed_work_unit_count"] = 1
    receipt["receipt_sha256"] = content_sha256(
        {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    )

    with pytest.raises(PydanticValidationError, match="recovered partition"):
        LegacyItemCorpusCompletionReceipt.model_validate(receipt)


def test_command_schema_rejects_extra_property() -> None:
    command_schema = _schema("legacy-item-corpus-completion-command-v1.schema.json")
    registry = _registry(command_schema)
    command = deepcopy(_command())
    command["expected_item_count"] = 520

    with pytest.raises(JsonSchemaValidationError):
        Draft202012Validator(command_schema, registry=registry).validate(command)
