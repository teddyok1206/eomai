from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.legacy_item_extraction_bootstrap import (
    LegacyItemExtractionBootstrapManifest,
    _require_exact_six_slot_registry,
    load_legacy_item_extraction_bootstrap_manifest,
)
from eom_orchestrator.worker_registry import WorkerSlot
from eom_workflow.control_schemas import validate_control_contract
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config/control-plane/legacy-item-extraction-v1"


def test_legacy_item_extraction_bootstrap_is_schema_first_and_exact() -> None:
    manifest = load_legacy_item_extraction_bootstrap_manifest(CONFIG)
    document = manifest.model_dump(mode="json")

    validate_control_contract("legacy-item-extraction-control-bootstrap", document)
    assert manifest.preset_key == "legacy-item-extraction"
    assert manifest.model == "gpt-5.6-terra"
    assert manifest.reasoning_effort == "xhigh"
    assert manifest.general_knowledge_policy == "DENY"
    assert manifest.compatible_workflow_protocols == ("workflow-role/1.14.0",)
    assert manifest.slot_key == "slot06"
    assert manifest.worker_pool_key == "legacy-extraction"
    assert manifest.timeout_seconds == 7200
    assert hashlib.sha256((CONFIG / "bootstrap.yaml").read_bytes()).hexdigest() == (
        "4d63661cc051c3eec1a8f56a7deaefa8350d993922e571f38db37d090826d4b6"
    )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("model", "gpt-5.6-sol"),
        ("reasoning_effort", "high"),
        ("general_knowledge_policy", "ALLOW_WITH_PROVENANCE"),
        ("compatible_workflow_protocols", ["workflow-role/1.11.0"]),
        ("slot_key", "slot05"),
        ("worker_pool_key", "support"),
        ("timeout_seconds", 3600),
    ),
)
def test_legacy_item_extraction_bootstrap_rejects_execution_drift(
    field: str, value: object
) -> None:
    document = load_legacy_item_extraction_bootstrap_manifest(CONFIG).model_dump(mode="json")
    document[field] = value

    with pytest.raises((JsonSchemaValidationError, ValidationError)):
        validate_control_contract("legacy-item-extraction-control-bootstrap", document)
        LegacyItemExtractionBootstrapManifest.model_validate(document)


def test_legacy_item_extraction_bootstrap_rejects_symlinked_root(tmp_path: Path) -> None:
    copied = tmp_path / "copied"
    shutil.copytree(CONFIG, copied)
    linked = tmp_path / "linked"
    linked.symlink_to(copied, target_is_directory=True)

    with pytest.raises(ControlPlaneError) as captured:
        load_legacy_item_extraction_bootstrap_manifest(linked)
    assert captured.value.code == "CONTROL_BOOTSTRAP_INVALID"


def test_legacy_item_extraction_requires_slot06_without_broadening_slot05() -> None:
    slots = tuple(
        WorkerSlot(
            slot_id=f"{ordinal:02d}",
            linux_user=f"eom-cdx-{ordinal:02d}",
            role=role,
            enabled=True,
            gpu=role == "image",
        )
        for ordinal, role in (
            (1, "authoring"),
            (2, "review"),
            (3, "image"),
            (4, "item_management"),
            (5, "support"),
            (6, "support"),
        )
    )
    _require_exact_six_slot_registry(slots)

    drifted = (*slots[:5], slots[5].model_copy(update={"enabled": False}))
    with pytest.raises(ControlPlaneError) as captured:
        _require_exact_six_slot_registry(drifted)
    assert captured.value.code == "CONTROL_BOOTSTRAP_SLOT_MISMATCH"


def test_legacy_item_extraction_bootstrap_cli_is_explicit_and_secret_free() -> None:
    source = (ROOT / "apps/eomctl/eomctl/control_plane.py").read_text(encoding="utf-8")
    config_text = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(CONFIG.rglob("*")) if path.is_file()
    ).casefold()

    assert '@control_plane_app.command("bootstrap-legacy-item-extraction")' in source
    assert all(
        forbidden not in config_text
        for forbidden in ("auth.json", "bearer ", "password=", "token=", "api_key")
    )
