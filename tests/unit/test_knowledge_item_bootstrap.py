from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from types import SimpleNamespace

import eom_orchestrator.control_bootstrap as control_bootstrap
import eom_orchestrator.knowledge_item_bootstrap as knowledge_item_bootstrap
import pytest
from eom_orchestrator.control_bootstrap import load_standard_bootstrap_manifest
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.knowledge_item_bootstrap import (
    EXPECTED_V7_BASE_INSTRUCTION_BUNDLE_REVISION_IDS,
    EXPECTED_V7_BASE_INSTRUCTION_MEMBER_SHA256S,
    EXPECTED_V8_BASE_INSTRUCTION_BUNDLE_IDS,
    EXPECTED_V8_BASE_INSTRUCTION_BUNDLE_REVISION_IDS,
    EXPECTED_V8_BASE_INSTRUCTION_MEMBER_SHA256S,
    EXPECTED_V9_BASE_INSTRUCTION_BUNDLE_IDS,
    EXPECTED_V9_BASE_INSTRUCTION_BUNDLE_REVISION_IDS,
    EXPECTED_V9_BASE_INSTRUCTION_MEMBER_SHA256S,
    EXPECTED_V10_BASE_INSTRUCTION_BUNDLE_IDS,
    EXPECTED_V10_BASE_INSTRUCTION_BUNDLE_REVISION_IDS,
    EXPECTED_V10_BASE_INSTRUCTION_MEMBER_SHA256S,
    KnowledgeItemBootstrapManifest,
    load_knowledge_item_bootstrap_manifest,
)
from eom_workflow.control_schemas import validate_control_contract
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config/control-plane/knowledge-grounded-item-v1"
CONFIG_V2 = ROOT / "config/control-plane/knowledge-grounded-item-v2"
CONFIG_V3 = ROOT / "config/control-plane/knowledge-grounded-item-v3"
CONFIG_V4 = ROOT / "config/control-plane/knowledge-grounded-item-v4"
CONFIG_V5 = ROOT / "config/control-plane/knowledge-grounded-item-v5"
CONFIG_V6 = ROOT / "config/control-plane/knowledge-grounded-item-v6"
CONFIG_V7 = ROOT / "config/control-plane/knowledge-grounded-item-v7"
CONFIG_V8 = ROOT / "config/control-plane/knowledge-grounded-item-v8"
CONFIG_V9 = ROOT / "config/control-plane/knowledge-grounded-item-v9"
CONFIG_V10 = ROOT / "config/control-plane/knowledge-grounded-item-v10"
STANDARD_CONFIG_V9 = ROOT / "config/control-plane/standard-item-v9"
STANDARD_CONFIG_V10 = ROOT / "config/control-plane/standard-item-v10"
STANDARD_CONFIG_V11 = ROOT / "config/control-plane/standard-item-v11"
STANDARD_CONFIG_V12 = ROOT / "config/control-plane/standard-item-v12"
STANDARD_CONFIG_V13 = ROOT / "config/control-plane/standard-item-v13"


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


def test_knowledge_item_v2_bootstrap_pins_current_authoring_protocol() -> None:
    manifest = load_knowledge_item_bootstrap_manifest(CONFIG_V2)
    value = manifest.model_dump(mode="json")

    validate_control_contract("knowledge-item-control-bootstrap-v2", value)
    assert manifest.schema_version == "knowledge-item-control-bootstrap/2.0"
    assert manifest.compatible_workflow_protocols == ("workflow-role/1.15.0",)
    assert manifest.evidence_access_by_role == {
        "authoring": "EVIDENCE_CONTEXT",
        "image": "EVIDENCE_CONTEXT",
        "review": "EVIDENCE_CONTEXT",
        "item_management": "NONE",
    }
    assert manifest.retrieval_policy.allowed_corpus_keys == ("integrated-science-textbooks",)


