from __future__ import annotations

import hashlib
from pathlib import Path

from eom_catalog_service.content_pack_files import compile_pack
from eom_catalog_service.workflow_catalog import (
    WorkflowCatalogService,
    _local_image_prompt_contract,
)
from eom_workflow.models import WorkflowRequest
from eom_workflow_runner.models import WorkflowInstanceRecord

ROOT = Path(__file__).resolve().parents[2]
PREDECESSOR = ROOT / "content/packs/generated-knowledge-item/1.19.0"
PACK = ROOT / "content/packs/generated-knowledge-item/1.20.0"


def test_assessment_image_pack_is_an_immutable_compatible_successor() -> None:
    predecessor = compile_pack(PREDECESSOR)
    pack = compile_pack(PACK)

    assert predecessor.source_tree_sha256 == (
        "sha256:5ef75c25b9fc6254ce836b007df3ef49cce8c43c609a83f089b6390679228880"
    )
    assert pack.source_tree_sha256 == (
        "sha256:0f62ea0d1be5fa0394f1aef747b948ae59161fdccbee0b58e68a565dbcf2e949"
    )
    assert pack.manifest.pack.version == "1.20.0"
    assert pack.manifest.compatibility.protocol.minimum == "1.24.0"
    assert pack.manifest.compatibility.protocol.maximum_exclusive == "1.25.0"
    assert pack.manifest.compatibility.workflow_definitions[0].versions == ("1.13.0",)

    request = WorkflowRequest.model_validate_json(
        (PACK / "fixtures/smoke-request.json").read_text(encoding="utf-8")
    )
    WorkflowCatalogService._require_item_brief_release(
        "generated-knowledge-item",
        "1.20.0",
        request,
    )


def test_image_prompt_preserves_team_authorities_and_requires_local_english_subject() -> None:
    predecessor = (PREDECESSOR / "prompt-templates/image.md").read_text(encoding="utf-8")
    successor = (PACK / "prompt-templates/image.md").read_text(encoding="utf-8")

    assert successor.startswith(predecessor.rstrip())
    for required in (
        "520개 occurrence-backed 기출 분석",
        "HYBRID_LOCAL_GENERATIVE",
        "DETERMINISTIC_SVG",
        "영어 subject",
        "3~180 ASCII 문자",
        "one trilobite fossil isolated on white",
        "scene_description",
        "scientific_constraints",
        "정확한 개수, 시점(side view/cross-section 등), 외형, 핵심 물리 상태",
        "팀장의 exact `illustration_prompt`",
        "policy revision과 prompt hash",
    ):
        assert required in successor

    assert "GPU에는 사람을 요청하지 않는다" in successor
    assert "그래프, 지도, 실험 장치, 입자 모형" in successor
    assert (
        hashlib.sha256(
            (
                ROOT / "config/control-plane/standard-item-v5/references/guidance/"
                "content-team-integrated-science-authoring-v05.md"
            ).read_bytes()
        ).hexdigest()
        == "62f245320a4776a2ee3dcd273fb1180b6f3c431a45d2504d125816102f017435"
    )
    assert (
        hashlib.sha256(
            (
                ROOT / "config/control-plane/standard-item-v6/references/guidance/"
                "content-team-hwp-question-editor-handoff-v1.md"
            ).read_bytes()
        ).hexdigest()
        == "6fdfd8f9dbc67abfcac9ef2761059bbe841a8b994640925fef30388d95a00ee5"
    )


def test_only_image_profile_revision_changes_inside_successor_pack() -> None:
    predecessor_files = {
        path.relative_to(PREDECESSOR): path.read_bytes()
        for path in PREDECESSOR.rglob("*")
        if path.is_file()
    }
    successor_files = {
        path.relative_to(PACK): path.read_bytes() for path in PACK.rglob("*") if path.is_file()
    }
    assert predecessor_files.keys() == successor_files.keys()
    changed = {
        path for path in predecessor_files if predecessor_files[path] != successor_files[path]
    }
    assert changed == {
        Path("pack.yaml"),
        Path("profiles/generated-stimulus-drawing.yaml"),
        Path("prompt-templates/image.md"),
    }


def test_prompt_contract_is_selected_from_the_pinned_pack_version() -> None:
    workflow = WorkflowInstanceRecord()
    workflow.runtime_context = {"content_pack": {"version": "1.20.0"}}
    assert _local_image_prompt_contract(workflow) == "ASSESSMENT_LINE_ART_V1"

    workflow.runtime_context = {"content_pack": {"version": "1.19.0"}}
    assert _local_image_prompt_contract(workflow) == "LEGACY_COMPAT"
