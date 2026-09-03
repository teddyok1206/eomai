from __future__ import annotations

import hashlib
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import get_args

import eom_orchestrator.control_bootstrap as control_bootstrap
import pytest
from eom_orchestrator.control_bootstrap import (
    EXPECTED_ROLE_SLOTS,
    EXPECTED_STANDARD_V2_REFERENCE_KEYS,
    EXPECTED_STANDARD_V5_REFERENCE_KEYS,
    EXPECTED_STANDARD_V6_REFERENCE_KEYS,
    KNOWLEDGE_ANALYSIS_BOOTSTRAP_REVISIONS,
    STANDARD_BOOTSTRAP_INSTRUCTION_REVISIONS,
    STANDARD_BOOTSTRAP_REFERENCE_REVISIONS,
    STANDARD_COMPATIBLE_CURRENT_CAPACITY_REVISIONS,
    STANDARD_GUIDANCE_BUNDLE_CREATED_AT,
    KnowledgeAnalysisBootstrapManifest,
    StandardBootstrapManifest,
    bootstrap_standard_control_plane,
    load_knowledge_analysis_bootstrap_manifest,
    load_standard_bootstrap_manifest,
)
from eom_orchestrator.control_service import ControlPlaneError
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config/control-plane/standard-item-v1"
CONFIG_V2 = ROOT / "config/control-plane/standard-item-v2"
CONFIG_V3 = ROOT / "config/control-plane/standard-item-v3"
CONFIG_V4 = ROOT / "config/control-plane/standard-item-v4"
CONFIG_V5 = ROOT / "config/control-plane/standard-item-v5"
CONFIG_V6 = ROOT / "config/control-plane/standard-item-v6"
ANALYSIS_CONFIG = ROOT / "config/control-plane/knowledge-analysis-v1"
ANALYSIS_CONFIG_V2 = ROOT / "config/control-plane/knowledge-analysis-v2"
ANALYSIS_CONFIG_V3 = ROOT / "config/control-plane/knowledge-analysis-v3"
ANALYSIS_CONFIG_V4 = ROOT / "config/control-plane/knowledge-analysis-v4"
ANALYSIS_CONFIG_V5 = ROOT / "config/control-plane/knowledge-analysis-v5"
ANALYSIS_CONFIG_V6 = ROOT / "config/control-plane/knowledge-analysis-v6"
ANALYSIS_CONFIG_V7 = ROOT / "config/control-plane/knowledge-analysis-v7"
ANALYSIS_CONFIG_V8 = ROOT / "config/control-plane/knowledge-analysis-v8"
ANALYSIS_CONFIG_V9 = ROOT / "config/control-plane/knowledge-analysis-v9"
ANALYSIS_CONFIG_V10 = ROOT / "config/control-plane/knowledge-analysis-v10"
ANALYSIS_CONFIG_V11 = ROOT / "config/control-plane/knowledge-analysis-v11"
ANALYSIS_CONFIG_V12 = ROOT / "config/control-plane/knowledge-analysis-v12"
ANALYSIS_CONFIG_V13 = ROOT / "config/control-plane/knowledge-analysis-v13"
ANALYSIS_CONFIG_V14 = ROOT / "config/control-plane/knowledge-analysis-v14"


def test_knowledge_analysis_bootstrap_revision_map_covers_every_manifest_version() -> None:
    schema_versions = set(
        get_args(KnowledgeAnalysisBootstrapManifest.model_fields["schema_version"].annotation)
    )

    assert set(KNOWLEDGE_ANALYSIS_BOOTSTRAP_REVISIONS) == schema_versions
    assert tuple(KNOWLEDGE_ANALYSIS_BOOTSTRAP_REVISIONS.values()) == tuple(range(1, 15))


def test_knowledge_analysis_v13_adds_parallel_capacity_without_changing_worker_semantics() -> None:
    manifest = load_knowledge_analysis_bootstrap_manifest(ANALYSIS_CONFIG_V13)

    assert manifest.schema_version == "knowledge-analysis-control-bootstrap/13.0"
    assert manifest.slot_key == "slot05"
    assert manifest.worker_pool_key == "support"
    assert manifest.timeout_seconds == 7200
    assert manifest.compatible_workflow_protocols[-1] == "workflow-role/1.11.0"
    expected_sha256 = {
        "bootstrap.yaml": "6a1e15fe629e2cf90b46735e875ca58294b434293059eb2c6f78b6a4fdaaccc4",
        "instructions/platform.md": (
            "d89ba7eaffda1580178d215ad510e5401ed268473140cf3c3d53bb7195b9df91"
        ),
        "instructions/knowledge-analysis.md": (
            "93bf41b30a4520fbbcb0e21dc88be0a0a815f4ac96c9237d0d21758728b1b1ea"
        ),
    }
    for relative_path, expected in expected_sha256.items():
        assert hashlib.sha256((ANALYSIS_CONFIG_V13 / relative_path).read_bytes()).hexdigest() == (
            expected
        )
    assert (ANALYSIS_CONFIG_V13 / "instructions/platform.md").read_bytes() == (
        ANALYSIS_CONFIG_V12 / "instructions/platform.md"
    ).read_bytes()
    assert (ANALYSIS_CONFIG_V13 / "instructions/knowledge-analysis.md").read_bytes() == (
        ANALYSIS_CONFIG_V12 / "instructions/knowledge-analysis.md"
    ).read_bytes()