def test_knowledge_item_v3_bootstrap_pins_conditional_image_protocol() -> None:
    manifest = load_knowledge_item_bootstrap_manifest(CONFIG_V3)
    value = manifest.model_dump(mode="json")

    validate_control_contract("knowledge-item-control-bootstrap-v3", value)
    assert manifest.schema_version == "knowledge-item-control-bootstrap/3.0"
    assert manifest.compatible_workflow_protocols == ("workflow-role/1.17.0",)
    assert manifest.evidence_access_by_role["image"] == "EVIDENCE_CONTEXT"
    assert manifest.retrieval_policy.allowed_corpus_keys == ("integrated-science-textbooks",)


def test_knowledge_item_v4_bootstrap_routes_past_exam_graph_evidence_to_one_shot() -> None:
    manifest = load_knowledge_item_bootstrap_manifest(CONFIG_V4)
    value = manifest.model_dump(mode="json")

    validate_control_contract("knowledge-item-control-bootstrap-v4", value)
    assert manifest.schema_version == "knowledge-item-control-bootstrap/4.0"
    assert manifest.compatible_workflow_protocols == ("workflow-role/1.17.0",)
    assert manifest.evidence_access_by_role["authoring"] == "EVIDENCE_CONTEXT"
    assert manifest.retrieval_policy.allowed_source_classes == (
        "APPROVED_ITEM",
        "PAST_EXAM",
        "TEXTBOOK",
    )


def test_knowledge_item_v5_bootstrap_pins_content_team_v3_protocol() -> None:
    manifest = load_knowledge_item_bootstrap_manifest(CONFIG_V5)
    value = manifest.model_dump(mode="json")

    validate_control_contract("knowledge-item-control-bootstrap-v5", value)
    assert manifest.schema_version == "knowledge-item-control-bootstrap/5.0"
    assert manifest.compatible_workflow_protocols == ("workflow-role/1.19.0",)
    assert manifest.evidence_access_by_role == {
        "authoring": "EVIDENCE_CONTEXT",
        "image": "EVIDENCE_CONTEXT",
        "review": "EVIDENCE_CONTEXT",
        "item_management": "NONE",
    }
    assert manifest.retrieval_policy.allowed_source_classes == (
        "APPROVED_ITEM",
        "PAST_EXAM",
        "TEXTBOOK",
    )


def test_knowledge_item_v6_bootstrap_projects_exact_slot_standard_successor() -> None:
    standard = load_standard_bootstrap_manifest(STANDARD_CONFIG_V9)
    manifest = load_knowledge_item_bootstrap_manifest(CONFIG_V6)
    value = manifest.model_dump(mode="json")

    validate_control_contract("knowledge-item-control-bootstrap-v6", value)
    assert manifest.schema_version == "knowledge-item-control-bootstrap/6.0"
    assert manifest.compatible_workflow_protocols == ("workflow-role/1.19.0",)
    assert manifest.created_at.isoformat() == "2026-09-08T18:58:00+00:00"
    assert standard.created_at < manifest.created_at
    assert manifest.evidence_access_by_role == {
        "authoring": "EVIDENCE_CONTEXT",
        "image": "EVIDENCE_CONTEXT",
        "review": "EVIDENCE_CONTEXT",
        "item_management": "NONE",
    }
    assert manifest.retrieval_policy.allowed_source_classes == (
        "APPROVED_ITEM",
        "PAST_EXAM",
        "TEXTBOOK",
    )
    assert hashlib.sha256((CONFIG_V6 / "bootstrap.yaml").read_bytes()).hexdigest() == (
        "1e123bf26bf1527f75c26f32853ca98aa2b7630a23d48e9c65bd7f1fd1c0937a"
    )


