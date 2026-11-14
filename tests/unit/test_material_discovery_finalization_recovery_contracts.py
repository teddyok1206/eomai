"""Native finalization recovery is closed; existing model retry stays unchanged."""

from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest
from eom_catalog_contracts.material_discovery_finalization_recovery import (
    NativeMaterialDiscoveryFinalizationRecoveryResult,
    RecoverNativeMaterialDiscoveryFinalizationCommand,
)
from eom_catalog_contracts.material_learning_intake import MaterialLearningRetryResult
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES, validate_contract
from jsonschema.exceptions import ValidationError as JsonSchemaError

ROOT = Path(__file__).resolve().parents[2]
COMMAND_SCHEMA = "material-native-discovery-finalization-recovery-v1"
RESULT_SCHEMA = "material-native-discovery-finalization-recovery-result-v1"


def command_data():
    return dict(
        actor_id="operator_" + "1" * 32,
        run_id="materialrun_" + "2" * 32,
        expected_updated_at=datetime(2026, 11, 14, tzinfo=UTC).isoformat(),
        expected_prepared_sha256="sha256:" + "3" * 64,
        target_source_commit="4" * 40,
    )


def result_data():
    return dict(
        predecessor_run_id="materialrun_" + "2" * 32,
        run_id="materialrun_" + "5" * 32,
        material_id="material_" + "6" * 32,
        material_revision_id="materialrev_" + "7" * 32,
        prepared=dict(
            artifact_id="artifact_" + "8" * 32,
            artifact_revision_id="rev_" + "9" * 32,
            member_path="material/prepared.json",
            schema_ref="eom://schemas/material-learning/prepared/2.0",
            media_type="application/json",
            sha256="sha256:" + "3" * 64,
            bytes=256,
        ),
        source_commit="4" * 40,
        reused_tasks=7,
        state="DISCOVERING",
        replayed=False,
    )


def test_closed_command_roundtrip_and_frozen_identity():
    command = RecoverNativeMaterialDiscoveryFinalizationCommand.model_validate(command_data())
    assert command.operation == "RECOVER_NATIVE_MATERIAL_DISCOVERY_FINALIZATION"
    assert (
        RecoverNativeMaterialDiscoveryFinalizationCommand.model_validate_json(
            command.model_dump_json()
        )
        == command
    )
    validate_contract(COMMAND_SCHEMA, command.model_dump(mode="json"))
    with pytest.raises(ValueError):
        command.target_source_commit = "a" * 40


@pytest.mark.parametrize(
    "changes",
    [
        {"actor_id": "ADMIN"},
        {"run_id": "materialrun_latest"},
        {"target_source_commit": "A" * 40},
        {"target_source_commit": "main"},
        {"expected_prepared_sha256": "sha256:" + "x" * 64},
        {"expected_updated_at": "2026-11-14T09:00:00+09:00"},
        {"prepared": {}},
        {"service_drained": True},
        {"retry_model": True},
        {"path": "/tmp/untrusted"},
    ],
)
def test_command_rejects_bad_pins_and_claimed_runtime_authority(changes):
    with pytest.raises(ValueError):
        RecoverNativeMaterialDiscoveryFinalizationCommand.model_validate(command_data() | changes)


def test_result_has_exact_native_prepared_pointer_and_no_model_retry_count():
    result = NativeMaterialDiscoveryFinalizationRecoveryResult.model_validate(result_data())
    value = result.model_dump(mode="json")
    validate_contract(RESULT_SCHEMA, value)
    assert "retried_tasks" not in value
    assert result.prepared.sha256 == command_data()["expected_prepared_sha256"]
    assert (
        NativeMaterialDiscoveryFinalizationRecoveryResult.model_validate_json(
            result.model_dump_json()
        )
        == result
    )
    replay = NativeMaterialDiscoveryFinalizationRecoveryResult.model_validate(
        result_data() | {"replayed": True, "state": "PROCESSING"}
    )
    assert replay.run_id == result.run_id and replay.prepared == result.prepared


@pytest.mark.parametrize(
    "changes",
    [
        {"predecessor_run_id": "materialrun_" + "5" * 32},
        {"source_commit": "latest"},
        {"reused_tasks": 0},
        {"reused_tasks": True},
        {"retried_tasks": 0},
    ],
)
def test_result_rejects_false_successor_and_bad_reuse_count(changes):
    with pytest.raises(ValueError):
        NativeMaterialDiscoveryFinalizationRecoveryResult.model_validate(result_data() | changes)


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_ref", "eom://schemas/material-learning/prepared/1.0"),
        ("member_path", "material/intake.json"),
        ("media_type", "application/octet-stream"),
    ],
)
def test_model_and_schema_both_reject_non_native_or_wrong_member(field, value):
    data = result_data()
    data["prepared"][field] = value
    with pytest.raises(ValueError, match="PREPARED_POINTER_INVALID"):
        NativeMaterialDiscoveryFinalizationRecoveryResult.model_validate(data)
    with pytest.raises(JsonSchemaError):
        validate_contract(
            RESULT_SCHEMA,
            data | {"schema_version": "material-native-discovery-finalization-recovery-result/1.0"},
        )


def test_resource_mirrors_and_registry_hashes_are_exact():
    import hashlib

    for key in (COMMAND_SCHEMA, RESULT_SCHEMA):
        resource = CATALOG_SCHEMA_RESOURCES[key]
        canonical = (ROOT / resource.canonical_path).read_bytes()
        mirror = (
            ROOT / "packages/catalog_contracts/eom_catalog_contracts" / resource.resource_path
        ).read_bytes()
        assert canonical == mirror
        assert resource.sha256 == "sha256:" + hashlib.sha256(canonical).hexdigest()


def test_existing_retry_still_requires_at_least_one_failed_task():
    data = result_data()
    retry = dict(
        predecessor_run_id=data["predecessor_run_id"],
        run_id=data["run_id"],
        state="DISCOVERING",
        reused_tasks=7,
        retried_tasks=0,
        replayed=False,
    )
    with pytest.raises(ValueError):
        MaterialLearningRetryResult.model_validate(retry)
    before = deepcopy(retry)
    with pytest.raises(JsonSchemaError):
        validate_contract(
            "material-learning-retry-result-v1",
            retry | {"schema_version": "material-learning-retry-result/1.0"},
        )
    assert retry == before
