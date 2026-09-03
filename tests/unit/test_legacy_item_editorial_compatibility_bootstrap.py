from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from eom_orchestrator.control_service import ControlPlaneError, compute_control_document_hash
from eom_orchestrator.legacy_item_editorial_compatibility_bootstrap import (
    EDITORIAL_COMPATIBILITY_PLATFORM_ARTIFACT_KEY,
    EDITORIAL_COMPATIBILITY_ROLE_ARTIFACT_KEY,
    _build_non_live_evaluation_report,
    _require_exact_six_slot_registry,
    load_legacy_item_editorial_compatibility_bootstrap_manifest,
)
from eom_orchestrator.worker_registry import WorkerSlot
from eom_workflow import ExecutionPresetEvaluationReport
from eom_workflow.control_schemas import validate_control_contract

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config/control-plane/legacy-item-editorial-compatibility-v1"


def test_editorial_compatibility_bootstrap_is_schema_first_and_source_only() -> None:
    manifest = load_legacy_item_editorial_compatibility_bootstrap_manifest(CONFIG)

    validate_control_contract(
        "legacy-item-editorial-compatibility-control-bootstrap",
        manifest.model_dump(mode="json"),
    )
    assert manifest.preset_key == "legacy-item-editorial-compatibility"
    assert manifest.compatible_workflow_protocols == ("workflow-role/1.16.0",)
    assert manifest.slot_key == "slot05"
    assert manifest.worker_pool_key == "support"
    assert manifest.model == "gpt-5.6-terra"
    assert manifest.reasoning_effort == "high"
    assert manifest.general_knowledge_policy == "DENY"
    assert manifest.timeout_seconds == 3600
    role = (CONFIG / manifest.role_instruction_path).read_text(encoding="utf-8")
    assert "Read both authority documents in full" in role
    assert "do not invent, add, or silently import EOM editorial" in " ".join(role.split())
    for artifact_key in (
        EDITORIAL_COMPATIBILITY_PLATFORM_ARTIFACT_KEY,
        EDITORIAL_COMPATIBILITY_ROLE_ARTIFACT_KEY,
    ):
        assert len(f"control-bootstrap:{artifact_key}:{'a' * 64}") <= 128


def test_editorial_compatibility_evaluation_uses_existing_non_live_contract() -> None:
    document = _build_non_live_evaluation_report(
        preset_revision_id="execpresetrev_" + "a" * 32,
        policy_sha256="sha256:" + "b" * 64,
        evaluation_cases_total=65,
        completed_at=datetime(2026, 9, 3, 0, 1, tzinfo=UTC),
    )

    validate_control_contract("execution-preset-evaluation-report", document)
    report = ExecutionPresetEvaluationReport.model_validate(document)
    assert report.scope == "NON_LIVE"
    assert report.cases_total == report.cases_passed == 65
    assert report.report_sha256 == compute_control_document_hash(document, "report_sha256")


def test_editorial_compatibility_requires_exact_six_slot_registry() -> None:
    roles = ("authoring", "review", "image", "item_management", "support", "support")
    slots = tuple(
        WorkerSlot.model_validate(
            {
                "slot_id": f"{index:02d}",
                "linux_user": f"eom-cdx-{index:02d}",
                "role": roles[index - 1],
                "enabled": True,
                "gpu": index == 3,
            }
        )
        for index in range(1, 7)
    )
    _require_exact_six_slot_registry(slots)

    with pytest.raises(ControlPlaneError, match="exact six-slot inventory"):
        _require_exact_six_slot_registry(slots[:-1])