def test_knowledge_item_v7_projects_renderer_safe_standard_successor() -> None:
    standard = load_standard_bootstrap_manifest(STANDARD_CONFIG_V10)
    manifest = load_knowledge_item_bootstrap_manifest(CONFIG_V7)
    value = manifest.model_dump(mode="json")

    validate_control_contract("knowledge-item-control-bootstrap-v7", value)
    assert manifest.schema_version == "knowledge-item-control-bootstrap/7.0"
    assert manifest.compatible_workflow_protocols == ("workflow-role/1.19.0",)
    assert manifest.created_at.isoformat() == "2026-09-08T21:33:00+00:00"
    assert standard.created_at < manifest.created_at
    assert manifest.evidence_access_by_role == {
        "authoring": "EVIDENCE_CONTEXT",
        "image": "EVIDENCE_CONTEXT",
        "review": "EVIDENCE_CONTEXT",
        "item_management": "NONE",
    }
    assert manifest.retrieval_policy.allowed_source_classes == (
        "APPROVED_ITEM",
        "PAST_EXAM",
        "TEXTBOOK",
    )
    assert manifest.base_instruction_bundle_revision_ids == dict(
        EXPECTED_V7_BASE_INSTRUCTION_BUNDLE_REVISION_IDS
    )
    assert manifest.base_instruction_member_sha256s == dict(
        EXPECTED_V7_BASE_INSTRUCTION_MEMBER_SHA256S
    )
    assert hashlib.sha256((CONFIG_V7 / "bootstrap.yaml").read_bytes()).hexdigest() == (
        "fea4c9e084bc048eea8796cd6e842d32c3651d783686c70f0f29ccbb65bbe572"
    )


def test_knowledge_item_v7_rejects_v9_current_and_accepts_exact_v10_base() -> None:
    manifest = load_knowledge_item_bootstrap_manifest(CONFIG_V7)
    v9_instruction_revisions = {
        "authoring": "instrrev_96518bbf860e8708ea7e65ce7d9b0862",
        "image": "instrrev_ae79989927d4d45169c5bf99a3610866",
        "review": "instrrev_7c6508313ffb8bbc666dfcdde2a52504",
        "item_management": "instrrev_b8182fd7783973d475d99fbc8991288d",
    }

    with pytest.raises(ControlPlaneError) as captured:
        knowledge_item_bootstrap._require_base_instruction_revisions(
            manifest, v9_instruction_revisions
        )
    assert captured.value.code == "CONTROL_BOOTSTRAP_BASE_PRESET_INVALID"

    knowledge_item_bootstrap._require_base_instruction_revisions(
        manifest, dict(EXPECTED_V7_BASE_INSTRUCTION_BUNDLE_REVISION_IDS)
    )


def test_knowledge_item_v7_instruction_component_hash_pin_fails_closed() -> None:
    manifest = load_knowledge_item_bootstrap_manifest(CONFIG_V7)
    expected = dict(EXPECTED_V7_BASE_INSTRUCTION_MEMBER_SHA256S)
    pointer = SimpleNamespace(
        bundle_id="instrbundle_" + "1" * 32,
        bundle_revision_id=EXPECTED_V7_BASE_INSTRUCTION_BUNDLE_REVISION_IDS["authoring"],
        manifest_artifact=SimpleNamespace(
            artifact_id="artifact_" + "2" * 32,
            artifact_revision_id="rev_" + "3" * 32,
            sha256="sha256:" + "4" * 64,
        ),
        manifest_sha256="sha256:" + "4" * 64,
    )
    document: dict[str, object] = {
        "bundle_id": pointer.bundle_id,
        "bundle_revision_id": pointer.bundle_revision_id,
        "revision_number": 10,
        "components": [
            {"layer": "PLATFORM", "artifact": {"sha256": expected["platform"]}},
            {"layer": "ROLE", "artifact": {"sha256": expected["authoring"]}},
        ],
        "content_sha256": "sha256:" + "0" * 64,
    }
    document["content_sha256"] = knowledge_item_bootstrap.compute_control_document_hash(
        document, "content_sha256"
    )

    def record(value: dict[str, object]) -> SimpleNamespace:
        return SimpleNamespace(
            bundle_id=pointer.bundle_id,
            bundle_revision_id=pointer.bundle_revision_id,
            bundle_kind="INSTRUCTION",
            revision_number=10,
            schema_version="instruction-bundle-manifest/1.0",
            state="RELEASED",
            manifest_artifact_id=pointer.manifest_artifact.artifact_id,
            manifest_artifact_revision_id=pointer.manifest_artifact.artifact_revision_id,
            manifest_sha256=pointer.manifest_sha256,
            content_sha256=value["content_sha256"],
            canonical_document=value,
        )

    base = SimpleNamespace(
        role_policies=(SimpleNamespace(role="authoring", instruction_bundle=pointer),)
    )
    accepted_session = SimpleNamespace(get=lambda *_args: record(document))
    knowledge_item_bootstrap._require_base_instruction_member_hashes(
        accepted_session, manifest=manifest, base=base
    )

    forged: dict[str, object] = {
        "bundle_id": pointer.bundle_id,
        "bundle_revision_id": pointer.bundle_revision_id,
        "revision_number": 10,
        "components": [
            {"layer": "PLATFORM", "artifact": {"sha256": expected["platform"]}},
            {"layer": "ROLE", "artifact": {"sha256": "sha256:" + "0" * 64}},
        ],
        "content_sha256": "sha256:" + "0" * 64,
    }
    forged["content_sha256"] = knowledge_item_bootstrap.compute_control_document_hash(
        forged, "content_sha256"
    )
    forged_session = SimpleNamespace(get=lambda *_args: record(forged))
    with pytest.raises(ControlPlaneError) as captured:
        knowledge_item_bootstrap._require_base_instruction_member_hashes(
            forged_session, manifest=manifest, base=base
        )
    assert captured.value.code == "CONTROL_BOOTSTRAP_BASE_PRESET_INVALID"


