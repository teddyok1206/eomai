"""Installed material owner pins/error redaction; no DB/model/authentication calls."""

from datetime import UTC, datetime

import pytest
from eom_catalog_service.material_learning_runner import stable_material_error_code
from eom_catalog_service.material_learning_runtime import MaterialLearningRuntimePins
from eom_orchestrator.material_learning_controls import material_learning_capacity_document
from eom_workflow.control_plane import WorkerCapacityPolicyV7


def pins():
    return dict(
        learning_preset_revision_id="execpresetrev_" + "1" * 32,
        item_preset_revision_id="execpresetrev_" + "2" * 32,
        solution_preset_revision_id="execpresetrev_" + "3" * 32,
        document_preset_revision_id="execpresetrev_" + "4" * 32,
        risk_policy_revision_id="analysisriskrev_" + "5" * 32,
        access_policy_revision_id="accessrev_" + "6" * 32,
        content_pack_release_id="packrel_" + "7" * 32,
        definition_id="wfdef_" + "8" * 32,
    )


def test_runtime_reads_only_explicit_small_release_pins(monkeypatch):
    for key, value in pins().items():
        monkeypatch.setenv("EOM_MATERIAL_" + key.upper(), value)
    assert MaterialLearningRuntimePins.from_environment().model_dump() == {
        **pins(),
        "native_content_pack_release_id": None,
    }
    monkeypatch.delenv("EOM_MATERIAL_ITEM_PRESET_REVISION_ID")
    with pytest.raises(ValueError):
        MaterialLearningRuntimePins.from_environment()


def test_material_capacity_is_shared_four_not_an_extra_slot():
    value = WorkerCapacityPolicyV7.model_validate(
        material_learning_capacity_document(created_at=datetime(2026, 11, 6, tzinfo=UTC))
    )
    assert value.purpose == "UPLOADED_MATERIAL_LEARNING"
    assert value.max_active_codex == value.max_active_knowledge_analysis == 4
    assert value.max_active_per_slot == 1


@pytest.mark.parametrize(
    "error,expected",
    [
        (ValueError("MATERIAL_LEARNING_SOURCE_STALE"), "MATERIAL_LEARNING_SOURCE_STALE"),
        (RuntimeError("password=not-to-be-logged"), "MATERIAL_LEARNING_PROCESSING_FAILED"),
        (ValueError("/private/source/path"), "MATERIAL_LEARNING_PROCESSING_FAILED"),
    ],
)
def test_process_errors_are_codes_not_source_bytes_or_paths(error, expected):
    assert stable_material_error_code(error) == expected
