from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.knowledge_item_bootstrap import (
    KnowledgeItemBootstrapManifest,
    load_knowledge_item_bootstrap_manifest,
)
from eom_workflow.control_schemas import validate_control_contract
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config/control-plane/knowledge-grounded-item-v1"


def test_knowledge_item_bootstrap_is_schema_first_and_exact() -> None:
    manifest = load_knowledge_item_bootstrap_manifest(CONFIG)
    value = manifest.model_dump(mode="json")

    validate_control_contract("knowledge-item-control-bootstrap", value)
    assert manifest.preset_key == "knowledge-grounded-item"
    assert manifest.base_preset_key == "standard-item"
    assert manifest.compatible_workflow_protocols == ("workflow-role/1.12.0",)
    assert manifest.evidence_access_by_role == {
        "authoring": "EVIDENCE_CONTEXT",
        "image": "EVIDENCE_CONTEXT",
        "review": "EVIDENCE_CONTEXT",
        "item_management": "NONE",
    }
    assert manifest.retrieval_policy.allowed_corpus_keys == ("integrated-science-textbooks",)
    assert manifest.retrieval_policy.allowed_query_kinds == ("ITEM_PREPARATION",)
    assert manifest.retrieval_policy.allowed_source_classes == (
        "APPROVED_ITEM",
        "TEXTBOOK",
    )
    assert hashlib.sha256((CONFIG / "bootstrap.yaml").read_bytes()).hexdigest() == (
        "70e9a8d580cfea28499be6cd3a8aa2f6b2777fabfaa2076a481aa8cf608a90cd"
    )


@pytest.mark.parametrize(
    ("path", "value"),
    (
        (("retrieval_policy", "allowed_corpus_keys"), ["science-core"]),
        (("retrieval_policy", "allowed_query_kinds"), ["CURRICULUM_COMPONENTS"]),
        (("retrieval_policy", "allowed_source_classes"), ["TEXTBOOK", "APPROVED_ITEM"]),
        (("evidence_access_by_role", "item_management"), "EVIDENCE_CONTEXT"),
        (("compatible_workflow_protocols",), ["workflow-role/1.3.0"]),
    ),
)
def test_knowledge_item_bootstrap_rejects_scope_or_role_drift(
    path: tuple[str, ...], value: object
) -> None:
    document = load_knowledge_item_bootstrap_manifest(CONFIG).model_dump(mode="json")
    target: dict[str, object] = document
    for part in path[:-1]:
        nested = target[part]
        assert isinstance(nested, dict)
        target = nested
    target[path[-1]] = value

    with pytest.raises((JsonSchemaValidationError, ValidationError)):
        validate_control_contract("knowledge-item-control-bootstrap", document)
        KnowledgeItemBootstrapManifest.model_validate(document)


def test_knowledge_item_bootstrap_rejects_symlinked_root(tmp_path: Path) -> None:
    copied = tmp_path / "copied"
    shutil.copytree(CONFIG, copied)
    linked = tmp_path / "linked"
    linked.symlink_to(copied, target_is_directory=True)

    with pytest.raises(ControlPlaneError) as captured:
        load_knowledge_item_bootstrap_manifest(linked)
    assert captured.value.code == "CONTROL_BOOTSTRAP_INVALID"


def test_knowledge_item_bootstrap_cli_is_explicit_and_credential_free() -> None:
    source = (ROOT / "apps/eomctl/eomctl/control_plane.py").read_text(encoding="utf-8")
    config_source = (CONFIG / "bootstrap.yaml").read_text(encoding="utf-8").casefold()

    assert '@control_plane_app.command("bootstrap-knowledge-item")' in source
    assert "KNOWLEDGE_ITEM_CONFIG_DIRECTORY_OPTION = typer.Option(\n    ...," in source
    assert all(
        forbidden not in config_source
        for forbidden in ("auth.json", "bearer ", "password=", "token=", "api_key")
    )