def test_knowledge_item_v8_projects_exact_occurrence_authority_successor() -> None:
    standard = load_standard_bootstrap_manifest(STANDARD_CONFIG_V11)
    manifest = load_knowledge_item_bootstrap_manifest(CONFIG_V8)
    value = manifest.model_dump(mode="json")

    validate_control_contract("knowledge-item-control-bootstrap-v8", value)
    assert manifest.schema_version == "knowledge-item-control-bootstrap/8.0"
    assert manifest.compatible_workflow_protocols == ("workflow-role/1.19.0",)
    assert manifest.created_at.isoformat() == "2026-09-09T00:28:00+00:00"
    assert standard.created_at < manifest.created_at
    assert manifest.evidence_access_by_role == {
        "authoring": "EVIDENCE_CONTEXT",
        "image": "EVIDENCE_CONTEXT",
        "review": "EVIDENCE_CONTEXT",
        "item_management": "NONE",
    }
    assert manifest.retrieval_policy.allowed_source_classes == (
        "APPROVED_ITEM",
        "PAST_EXAM",
        "TEXTBOOK",
    )
    assert manifest.base_instruction_bundle_ids == dict(EXPECTED_V8_BASE_INSTRUCTION_BUNDLE_IDS)
    assert manifest.base_instruction_bundle_ids == {
        role: control_bootstrap._stable_id("instrbundle_", f"standard-item:{role}")
        for role in ("authoring", "image", "review", "item_management")
    }
    assert manifest.base_instruction_bundle_revision_ids == dict(
        EXPECTED_V8_BASE_INSTRUCTION_BUNDLE_REVISION_IDS
    )
    assert manifest.base_instruction_bundle_revision_ids == {
        role: control_bootstrap._stable_id("instrrev_", f"standard-item:{role}:v11")
        for role in ("authoring", "image", "review", "item_management")
    }
    assert manifest.base_instruction_member_sha256s == dict(
        EXPECTED_V8_BASE_INSTRUCTION_MEMBER_SHA256S
    )
    assert hashlib.sha256((CONFIG_V8 / "bootstrap.yaml").read_bytes()).hexdigest() == (
        "a3fc521d48bd9004c40be01735b0943230d9e502801f85b3219b824582d569c4"
    )
    assert hashlib.sha256((CONFIG_V7 / "bootstrap.yaml").read_bytes()).hexdigest() == (
        "fea4c9e084bc048eea8796cd6e842d32c3651d783686c70f0f29ccbb65bbe572"
    )


