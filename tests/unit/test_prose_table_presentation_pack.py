from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest
import yaml
from eom_catalog_service.content_pack_files import build_pack, compile_pack
from eom_catalog_service.workflow_catalog import (
    WorkflowCatalogService,
    _enforces_svg_label_layout,
    _local_image_prompt_contract,
    _uses_v1_reference_conditioning,
)
from eom_content_pack import ContentPackError, render_prompt
from eom_image_contracts import SVG_LABEL_LAYOUT_PACK_BUNDLES, LocalImageProviderBinding
from eom_workflow.models import WorkflowRequest
from eom_workflow_runner.models import WorkflowInstanceRecord

from scripts.workflow.generate_prose_table_presentation_pack_v12015 import (
    GUIDANCE,
    NEXT_HEADING,
    PRESENTATION_HEADING,
    generate_pack,
    presentation_rule,
    tree_bytes,
)
from tests.unit.test_local_image_adapter import _binding_value

ROOT = Path(__file__).resolve().parents[2]
PREDECESSOR = ROOT / "content/packs/generated-knowledge-item/1.20.14"
PACK = ROOT / "content/packs/generated-knowledge-item/1.20.15"
AUTHORING_SOURCE = (
    ROOT / "config/control-plane/standard-item-v5/references/guidance/"
    "content-team-integrated-science-authoring-v05.md"
)
HANDOFF_V1 = (
    ROOT / "config/control-plane/standard-item-v6/references/guidance/"
    "content-team-hwp-question-editor-handoff-v1.md"
)


def test_prose_table_successor_preserves_the_original_and_released_guidance() -> None:
    assert sha256(AUTHORING_SOURCE.read_bytes()).hexdigest() == (
        "62f245320a4776a2ee3dcd273fb1180b6f3c431a45d2504d125816102f017435"
    )
    assert sha256(HANDOFF_V1.read_bytes()).hexdigest() == (
        "6fdfd8f9dbc67abfcac9ef2761059bbe841a8b994640925fef30388d95a00ee5"
    )
    assert (
        sha256(
            (ROOT / "content/image-specs/kice-integrated-science-illustration-v1.md").read_bytes()
        ).hexdigest()
        == "9acdb63cfbc69583d852b386fddb205dfc6efc493a6b68195375b222139396ed"
    )


def test_prose_table_pack_changes_only_owned_editorial_prompt_files() -> None:
    predecessor = tree_bytes(PREDECESSOR)
    successor = tree_bytes(PACK)
    assert predecessor.keys() == successor.keys()
    assert {path for path in predecessor if predecessor[path] != successor[path]} == {
        Path("pack.yaml"),
        Path("profiles/generated-knowledge-authoring.yaml"),
        Path("profiles/generated-knowledge-review.yaml"),
        Path("prompt-templates/authoring.md"),
        Path("prompt-templates/review.md"),
    }
    for role in ("authoring", "review"):
        before = (PREDECESSOR / f"prompt-templates/{role}.md").read_text(encoding="utf-8")
        after = (PACK / f"prompt-templates/{role}.md").read_text(encoding="utf-8")
        assert after == before.rstrip() + presentation_rule()
        old_profile = yaml.safe_load(
            (PREDECESSOR / f"profiles/generated-knowledge-{role}.yaml").read_text()
        )
        new_profile = yaml.safe_load(
            (PACK / f"profiles/generated-knowledge-{role}.yaml").read_text()
        )
        assert new_profile["profile"]["version"] == "12.2.1"
        new_profile["profile"]["version"] = old_profile["profile"]["version"]
        assert new_profile == old_profile


def test_prose_table_pack_is_a_compatible_compiled_successor() -> None:
    predecessor = compile_pack(PREDECESSOR)
    pack = compile_pack(PACK)
    assert pack.manifest.pack.version == "1.20.15"
    assert pack.manifest.compatibility == predecessor.manifest.compatibility
    request = WorkflowRequest.model_validate_json(
        (PACK / "fixtures/smoke-request.json").read_text(encoding="utf-8")
    )
    WorkflowCatalogService._require_item_brief_release(
        "generated-knowledge-item", "1.20.15", request
    )


@pytest.mark.parametrize(
    "version", ("1.15.9", "1.20.0", "1.20.3", "1.20.11", "1.20.12", "1.20.13", "1.20.14")
)
def test_historical_pack_briefs_keep_their_exact_compatibility(version: str) -> None:
    source = ROOT / f"content/packs/generated-knowledge-item/{version}/fixtures/smoke-request.json"
    request = WorkflowRequest.model_validate_json(source.read_text(encoding="utf-8"))
    WorkflowCatalogService._require_item_brief_release("generated-knowledge-item", version, request)