def test_knowledge_analysis_v14_requires_page_local_structured_evidence() -> None:
    manifest = load_knowledge_analysis_bootstrap_manifest(ANALYSIS_CONFIG_V14)

    assert manifest.schema_version == "knowledge-analysis-control-bootstrap/14.0"
    assert manifest.slot_key == "slot05"
    assert manifest.worker_pool_key == "support"
    assert manifest.model == "gpt-5.6-terra"
    assert manifest.reasoning_effort == "xhigh"
    assert manifest.timeout_seconds == 7200
    assert manifest.compatible_workflow_protocols[-1] == "workflow-role/1.11.0"
    expected_sha256 = {
        "bootstrap.yaml": "cbd813837bdeeae9dba12bb65fd38708eed2a8401dded1e55d609e3272930898",
        "instructions/platform.md": (
            "d89ba7eaffda1580178d215ad510e5401ed268473140cf3c3d53bb7195b9df91"
        ),
        "instructions/knowledge-analysis.md": (
            "992db112a0bfe5c864f2ca3b5ee3ef4fa2be5c1abba11c3a47bb436da4a3426e"
        ),
    }
    for relative_path, expected in expected_sha256.items():
        assert hashlib.sha256((ANALYSIS_CONFIG_V14 / relative_path).read_bytes()).hexdigest() == (
            expected
        )
    assert (ANALYSIS_CONFIG_V14 / "instructions/platform.md").read_bytes() == (
        ANALYSIS_CONFIG_V13 / "instructions/platform.md"
    ).read_bytes()
    role_instruction = (ANALYSIS_CONFIG_V14 / "instructions/knowledge-analysis.md").read_text(
        encoding="utf-8"
    )
    for required in (
        "For every `OBSERVED` page",
        "that exact physical page",
        "not a substitute for structured",
        "mark it `NO_RELEVANT_CONTENT`",
        "mark it `UNCLEAR`",
    ):
        assert required in role_instruction


def test_parallel_bootstrap_preserves_an_operator_assigned_account_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binding = SimpleNamespace(
        binding_id="authbinding_9a706de221738715d237009bd2710b07",
        worker_slot_id="06",
        account_label="textbook-analysis-slot06",
    )

    class FakeSession:
        @staticmethod
        def get(_model: object, _identity: str) -> object:
            return binding

    @contextmanager
    def fake_transaction(_sessions: object) -> Iterator[FakeSession]:
        yield FakeSession()

    monkeypatch.setattr(control_bootstrap, "transaction", fake_transaction)
    binding_ids = control_bootstrap._bootstrap_bindings(
        object(),  # type: ignore[arg-type]
        slots=(SimpleNamespace(slot_id="06"),),  # type: ignore[arg-type]
        observed_at=control_bootstrap.PARALLEL_ANALYSIS_CAPACITY_CREATED_AT,
    )

    assert binding_ids == (binding.binding_id,)
    assert binding.account_label == "textbook-analysis-slot06"


def test_standard_capacity_accepts_only_hash_pinned_shared_policy_revisions() -> None:
    assert {
        control_bootstrap._stable_id("capacityrev_", "fixed-host:v1"): (
            "sha256:6bac3c91a521c918f56b31cbb37b4d46ded100c0503988c10c7d53573ba59cd3"
        ),
        control_bootstrap._stable_id("capacityrev_", "fixed-host:v2"): (
            "sha256:392782a3811351199890a837b065d9bfa0a03a0578a47b32fd51e2dce716f806"
        ),
        control_bootstrap._stable_id("capacityrev_", "fixed-host:v3"): (
            "sha256:0d57aca8671aebd1f487bb1d39ef1bbfb75b07f618bd26a38e863d69920f1660"
        ),
    } == STANDARD_COMPATIBLE_CURRENT_CAPACITY_REVISIONS


def test_standard_bootstrap_manifest_is_bounded_and_credential_free() -> None:
    manifest = load_standard_bootstrap_manifest(CONFIG)
    assert manifest.preset_key == "standard-item"
    assert {role.role: role.slot_key for role in manifest.roles} == EXPECTED_ROLE_SLOTS
    assert manifest.support_slot_key == "slot05"
    assert manifest.general_knowledge_policy == "ALLOW_WITH_PROVENANCE"
    assert manifest.model == "gpt-5.6-terra"
    assert manifest.reasoning_effort == "high"
    tracked_v2 = tuple(path for path in CONFIG_V2.rglob("*") if path.is_file())
    assert tracked_v2 and all(path.is_file() and not path.is_symlink() for path in tracked_v2)
    source_v2 = "\n".join(path.read_text(encoding="utf-8") for path in tracked_v2).casefold()
    assert all(
        forbidden not in source_v2
        for forbidden in ("auth.json", "bearer ", "password=", "token=", "api_key")
    )
    assert (CONFIG_V2 / "references/general-knowledge-provenance.md").read_bytes() == (
        CONFIG / "references/general-knowledge-provenance.md"
    ).read_bytes()
    assert "integrated-science-single-item-authoring-v1.md" in (
        CONFIG_V2 / "instructions/authoring.md"
    ).read_text(encoding="utf-8")
    assert "kice-integrated-science-illustration-v1.md" in (
        CONFIG_V2 / "instructions/image.md"
    ).read_text(encoding="utf-8")
    item_management_instruction = (CONFIG_V2 / "instructions/item-management.md").read_text(
        encoding="utf-8"
    )
    assert "single-item-authoring" not in item_management_instruction
    assert "illustration" not in item_management_instruction
    tracked = tuple(path for path in CONFIG.rglob("*") if path.is_file())
    assert all(path.is_file() and not path.is_symlink() for path in tracked)
    source = "\n".join(path.read_text(encoding="utf-8") for path in tracked).casefold()
    assert all(
        forbidden not in source
        for forbidden in ("auth.json", "bearer ", "password=", "token=", "api_key")
    )