def test_knowledge_item_v9_projects_exact_evidence_usage_standard_successor() -> None:
    standard = load_standard_bootstrap_manifest(STANDARD_CONFIG_V12)
    manifest = load_knowledge_item_bootstrap_manifest(CONFIG_V9)
    value = manifest.model_dump(mode="json")

    validate_control_contract("knowledge-item-control-bootstrap-v9", value)
    assert manifest.schema_version == "knowledge-item-control-bootstrap/9.0"
    assert manifest.compatible_workflow_protocols == ("workflow-role/1.20.0",)
    assert manifest.created_at.isoformat() == "2026-09-10T01:05:00+00:00"
    assert standard.created_at < manifest.created_at
    assert manifest.evidence_access_by_role == {
        "authoring": "EVIDENCE_CONTEXT",
        "image": "EVIDENCE_CONTEXT",
        "review": "EVIDENCE_CONTEXT",
        "item_management": "NONE",
    }
    assert manifest.retrieval_policy.allowed_source_classes == (
        "APPROVED_ITEM",
        "PAST_EXAM",
        "TEXTBOOK",
    )
    assert manifest.base_instruction_bundle_ids == dict(EXPECTED_V9_BASE_INSTRUCTION_BUNDLE_IDS)
    assert manifest.base_instruction_bundle_revision_ids == dict(
        EXPECTED_V9_BASE_INSTRUCTION_BUNDLE_REVISION_IDS
    )
    assert manifest.base_instruction_bundle_revision_ids == {
        role: control_bootstrap._stable_id("instrrev_", f"standard-item:{role}:v12")
        for role in ("authoring", "image", "review", "item_management")
    }
    assert manifest.base_instruction_member_sha256s == dict(
        EXPECTED_V9_BASE_INSTRUCTION_MEMBER_SHA256S
    )
    assert hashlib.sha256((CONFIG_V9 / "bootstrap.yaml").read_bytes()).hexdigest() == (
        "5e1e9eadd79daadfaeba268aea813311b109703aab56b42842bc4d50dcdb4804"
    )


def test_knowledge_item_v10_pins_exact_two_prompt_standard_successor() -> None:
    standard = load_standard_bootstrap_manifest(STANDARD_CONFIG_V13)
    manifest = load_knowledge_item_bootstrap_manifest(CONFIG_V10)
    value = manifest.model_dump(mode="json")

    validate_control_contract("knowledge-item-control-bootstrap-v10", value)
    assert manifest.schema_version == "knowledge-item-control-bootstrap/10.0"
    assert manifest.compatible_workflow_protocols == ("workflow-role/1.20.0",)
    assert manifest.created_at.isoformat() == "2026-09-12T00:05:00+00:00"
    assert standard.created_at < manifest.created_at
    assert manifest.base_instruction_bundle_ids == dict(EXPECTED_V10_BASE_INSTRUCTION_BUNDLE_IDS)
    assert manifest.base_instruction_bundle_revision_ids == dict(
        EXPECTED_V10_BASE_INSTRUCTION_BUNDLE_REVISION_IDS
    )
    assert manifest.base_instruction_bundle_revision_ids == {
        role: control_bootstrap._stable_id("instrrev_", f"standard-item:{role}:v13")
        for role in ("authoring", "image", "review", "item_management")
    }
    assert manifest.base_instruction_member_sha256s == dict(
        EXPECTED_V10_BASE_INSTRUCTION_MEMBER_SHA256S
    )
    assert manifest.base_instruction_member_sha256s["image"] == (
        "sha256:4641d2fdeb7d78431d2b00190c117c6b27433e02f14c3750a89fbefbde0cdfb2"
    )
    assert hashlib.sha256((CONFIG_V10 / "bootstrap.yaml").read_bytes()).hexdigest() == (
        "14d2a192cd6f9c92d8e50ca8ca639e2c0346a25da9c0c03aff6398892b1cfe36"
    )


def test_knowledge_item_v8_rejects_v10_current_and_wrong_bundle_identity() -> None:
    manifest = load_knowledge_item_bootstrap_manifest(CONFIG_V8)

    with pytest.raises(ControlPlaneError) as revision_error:
        knowledge_item_bootstrap._require_base_instruction_revisions(
            manifest, dict(EXPECTED_V7_BASE_INSTRUCTION_BUNDLE_REVISION_IDS)
        )
    assert revision_error.value.code == "CONTROL_BOOTSTRAP_BASE_PRESET_INVALID"
    knowledge_item_bootstrap._require_base_instruction_revisions(
        manifest, dict(EXPECTED_V8_BASE_INSTRUCTION_BUNDLE_REVISION_IDS)
    )

    wrong_identities = dict(EXPECTED_V8_BASE_INSTRUCTION_BUNDLE_IDS)
    wrong_identities["review"] = "instrbundle_" + "0" * 32
    with pytest.raises(ControlPlaneError) as identity_error:
        knowledge_item_bootstrap._require_base_instruction_bundle_identities(
            manifest, wrong_identities
        )
    assert identity_error.value.code == "CONTROL_BOOTSTRAP_BASE_PRESET_INVALID"
    knowledge_item_bootstrap._require_base_instruction_bundle_identities(
        manifest, dict(EXPECTED_V8_BASE_INSTRUCTION_BUNDLE_IDS)
    )


