from __future__ import annotations

from pathlib import Path

import pytest
from eom_orchestrator.control_bootstrap import (
    EXPECTED_ROLE_SLOTS,
    StandardBootstrapManifest,
    load_standard_bootstrap_manifest,
)
from eom_orchestrator.control_service import ControlPlaneError
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config/control-plane/standard-item-v1"


def test_standard_bootstrap_manifest_is_bounded_and_credential_free() -> None:
    manifest = load_standard_bootstrap_manifest(CONFIG)
    assert manifest.preset_key == "standard-item"
    assert {role.role: role.slot_key for role in manifest.roles} == EXPECTED_ROLE_SLOTS
    assert manifest.support_slot_key == "slot05"
    assert manifest.general_knowledge_policy == "ALLOW_WITH_PROVENANCE"
    assert manifest.model == "gpt-5.6-terra"
    assert manifest.reasoning_effort == "high"
    tracked = tuple(path for path in CONFIG.rglob("*") if path.is_file())
    assert all(path.is_file() and not path.is_symlink() for path in tracked)
    source = "\n".join(path.read_text(encoding="utf-8") for path in tracked).casefold()
    assert all(
        forbidden not in source
        for forbidden in ("auth.json", "bearer ", "password=", "token=", "api_key")
    )


def test_bootstrap_cli_requires_an_explicit_reviewed_source_directory() -> None:
    source = (ROOT / "apps/eomctl/eomctl/control_plane.py").read_text(encoding="utf-8")

    assert "STANDARD_CONFIG_DIRECTORY_OPTION = typer.Option(\n    ...," in source
    assert "/home/eom/EOM" not in source


def test_standard_bootstrap_rejects_role_slot_drift_and_symlink_root(tmp_path: Path) -> None:
    value = load_standard_bootstrap_manifest(CONFIG).model_dump(mode="json")
    value["roles"][0]["slot_key"] = "slot02"
    with pytest.raises(ValidationError, match="fixed identities"):
        StandardBootstrapManifest.model_validate(value)

    linked = tmp_path / "linked"
    linked.symlink_to(CONFIG, target_is_directory=True)
    with pytest.raises(ControlPlaneError) as captured:
        load_standard_bootstrap_manifest(linked)
    assert captured.value.code == "CONTROL_BOOTSTRAP_INVALID"