def test_standard_bootstrap_v2_is_role_scoped_and_preserves_v1_bytes() -> None:
    manifest = load_standard_bootstrap_manifest(CONFIG_V2)

    assert manifest.schema_version == "standard-control-bootstrap/2.0"
    assert {role.role: role.reference_keys for role in manifest.roles} == dict(
        EXPECTED_STANDARD_V2_REFERENCE_KEYS
    )
    assert tuple(reference.reference_key for reference in manifest.references) == (
        "general-knowledge-provenance",
        "integrated-science-single-item-authoring",
        "kice-integrated-science-illustration",
    )
    assert {reference.reference_key: reference.sha256 for reference in manifest.references} == {
        "general-knowledge-provenance": (
            "sha256:ff3859cb40aa66e37bbac632b0b35df3e314cc6d56aca0145dfedbea847d51f7"
        ),
        "integrated-science-single-item-authoring": (
            "sha256:00e3334573b120bf7f6f5c05aba28e58c4b2f0421a34705d15641cd5737accbc"
        ),
        "kice-integrated-science-illustration": (
            "sha256:9acdb63cfbc69583d852b386fddb205dfc6efc493a6b68195375b222139396ed"
        ),
    }
    assert manifest.model == "gpt-5.6-terra"
    assert manifest.reasoning_effort == "high"
    expected_v1_sha256 = {
        "bootstrap.yaml": "24f02d4dc88d5974fca1052430d9bbfdadaf0e003cc318aba43149e983cab83d",
        "instructions/authoring.md": (
            "dbbb746250ad56dec4ef10c9c6484d2b202553e6d8a5fddd2304076604aef25d"
        ),
        "instructions/image.md": (
            "71407504e92d908f8c2a34e2d7dcdcfbdf55824fcb80cc06018abd368fa26de5"
        ),
        "instructions/item-management.md": (
            "f283532321af9421b9afcbf951a7ac62f8fe17d232f2789e92d8ee22e20acb2a"
        ),
        "instructions/platform.md": (
            "0d91c68be0c5f61441c8b0481e093187bcd91a8586369c0c28b751819ac6ca25"
        ),
        "instructions/review.md": (
            "03047f8a0efb82c91d22691e3389959db310dcfd1b2efb10d87f44dc424d2647"
        ),
        "references/general-knowledge-provenance.md": (
            "ff3859cb40aa66e37bbac632b0b35df3e314cc6d56aca0145dfedbea847d51f7"
        ),
    }
    for relative_path, expected in expected_v1_sha256.items():
        assert hashlib.sha256((CONFIG / relative_path).read_bytes()).hexdigest() == expected


def test_standard_bootstrap_v3_selects_the_svg_first_protocol_without_secrets() -> None:
    manifest = load_standard_bootstrap_manifest(CONFIG_V3)

    assert manifest.schema_version == "standard-control-bootstrap/3.0"
    assert manifest.preset_key == "standard-item"
    assert manifest.compatible_workflow_protocols == ("workflow-role/1.12.0",)
    assert {role.role: role.slot_key for role in manifest.roles} == EXPECTED_ROLE_SLOTS
    assert {role.role: role.reference_keys for role in manifest.roles} == dict(
        EXPECTED_STANDARD_V2_REFERENCE_KEYS
    )
    assert hashlib.sha256((CONFIG_V3 / "bootstrap.yaml").read_bytes()).hexdigest() == (
        "835840e03abeabb33cd1a64d7c068cabd48b440b1af89860f786d04bfca1ae45"
    )
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in CONFIG_V3.rglob("*") if path.is_file()
    ).casefold()
    assert "deterministic_svg" in source
    assert all(
        forbidden not in source
        for forbidden in ("auth.json", "bearer ", "password=", "token=", "api_key")
    )


def test_standard_bootstrap_v4_pins_image_plan_protocol_and_preserves_v3() -> None:
    manifest = load_standard_bootstrap_manifest(CONFIG_V4)

    assert manifest.schema_version == "standard-control-bootstrap/4.0"
    assert manifest.preset_key == "standard-item"
    assert manifest.compatible_workflow_protocols == ("workflow-role/1.13.0",)
    assert {role.role: role.slot_key for role in manifest.roles} == EXPECTED_ROLE_SLOTS
    assert {role.role: role.reference_keys for role in manifest.roles} == dict(
        EXPECTED_STANDARD_V2_REFERENCE_KEYS
    )
    expected_v4_sha256 = {
        "bootstrap.yaml": "3c5521d3bd83ed5712d6b92ebf73adae8f32b52282ddda9d9883c9d6ae8f8b44",
        "instructions/authoring.md": (
            "89887d29172eec23491e1e11a108ceffd32e7546e080feea0bf2190af015f40d"
        ),
        "instructions/image.md": (
            "a72ca540fff9c24279f249d0b46c03119db96c8d511010792a72ab5606990954"
        ),
        "instructions/item-management.md": (
            "6f6f6acf786d09f3759c72e46bcf8a09671045a473a7269d010d90af20d64860"
        ),
        "instructions/platform.md": (
            "31513e33106313953fb2017268e08ff6cd1a64bce165c96ab5356860ffa08102"
        ),
        "instructions/review.md": (
            "36b8c1ddb1a334a7edc883d3f71e71dbb08c4a34939221082c0eefe5152d16e9"
        ),
        "references/general-knowledge-provenance.md": (
            "ff3859cb40aa66e37bbac632b0b35df3e314cc6d56aca0145dfedbea847d51f7"
        ),
    }
    for relative_path, expected in expected_v4_sha256.items():
        assert hashlib.sha256((CONFIG_V4 / relative_path).read_bytes()).hexdigest() == expected
    assert hashlib.sha256((CONFIG_V3 / "bootstrap.yaml").read_bytes()).hexdigest() == (
        "835840e03abeabb33cd1a64d7c068cabd48b440b1af89860f786d04bfca1ae45"
    )
    assert manifest.created_at > load_standard_bootstrap_manifest(CONFIG_V3).created_at
    assert (
        load_standard_bootstrap_manifest(CONFIG_V3).created_at
        == STANDARD_GUIDANCE_BUNDLE_CREATED_AT
    )
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in CONFIG_V4.rglob("*") if path.is_file()
    ).casefold()
    assert "hybrid_local_generative" in source
    assert "white" in source
    assert all(
        forbidden not in source
        for forbidden in ("auth.json", "bearer ", "password=", "token=", "api_key")
    )


