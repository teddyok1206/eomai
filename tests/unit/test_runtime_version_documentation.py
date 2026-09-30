from __future__ import annotations

import re
from pathlib import Path

import yaml
from eom_workflow.schemas import result_schema_protocol

ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "docs" / "architecture" / "ACTIVE_RUNTIME_VERSION_MATRIX.md"
README = ROOT / "README.md"
INSTALLER = ROOT / "scripts" / "workflow" / "install_runner_configuration.sh"


def _installed_definition_files() -> tuple[Path, ...]:
    installer = INSTALLER.read_text(encoding="utf-8")
    names = re.findall(r"config/workflows/([a-z0-9.-]+\.yaml)", installer)
    return tuple(ROOT / "config" / "workflows" / name for name in names)


def _semantic_version(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in value.split("."))


def _latest_compatible_generated_pack(definition_version: str) -> str:
    candidates: list[str] = []
    for pack_path in (ROOT / "content" / "packs" / "generated-knowledge-item").glob("*/pack.yaml"):
        document = yaml.safe_load(pack_path.read_text(encoding="utf-8"))
        for workflow in document["compatibility"]["workflow_definitions"]:
            if (
                workflow["key"] == "generic-item-development"
                and definition_version in workflow["versions"]
            ):
                candidates.append(document["pack"]["version"])
    assert candidates
    return max(candidates, key=_semantic_version)


def test_version_matrix_tracks_every_installed_workflow_selector() -> None:
    matrix = MATRIX.read_text(encoding="utf-8")
    paths = _installed_definition_files()

    assert paths
    for path in paths:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        identity = f"{document['definition_key']}@{document['definition_version']}"
        assert f"`{identity}`" in matrix
        protocols = {
            result_schema_protocol(step["result_schema"])
            for step in document["steps"]
            if step["type"] == "agent"
        }
        assert len(protocols) == 1
        assert f"`{protocols.pop()}`" in matrix


def test_readme_tracks_latest_single_item_selector_and_compatible_pack() -> None:
    readme = README.read_text(encoding="utf-8")
    generic_path = next(
        path
        for path in _installed_definition_files()
        if path.name.startswith("generic-item-development")
    )
    workflow = yaml.safe_load(generic_path.read_text(encoding="utf-8"))
    version = workflow["definition_version"]
    pack_version = _latest_compatible_generated_pack(version)

    assert f"`generic-item-development@{version}`" in readme
    assert f"`generated-knowledge-item@{pack_version}`" in readme
    assert "docs/architecture/ACTIVE_RUNTIME_VERSION_MATRIX.md" in readme


def test_version_matrix_separates_live_candidate_and_production_pin() -> None:
    matrix = MATRIX.read_text(encoding="utf-8")

    for state in (
        "Repository selector",
        "Admitted",
        "Live activated",
        "Repository candidate",
        "Historical replay",
        "Production pinned",
    ):
        assert state in matrix
    assert "source 1.2/role 1.27은 repository candidate" in matrix
    assert "`generic-item-development@1.10.0`" in matrix
    assert "`workflow-role/1.20.0`" in matrix
    assert "`generated-knowledge-item@1.16.1`" in matrix
    assert "가장 큰 값으로 자동 승격하지" in matrix