def test_knowledge_item_v8_instruction_pointer_and_hash_pins_fail_closed() -> None:
    manifest = load_knowledge_item_bootstrap_manifest(CONFIG_V8)
    expected = dict(EXPECTED_V8_BASE_INSTRUCTION_MEMBER_SHA256S)
    pointer = SimpleNamespace(
        bundle_id=EXPECTED_V8_BASE_INSTRUCTION_BUNDLE_IDS["authoring"],
        bundle_revision_id=EXPECTED_V8_BASE_INSTRUCTION_BUNDLE_REVISION_IDS["authoring"],
        manifest_artifact=SimpleNamespace(
            artifact_id="artifact_" + "2" * 32,
            artifact_revision_id="rev_" + "3" * 32,
            sha256="sha256:" + "4" * 64,
        ),
        manifest_sha256="sha256:" + "4" * 64,
    )
    document: dict[str, object] = {
        "bundle_id": pointer.bundle_id,
        "bundle_revision_id": pointer.bundle_revision_id,
        "revision_number": 11,
        "components": [
            {"layer": "PLATFORM", "artifact": {"sha256": expected["platform"]}},
            {"layer": "ROLE", "artifact": {"sha256": expected["authoring"]}},
        ],
        "content_sha256": "sha256:" + "0" * 64,
    }
    document["content_sha256"] = knowledge_item_bootstrap.compute_control_document_hash(
        document, "content_sha256"
    )

    def record(value: dict[str, object], *, bundle_id: str = pointer.bundle_id) -> SimpleNamespace:
        return SimpleNamespace(
            bundle_id=bundle_id,
            bundle_revision_id=pointer.bundle_revision_id,
            bundle_kind="INSTRUCTION",
            revision_number=11,
            schema_version="instruction-bundle-manifest/1.0",
            state="RELEASED",
            manifest_artifact_id=pointer.manifest_artifact.artifact_id,
            manifest_artifact_revision_id=pointer.manifest_artifact.artifact_revision_id,
            manifest_sha256=pointer.manifest_sha256,
            content_sha256=value["content_sha256"],
            canonical_document=value,
        )

    base = SimpleNamespace(
        role_policies=(SimpleNamespace(role="authoring", instruction_bundle=pointer),)
    )
    accepted_session = SimpleNamespace(get=lambda *_args: record(document))
    knowledge_item_bootstrap._require_base_instruction_member_hashes(
        accepted_session, manifest=manifest, base=base
    )

    wrong_identity_session = SimpleNamespace(
        get=lambda *_args: record(document, bundle_id="instrbundle_" + "0" * 32)
    )
    with pytest.raises(ControlPlaneError) as identity_error:
        knowledge_item_bootstrap._require_base_instruction_member_hashes(
            wrong_identity_session, manifest=manifest, base=base
        )
    assert identity_error.value.code == "CONTROL_BOOTSTRAP_BASE_PRESET_INVALID"

    forged = {
        **document,
        "components": [
            {"layer": "PLATFORM", "artifact": {"sha256": expected["platform"]}},
            {"layer": "ROLE", "artifact": {"sha256": "sha256:" + "0" * 64}},
        ],
    }
    forged["content_sha256"] = knowledge_item_bootstrap.compute_control_document_hash(
        forged, "content_sha256"
    )
    forged_session = SimpleNamespace(get=lambda *_args: record(forged))
    with pytest.raises(ControlPlaneError) as hash_error:
        knowledge_item_bootstrap._require_base_instruction_member_hashes(
            forged_session, manifest=manifest, base=base
        )
    assert hash_error.value.code == "CONTROL_BOOTSTRAP_BASE_PRESET_INVALID"


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