def test_standard_bootstrap_v4_uses_a_distinct_instruction_bundle_revision() -> None:
    manifest_v2 = load_standard_bootstrap_manifest(CONFIG_V2)
    manifest_v3 = load_standard_bootstrap_manifest(CONFIG_V3)
    manifest_v4 = load_standard_bootstrap_manifest(CONFIG_V4)

    assert dict(STANDARD_BOOTSTRAP_INSTRUCTION_REVISIONS) == {
        "standard-control-bootstrap/1.0": 1,
        "standard-control-bootstrap/2.0": 2,
        "standard-control-bootstrap/3.0": 3,
        "standard-control-bootstrap/4.0": 4,
        "standard-control-bootstrap/5.0": 5,
        "standard-control-bootstrap/6.0": 6,
    }
    assert STANDARD_BOOTSTRAP_INSTRUCTION_REVISIONS[manifest_v2.schema_version] == 2
    assert STANDARD_BOOTSTRAP_INSTRUCTION_REVISIONS[manifest_v3.schema_version] == 3
    assert STANDARD_BOOTSTRAP_INSTRUCTION_REVISIONS[manifest_v4.schema_version] == 4


def test_standard_bootstrap_v5_pins_full_content_team_authoring_prompt() -> None:
    manifest = load_standard_bootstrap_manifest(CONFIG_V5)
    source_prompt = next((ROOT / "staging").glob("*v05.md"))
    pinned_prompt = (
        CONFIG_V5 / "references/guidance/content-team-integrated-science-authoring-v05.md"
    )

    assert manifest.schema_version == "standard-control-bootstrap/5.0"
    assert manifest.reasoning_effort == "high"
    assert manifest.compatible_workflow_protocols == ("workflow-role/1.13.0",)
    assert {role.role: role.reference_keys for role in manifest.roles} == dict(
        EXPECTED_STANDARD_V5_REFERENCE_KEYS
    )
    assert source_prompt.read_bytes() == pinned_prompt.read_bytes()
    assert hashlib.sha256(pinned_prompt.read_bytes()).hexdigest() == (
        "62f245320a4776a2ee3dcd273fb1180b6f3c431a45d2504d125816102f017435"
    )
    authoring = (CONFIG_V5 / "instructions/authoring.md").read_text(encoding="utf-8")
    assert "read the complete content-team source prompt" in authoring
    assert "do not rely on a summary or\nmemory of it" in authoring
    assert STANDARD_BOOTSTRAP_INSTRUCTION_REVISIONS[manifest.schema_version] == 5
    assert dict(STANDARD_BOOTSTRAP_REFERENCE_REVISIONS) == {
        "standard-control-bootstrap/1.0": 1,
        "standard-control-bootstrap/2.0": 1,
        "standard-control-bootstrap/3.0": 1,
        "standard-control-bootstrap/4.0": 1,
        "standard-control-bootstrap/5.0": 2,
        "standard-control-bootstrap/6.0": 3,
    }


def test_standard_bootstrap_v6_pins_source_prompt_and_handoff_profile() -> None:
    manifest = load_standard_bootstrap_manifest(CONFIG_V6)
    handoff = CONFIG_V6 / "references/guidance/content-team-hwp-question-editor-handoff-v1.md"

    assert manifest.schema_version == "standard-control-bootstrap/6.0"
    assert manifest.reasoning_effort == "high"
    assert manifest.compatible_workflow_protocols == ("workflow-role/1.15.0",)
    assert {role.role: role.reference_keys for role in manifest.roles} == dict(
        EXPECTED_STANDARD_V6_REFERENCE_KEYS
    )
    assert hashlib.sha256(handoff.read_bytes()).hexdigest() == (
        "6fdfd8f9dbc67abfcac9ef2761059bbe841a8b994640925fef30388d95a00ee5"
    )
    source_prompt = next(
        reference
        for reference in manifest.references
        if reference.reference_key == "content-team-integrated-science-authoring-v05"
    )
    assert source_prompt.source_root == "CONTROL_CONFIG"
    assert source_prompt.sha256 == (
        "sha256:62f245320a4776a2ee3dcd273fb1180b6f3c431a45d2504d125816102f017435"
    )
    source_prompt_path = CONFIG_V6.parent / source_prompt.source_path
    assert "sha256:" + hashlib.sha256(source_prompt_path.read_bytes()).hexdigest() == (
        source_prompt.sha256
    )
    authoring = (CONFIG_V6 / "instructions/authoring.md").read_text(encoding="utf-8")
    assert "These two files are the\nordered content-and-presentation reference set" in authoring
    assert "do not skip the source prompt" in authoring
    assert STANDARD_BOOTSTRAP_INSTRUCTION_REVISIONS[manifest.schema_version] == 6
    assert STANDARD_BOOTSTRAP_REFERENCE_REVISIONS[manifest.schema_version] == 3