def test_successor_does_not_accept_an_older_brief_or_guess_an_unknown_release() -> None:
    old_request = WorkflowRequest.model_validate_json(
        (
            ROOT / "content/packs/generated-knowledge-item/1.20.11/fixtures/smoke-request.json"
        ).read_text(encoding="utf-8")
    )
    with pytest.raises(ContentPackError, match="material-aware item brief differ"):
        WorkflowCatalogService._require_item_brief_release(
            "generated-knowledge-item", "1.20.15", old_request
        )
    current_request = WorkflowRequest.model_validate_json(
        (PACK / "fixtures/smoke-request.json").read_text(encoding="utf-8")
    )
    with pytest.raises(ContentPackError, match="requires the content-team pack"):
        WorkflowCatalogService._require_item_brief_release(
            "generated-knowledge-item", "1.20.16", current_request
        )


def test_successor_retains_the_pinned_reference_image_policy_and_label_gate(tmp_path: Path) -> None:
    built = build_pack(PACK, tmp_path / "pack")
    assert SVG_LABEL_LAYOUT_PACK_BUNDLES["1.20.15"] == built.bundle_sha256
    workflow = WorkflowInstanceRecord()
    workflow.runtime_context = {
        "content_pack": {"version": "1.20.15", "release_sha256": built.bundle_sha256}
    }
    assert _local_image_prompt_contract(workflow) == "ASSESSMENT_REFERENCE_COMPOSITION_V3"
    assert _uses_v1_reference_conditioning(
        workflow, LocalImageProviderBinding.model_validate(_binding_value())
    )
    assert _enforces_svg_label_layout(workflow)

    workflow.runtime_context["content_pack"]["release_sha256"] = SVG_LABEL_LAYOUT_PACK_BUNDLES[
        "1.20.14"
    ]
    assert not _enforces_svg_label_layout(workflow)


def test_one_guidance_source_balances_prose_with_small_and_qualitative_tables() -> None:
    guidance = GUIDANCE.read_text(encoding="utf-8")
    section = guidance.split(PRESENTATION_HEADING, 1)[1].split(NEXT_HEADING, 1)[0].strip()
    for requirement in (
        "별도의 `<자료>`/`[자료]` 제목, DATA block",
        "모든 정보를 줄글로 옮기라는 뜻이 아니다",
        "줄글과 native TABLE을 동등하게 검토한다",
        "값이 적거나 문장으로도 표현할 수 있다는 이유로 표를 피하지 않는다",
        "표는 숫자 전용이 아니다",
        "짧은 설명 문장, 현상의 예",
        "숫자 개수나 글자 수의 고정 임계값",
        "고정 문장이 아니다",
        "표의 모든 셀을 발문에서 다시 나열하지 마라",
        "IMAGE를 MIXED로 임의 변경하지 않는다",
        "표를 사용할\n  수 있다는 이유만으로 정상 줄글을 오류로 판정하지 않는다",
        "표현 취향만으로 blocking finding을 만들거나",
    ):
        assert requirement in section
    rule = presentation_rule()
    assert section in rule
    assert f"source_sha256=sha256:{sha256(GUIDANCE.read_bytes()).hexdigest()}" in rule


@pytest.mark.parametrize("role", ("authoring", "review"))
def test_rendered_worker_prompt_contains_the_clarification_without_new_context(role: str) -> None:
    profile = yaml.safe_load(
        (PACK / f"profiles/generated-knowledge-{role}.yaml").read_text(encoding="utf-8")
    )
    context: dict[str, object] = {}
    for variable in profile["required_context"]:
        parts = variable.split(".")
        branch = context
        for part in parts[:-1]:
            child = branch.setdefault(part, {})
            assert isinstance(child, dict)
            branch = child
        branch[parts[-1]] = "null" if parts[-1].endswith("json") else "synthetic-test-value"
    prompt = (PACK / profile["template"]).read_text(encoding="utf-8")
    rendered = render_prompt(prompt, context, tuple(profile["required_context"]))

    assert "{{" not in rendered.text
    assert rendered.text.count("BEGIN_CONTENT_TEAM_PRESENTATION_V2") == 1
    assert rendered.text.count("END_CONTENT_TEAM_PRESENTATION_V2") == 1
    assert presentation_rule().strip() in rendered.text
    assert "별도의\nV2 파일이 있다고 추측하지 마라" in rendered.text


def test_generated_prose_table_pack_is_reproducible_and_never_overwrites(tmp_path: Path) -> None:
    generated = tmp_path / "1.20.15"
    generate_pack(generated)
    expected = tree_bytes(PACK)
    assert tree_bytes(generated) == expected
    with pytest.raises(FileExistsError):
        generate_pack(generated)
    assert tree_bytes(generated) == expected
