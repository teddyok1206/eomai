from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from eom_orchestrator.control_bootstrap import (
    EXPECTED_ROLE_SLOTS,
    KnowledgeAnalysisBootstrapManifest,
    StandardBootstrapManifest,
    load_knowledge_analysis_bootstrap_manifest,
    load_standard_bootstrap_manifest,
)
from eom_orchestrator.control_service import ControlPlaneError
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config/control-plane/standard-item-v1"
ANALYSIS_CONFIG = ROOT / "config/control-plane/knowledge-analysis-v1"
ANALYSIS_CONFIG_V2 = ROOT / "config/control-plane/knowledge-analysis-v2"
ANALYSIS_CONFIG_V3 = ROOT / "config/control-plane/knowledge-analysis-v3"


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
    assert "KNOWLEDGE_ANALYSIS_CONFIG_DIRECTORY_OPTION = typer.Option(\n    ...," in source
    assert "/home/eom/EOM" not in source


def test_knowledge_analysis_bootstrap_is_support_only_and_credential_free() -> None:
    manifest = load_knowledge_analysis_bootstrap_manifest(ANALYSIS_CONFIG)
    assert manifest.preset_key == "knowledge-analysis"
    assert manifest.slot_key == "slot05"
    assert manifest.worker_pool_key == "support"
    assert manifest.compatible_workflow_protocols == ("workflow-role/1.4.0",)
    assert manifest.general_knowledge_policy == "ALLOW_WITH_PROVENANCE"
    assert manifest.model == "gpt-5.6-terra"
    assert manifest.reasoning_effort == "high"
    tracked = tuple(path for path in ANALYSIS_CONFIG.rglob("*") if path.is_file())
    assert tracked and all(path.is_file() and not path.is_symlink() for path in tracked)
    source = "\n".join(path.read_text(encoding="utf-8") for path in tracked).casefold()
    assert all(
        forbidden not in source
        for forbidden in ("auth.json", "bearer ", "password=", "token=", "api_key")
    )

    invalid = manifest.model_dump(mode="json")
    invalid["slot_key"] = "slot04"
    with pytest.raises(ValidationError):
        KnowledgeAnalysisBootstrapManifest.model_validate(invalid)


def test_knowledge_analysis_v3_adds_ontology_guidance_without_mutating_history() -> None:
    expected_sha256 = dict(
        (
            (
                "knowledge-analysis-v1/bootstrap.yaml",
                "9b46cb103ad1c036635d3aa51fb16e60c99023cf984620a3c04204e261635c81",
            ),
            (
                "knowledge-analysis-v1/instructions/platform.md",
                "43d44eaa7ff40594490da50e03c4dbec885593963b704d9751ba9bf89a789d9e",
            ),
            (
                "knowledge-analysis-v1/instructions/knowledge-analysis.md",
                "efaf1402ceb6b2858aa0de841ab14ac69c71dde1b7f2352148b8cf66c99067d8",
            ),
            (
                "knowledge-analysis-v2/bootstrap.yaml",
                "17fc3e5c1deb9942004d2416f638e4fa13202ee3d92c5a24ee7f923bd2c9efcd",
            ),
            (
                "knowledge-analysis-v2/instructions/platform.md",
                "43d44eaa7ff40594490da50e03c4dbec885593963b704d9751ba9bf89a789d9e",
            ),
            (
                "knowledge-analysis-v2/instructions/knowledge-analysis.md",
                "fae98c13b3e5bf2d5072c485f96ad94a228709a45c51ef0bd853d9081a2a2c77",
            ),
        ),
    )
    for relative_path, expected in expected_sha256.items():
        assert (
            hashlib.sha256((ROOT / "config/control-plane" / relative_path).read_bytes()).hexdigest()
            == expected
        )

    manifest = load_knowledge_analysis_bootstrap_manifest(ANALYSIS_CONFIG_V3)
    assert manifest.schema_version == "knowledge-analysis-control-bootstrap/3.0"
    assert manifest.compatible_workflow_protocols == (
        "workflow-role/1.4.0",
        "workflow-role/1.5.0",
    )
    instruction = (ANALYSIS_CONFIG_V3 / manifest.role_instruction_path).read_text(encoding="utf-8")
    assert "CONTAINS_CURRICULUM_UNIT" in instruction
    assert "PART_OF" in instruction
    assert "REQUIRES_CONCEPT" in instruction
    assert "REQUIRES_PREREQUISITE" in instruction
    assert load_knowledge_analysis_bootstrap_manifest(ANALYSIS_CONFIG_V2).schema_version == (
        "knowledge-analysis-control-bootstrap/2.0"
    )


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