def test_standard_bootstrap_v6_rejects_shared_config_escape() -> None:
    manifest = load_standard_bootstrap_manifest(CONFIG_V6)
    forged = manifest.model_dump(mode="json")
    forged["references"][0]["source_path"] = "../standard-item-v5/references/secret.md"

    with pytest.raises(ValidationError, match="reference path is unsafe"):
        StandardBootstrapManifest.model_validate(forged)


def test_standard_bootstrap_v4_rejects_legacy_protocol() -> None:
    manifest = load_standard_bootstrap_manifest(CONFIG_V4)
    forged = manifest.model_dump(mode="json")
    forged["compatible_workflow_protocols"] = ["workflow-role/1.12.0"]

    with pytest.raises(ValidationError, match="V4 protocol differs"):
        StandardBootstrapManifest.model_validate(forged)


def test_standard_bootstrap_v2_rejects_forged_role_reference_selection() -> None:
    manifest = load_standard_bootstrap_manifest(CONFIG_V2)
    forged = manifest.model_dump(mode="json")
    forged["roles"][1]["reference_keys"] = ["general-knowledge-provenance"]

    with pytest.raises(ValidationError, match="role reference map differs"):
        StandardBootstrapManifest.model_validate(forged)

    forged_path = manifest.model_dump(mode="json")
    forged_path["references"][1]["source_path"] = "authoring-rules/../secrets.md"
    with pytest.raises(ValidationError, match="reference path is unsafe"):
        StandardBootstrapManifest.model_validate(forged_path)


def test_standard_bootstrap_v2_rejects_changed_guidance_before_runtime_access(
    tmp_path: Path,
) -> None:
    config = tmp_path / "config"
    content = tmp_path / "content"
    shutil.copytree(CONFIG_V2, config)
    shutil.copytree(ROOT / "content/authoring-rules", content / "authoring-rules")
    shutil.copytree(ROOT / "content/image-specs", content / "image-specs")
    guide = content / "authoring-rules/integrated-science-single-item-authoring-v1.md"
    guide.write_bytes(guide.read_bytes() + b"\n")

    with pytest.raises(ControlPlaneError) as raised:
        bootstrap_standard_control_plane(
            object(),  # type: ignore[arg-type]
            config_directory=config.resolve(),
            content_directory=content.resolve(),
            source_commit="a" * 40,
            actor_id="unit-reviewer",
            evaluation_cases_total=1,
        )
    assert raised.value.code == "CONTROL_BOOTSTRAP_REFERENCE_HASH_MISMATCH"


def test_bootstrap_cli_requires_an_explicit_reviewed_source_directory() -> None:
    source = (ROOT / "apps/eomctl/eomctl/control_plane.py").read_text(encoding="utf-8")

    assert "STANDARD_CONFIG_DIRECTORY_OPTION = typer.Option(\n    ...," in source
    assert "STANDARD_CONTENT_DIRECTORY_OPTION = typer.Option(\n    None," in source
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
            (
                "knowledge-analysis-v3/bootstrap.yaml",
                "a4038b78c91c3ebbb817fee25d9914cb54332e366e49835e5b671de891c09828",
            ),
            (
                "knowledge-analysis-v3/instructions/platform.md",
                "43d44eaa7ff40594490da50e03c4dbec885593963b704d9751ba9bf89a789d9e",
            ),
            (
                "knowledge-analysis-v3/instructions/knowledge-analysis.md",
                "3b50dfe9f983adfc92d2b8015fcf38edc0dd3b1ceff1dbacfb75b33992e32200",
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


def test_knowledge_analysis_v4_uses_xhigh_without_mutating_v3() -> None:
    manifest = load_knowledge_analysis_bootstrap_manifest(ANALYSIS_CONFIG_V4)
    assert manifest.schema_version == "knowledge-analysis-control-bootstrap/4.0"
    assert manifest.model == "gpt-5.6-terra"
    assert manifest.reasoning_effort == "xhigh"
    assert manifest.timeout_seconds == 1800
    assert manifest.slot_key == "slot05"
    assert manifest.worker_pool_key == "support"
    assert manifest.general_knowledge_policy == "ALLOW_WITH_PROVENANCE"
    assert manifest.compatible_workflow_protocols == (
        "workflow-role/1.4.0",
        "workflow-role/1.5.0",
    )
    assert (
        hashlib.sha256((ANALYSIS_CONFIG_V3 / "bootstrap.yaml").read_bytes()).hexdigest()
        == "a4038b78c91c3ebbb817fee25d9914cb54332e366e49835e5b671de891c09828"
    )
    expected_v4_sha256 = {
        "bootstrap.yaml": "80cbf7a476dcaf8ba88414d09eaab37a4ed0ac76c029354d2a8d92db9987e567",
        "instructions/platform.md": (
            "43d44eaa7ff40594490da50e03c4dbec885593963b704d9751ba9bf89a789d9e"
        ),
        "instructions/knowledge-analysis.md": (
            "3b50dfe9f983adfc92d2b8015fcf38edc0dd3b1ceff1dbacfb75b33992e32200"
        ),
    }
    for relative_path, expected in expected_v4_sha256.items():
        assert hashlib.sha256((ANALYSIS_CONFIG_V4 / relative_path).read_bytes()).hexdigest() == (
            expected
        )
    assert (ANALYSIS_CONFIG_V4 / "instructions/knowledge-analysis.md").read_bytes() == (
        ANALYSIS_CONFIG_V3 / "instructions/knowledge-analysis.md"
    ).read_bytes()


def test_knowledge_analysis_v5_extends_timeout_without_mutating_v4() -> None:
    manifest = load_knowledge_analysis_bootstrap_manifest(ANALYSIS_CONFIG_V5)
    assert manifest.schema_version == "knowledge-analysis-control-bootstrap/5.0"
    assert manifest.model == "gpt-5.6-terra"
    assert manifest.reasoning_effort == "xhigh"
    assert manifest.timeout_seconds == 7200
    assert manifest.slot_key == "slot05"
    assert manifest.worker_pool_key == "support"
    assert manifest.general_knowledge_policy == "ALLOW_WITH_PROVENANCE"
    assert manifest.compatible_workflow_protocols == (
        "workflow-role/1.4.0",
        "workflow-role/1.5.0",
    )
    expected_v4_sha256 = {
        "bootstrap.yaml": "80cbf7a476dcaf8ba88414d09eaab37a4ed0ac76c029354d2a8d92db9987e567",
        "instructions/platform.md": (
            "43d44eaa7ff40594490da50e03c4dbec885593963b704d9751ba9bf89a789d9e"
        ),
        "instructions/knowledge-analysis.md": (
            "3b50dfe9f983adfc92d2b8015fcf38edc0dd3b1ceff1dbacfb75b33992e32200"
        ),
    }
    for relative_path, expected in expected_v4_sha256.items():
        assert hashlib.sha256((ANALYSIS_CONFIG_V4 / relative_path).read_bytes()).hexdigest() == (
            expected
        )
    expected_v5_sha256 = {
        "bootstrap.yaml": "aa80d5d14af6e5eef0de544cdd03aa88f44d3d0b62f565d703da507b042314ea",
        "instructions/platform.md": (
            "43d44eaa7ff40594490da50e03c4dbec885593963b704d9751ba9bf89a789d9e"
        ),
        "instructions/knowledge-analysis.md": (
            "3b50dfe9f983adfc92d2b8015fcf38edc0dd3b1ceff1dbacfb75b33992e32200"
        ),
    }
    for relative_path, expected in expected_v5_sha256.items():
        assert hashlib.sha256((ANALYSIS_CONFIG_V5 / relative_path).read_bytes()).hexdigest() == (
            expected
        )
    assert (ANALYSIS_CONFIG_V5 / "instructions/platform.md").read_bytes() == (
        ANALYSIS_CONFIG_V4 / "instructions/platform.md"
    ).read_bytes()
    assert (ANALYSIS_CONFIG_V5 / "instructions/knowledge-analysis.md").read_bytes() == (
        ANALYSIS_CONFIG_V4 / "instructions/knowledge-analysis.md"
    ).read_bytes()


def test_knowledge_analysis_v6_adds_endpoint_typed_protocol_without_dropping_legacy() -> None:
    manifest = load_knowledge_analysis_bootstrap_manifest(ANALYSIS_CONFIG_V6)
    assert manifest.schema_version == "knowledge-analysis-control-bootstrap/6.0"
    assert manifest.model == "gpt-5.6-terra"
    assert manifest.reasoning_effort == "xhigh"
    assert manifest.timeout_seconds == 7200
    assert manifest.compatible_workflow_protocols == (
        "workflow-role/1.4.0",
        "workflow-role/1.5.0",
        "workflow-role/1.6.0",
    )
    instruction = (ANALYSIS_CONFIG_V6 / manifest.role_instruction_path).read_text(encoding="utf-8")
    assert "ASSESSMENT_PATTERN" in instruction
    assert "ASSESSES_CONCEPT" in instruction
    assert "REQUIRES_CONCEPT" in instruction
    assert "from_node_type" in instruction
    expected_v6_sha256 = {
        "bootstrap.yaml": "1e988b5d67c792268a97d12e57a2d0b195ab9e8b86e363cce4ad5256f7471a1f",
        "instructions/platform.md": (
            "43d44eaa7ff40594490da50e03c4dbec885593963b704d9751ba9bf89a789d9e"
        ),
        "instructions/knowledge-analysis.md": (
            "62321ad1f3b268e20377aaf0663bcbcc3ef8265549ca6b597043e8aa3610c312"
        ),
    }
    for relative_path, expected in expected_v6_sha256.items():
        assert hashlib.sha256((ANALYSIS_CONFIG_V6 / relative_path).read_bytes()).hexdigest() == (
            expected
        )


def test_knowledge_analysis_v7_adds_integrity_protocol_without_mutating_v6() -> None:
    manifest = load_knowledge_analysis_bootstrap_manifest(ANALYSIS_CONFIG_V7)
    assert manifest.schema_version == "knowledge-analysis-control-bootstrap/7.0"
    assert manifest.model == "gpt-5.6-terra"
    assert manifest.reasoning_effort == "xhigh"
    assert manifest.timeout_seconds == 7200
    assert manifest.slot_key == "slot05"
    assert manifest.worker_pool_key == "support"
    assert manifest.compatible_workflow_protocols == (
        "workflow-role/1.4.0",
        "workflow-role/1.5.0",
        "workflow-role/1.6.0",
        "workflow-role/1.7.0",
    )
    instruction = (ANALYSIS_CONFIG_V7 / manifest.role_instruction_path).read_text(encoding="utf-8")
    for required in (
        "category_code",
        "anchor_id",
        "node_id",
        "stable_key",
        "edge_id",
        "claim_id",
        "component_id",
        "self-edge",
        "general_knowledge_used",
    ):
        assert required in instruction

    expected_v6_sha256 = {
        "bootstrap.yaml": "1e988b5d67c792268a97d12e57a2d0b195ab9e8b86e363cce4ad5256f7471a1f",
        "instructions/platform.md": (
            "43d44eaa7ff40594490da50e03c4dbec885593963b704d9751ba9bf89a789d9e"
        ),
        "instructions/knowledge-analysis.md": (
            "62321ad1f3b268e20377aaf0663bcbcc3ef8265549ca6b597043e8aa3610c312"
        ),
    }
    for relative_path, expected in expected_v6_sha256.items():
        assert hashlib.sha256((ANALYSIS_CONFIG_V6 / relative_path).read_bytes()).hexdigest() == (
            expected
        )
    expected_v7_sha256 = {
        "bootstrap.yaml": "fa9153c4174ba60c1de49e1e0bbf0f5fbc20ffc0756119d3e7f75fcd29d637d5",
        "instructions/platform.md": (
            "43d44eaa7ff40594490da50e03c4dbec885593963b704d9751ba9bf89a789d9e"
        ),
        "instructions/knowledge-analysis.md": (
            "eb65b46e3de26f459c9bd749960678aa3a69a66c705bc347f4915678d4a78538"
        ),
    }
    for relative_path, expected in expected_v7_sha256.items():
        assert hashlib.sha256((ANALYSIS_CONFIG_V7 / relative_path).read_bytes()).hexdigest() == (
            expected
        )


def test_knowledge_analysis_v8_requires_every_page_image_without_content_quotas() -> None:
    manifest = load_knowledge_analysis_bootstrap_manifest(ANALYSIS_CONFIG_V8)
    assert manifest.schema_version == "knowledge-analysis-control-bootstrap/8.0"
    assert manifest.model == "gpt-5.6-terra"
    assert manifest.reasoning_effort == "xhigh"
    assert manifest.timeout_seconds == 7200
    assert manifest.slot_key == "slot05"
    assert manifest.worker_pool_key == "support"
    assert manifest.compatible_workflow_protocols == (
        "workflow-role/1.4.0",
        "workflow-role/1.5.0",
        "workflow-role/1.6.0",
        "workflow-role/1.7.0",
        "workflow-role/1.8.0",
    )
    platform = (ANALYSIS_CONFIG_V8 / manifest.platform_instruction_path).read_text(encoding="utf-8")
    instruction = (ANALYSIS_CONFIG_V8 / manifest.role_instruction_path).read_text(encoding="utf-8")
    for required in (
        "visually",
        "page_image_observations",
        "OBSERVED",
        "NO_RELEVANT_CONTENT",
        "UNCLEAR",
        "Zero content records",
    ):
        assert required in instruction
    assert "never replace the mandatory page-image observation" in platform
    assert "quota" in instruction
    expected_v8_sha256 = {
        "bootstrap.yaml": "86801d777714b57fadaddd3c118997febfaeb3d591bb0d502e7655016d12b11b",
        "instructions/platform.md": (
            "d89ba7eaffda1580178d215ad510e5401ed268473140cf3c3d53bb7195b9df91"
        ),
        "instructions/knowledge-analysis.md": (
            "a01e69bfb6714087ce8eb55b031e71838f5640a8773f23385e5f59f77ee3f345"
        ),
    }
    for relative_path, expected in expected_v8_sha256.items():
        assert hashlib.sha256((ANALYSIS_CONFIG_V8 / relative_path).read_bytes()).hexdigest() == (
            expected
        )


def test_knowledge_analysis_v9_adds_schema_closed_protocol_without_mutating_v8() -> None:
    manifest = load_knowledge_analysis_bootstrap_manifest(ANALYSIS_CONFIG_V9)
    assert manifest.schema_version == "knowledge-analysis-control-bootstrap/9.0"
    assert manifest.model == "gpt-5.6-terra"
    assert manifest.reasoning_effort == "xhigh"
    assert manifest.timeout_seconds == 7200
    assert manifest.slot_key == "slot05"
    assert manifest.worker_pool_key == "support"
    assert manifest.compatible_workflow_protocols == (
        "workflow-role/1.4.0",
        "workflow-role/1.5.0",
        "workflow-role/1.6.0",
        "workflow-role/1.7.0",
        "workflow-role/1.8.0",
        "workflow-role/1.9.0",
    )
    expected_v9_sha256 = {
        "bootstrap.yaml": "9075e8a390a3d69752eb4f7a57093440c14981d514a6778487f68876673d2214",
        "instructions/platform.md": (
            "d89ba7eaffda1580178d215ad510e5401ed268473140cf3c3d53bb7195b9df91"
        ),
        "instructions/knowledge-analysis.md": (
            "a01e69bfb6714087ce8eb55b031e71838f5640a8773f23385e5f59f77ee3f345"
        ),
    }
    for relative_path, expected in expected_v9_sha256.items():
        assert hashlib.sha256((ANALYSIS_CONFIG_V9 / relative_path).read_bytes()).hexdigest() == (
            expected
        )
    assert (ANALYSIS_CONFIG_V9 / "instructions/platform.md").read_bytes() == (
        ANALYSIS_CONFIG_V8 / "instructions/platform.md"
    ).read_bytes()
    assert (ANALYSIS_CONFIG_V9 / "instructions/knowledge-analysis.md").read_bytes() == (
        ANALYSIS_CONFIG_V8 / "instructions/knowledge-analysis.md"
    ).read_bytes()


def test_knowledge_analysis_v10_adds_typed_identity_protocol_without_mutating_v9() -> None:
    manifest = load_knowledge_analysis_bootstrap_manifest(ANALYSIS_CONFIG_V10)
    assert manifest.schema_version == "knowledge-analysis-control-bootstrap/10.0"
    assert manifest.model == "gpt-5.6-terra"
    assert manifest.reasoning_effort == "xhigh"
    assert manifest.timeout_seconds == 7200
    assert manifest.slot_key == "slot05"
    assert manifest.worker_pool_key == "support"
    assert manifest.compatible_workflow_protocols == (
        "workflow-role/1.4.0",
        "workflow-role/1.5.0",
        "workflow-role/1.6.0",
        "workflow-role/1.7.0",
        "workflow-role/1.8.0",
        "workflow-role/1.9.0",
        "workflow-role/1.10.0",
    )
    expected_v10_sha256 = {
        "bootstrap.yaml": "36ac727107c36c5a0a9ce0c36a8d3ada6eba3f9f2f803c530abe1a9185918229",
        "instructions/platform.md": (
            "d89ba7eaffda1580178d215ad510e5401ed268473140cf3c3d53bb7195b9df91"
        ),
        "instructions/knowledge-analysis.md": (
            "c399c014030c6a27aff542c300340c10fdde521d0983ce3d6cfbbcd9102840ba"
        ),
    }
    for relative_path, expected in expected_v10_sha256.items():
        assert hashlib.sha256((ANALYSIS_CONFIG_V10 / relative_path).read_bytes()).hexdigest() == (
            expected
        )
    assert (ANALYSIS_CONFIG_V10 / "instructions/platform.md").read_bytes() == (
        ANALYSIS_CONFIG_V9 / "instructions/platform.md"
    ).read_bytes()
    role_instruction = (ANALYSIS_CONFIG_V10 / "instructions/knowledge-analysis.md").read_text(
        encoding="utf-8"
    )
    for required in (
        "knode_<lowercase_node_type>_",
        "relationship.from_node_type",
        "relationship.to_node_type",
        "must match",
    ):
        assert required in role_instruction


def test_knowledge_analysis_v11_adds_stable_identity_protocol_without_mutating_v10() -> None:
    manifest = load_knowledge_analysis_bootstrap_manifest(ANALYSIS_CONFIG_V11)
    assert manifest.schema_version == "knowledge-analysis-control-bootstrap/11.0"
    assert manifest.model == "gpt-5.6-terra"
    assert manifest.reasoning_effort == "xhigh"
    assert manifest.timeout_seconds == 7200
    assert manifest.compatible_workflow_protocols[-2:] == (
        "workflow-role/1.10.0",
        "workflow-role/1.11.0",
    )
    expected_v11_sha256 = {
        "bootstrap.yaml": "93b3c5f8004c1cdc28e410577846854e004312b5e566c5b7a5035e6e4e2c5378",
        "instructions/platform.md": (
            "d89ba7eaffda1580178d215ad510e5401ed268473140cf3c3d53bb7195b9df91"
        ),
        "instructions/knowledge-analysis.md": (
            "f9424697fe7e89ce776e7f0f8b247c74c2337700447e5a069e215fdc9fc1a56b"
        ),
    }
    for relative_path, expected in expected_v11_sha256.items():
        assert hashlib.sha256((ANALYSIS_CONFIG_V11 / relative_path).read_bytes()).hexdigest() == (
            expected
        )
    assert (ANALYSIS_CONFIG_V11 / "instructions/platform.md").read_bytes() == (
        ANALYSIS_CONFIG_V10 / "instructions/platform.md"
    ).read_bytes()
    role_instruction = (ANALYSIS_CONFIG_V11 / "instructions/knowledge-analysis.md").read_text(
        encoding="utf-8"
    )
    for required in ("stable_key", "<lowercase_node_type>:", "Never reuse a stable key"):
        assert required in role_instruction


def test_knowledge_analysis_v12_closes_edge_references_without_mutating_v11() -> None:
    manifest = load_knowledge_analysis_bootstrap_manifest(ANALYSIS_CONFIG_V12)
    assert manifest.schema_version == "knowledge-analysis-control-bootstrap/12.0"
    assert manifest.model == "gpt-5.6-terra"
    assert manifest.reasoning_effort == "xhigh"
    assert manifest.timeout_seconds == 7200
    assert manifest.compatible_workflow_protocols[-2:] == (
        "workflow-role/1.10.0",
        "workflow-role/1.11.0",
    )
    expected_v12_sha256 = {
        "bootstrap.yaml": "11a3e401bfd353838648d080580876eee192c29dc5e31cebc9e12a04e8eed8a3",
        "instructions/platform.md": (
            "d89ba7eaffda1580178d215ad510e5401ed268473140cf3c3d53bb7195b9df91"
        ),
        "instructions/knowledge-analysis.md": (
            "93bf41b30a4520fbbcb0e21dc88be0a0a815f4ac96c9237d0d21758728b1b1ea"
        ),
    }
    for relative_path, expected in expected_v12_sha256.items():
        assert hashlib.sha256((ANALYSIS_CONFIG_V12 / relative_path).read_bytes()).hexdigest() == (
            expected
        )
    assert (ANALYSIS_CONFIG_V12 / "instructions/platform.md").read_bytes() == (
        ANALYSIS_CONFIG_V11 / "instructions/platform.md"
    ).read_bytes()
    role_instruction = (ANALYSIS_CONFIG_V12 / "instructions/knowledge-analysis.md").read_text(
        encoding="utf-8"
    )
    for required in (
        "Freeze the complete `nodes` array",
        "closed node-ID map",
        "Omit the proposed edge before returning",
        "Never return a dangling edge endpoint",
    ):
        assert required in role_instruction


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
