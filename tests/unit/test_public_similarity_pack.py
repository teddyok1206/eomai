"""Exact immutable guidance successor; no worker, model or live activation."""

from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from eom_catalog_service.content_pack_files import build_pack, compile_pack
from eom_catalog_service.workflow_catalog import (
    WorkflowCatalogService,
    _enforces_svg_label_layout,
    _local_image_prompt_contract,
)
from eom_content_pack import render_prompt
from eom_image_contracts import SVG_LABEL_LAYOUT_PACK_BUNDLES
from eom_workflow.models import WorkflowRequest

from scripts.workflow.generate_public_similarity_pack_v12018 import (
    GUIDANCE,
    RULE_MARKER,
    SOURCE,
    TARGET,
    generate_pack,
    reference_rule,
)
from scripts.workflow.generate_similarity_reference_pack_v12017 import (
    reference_rule as old_reference_rule,
)
from scripts.workflow.generate_similarity_reference_pack_v12017 import (
    tree_bytes,
)


def test_only_guidance_profile_version_and_pack_identity_change():
    before, after = tree_bytes(SOURCE), tree_bytes(TARGET)
    assert before.keys() == after.keys()
    assert {key for key in before if before[key] != after[key]} == {
        Path("pack.yaml"),
        Path("profiles/generated-knowledge-authoring.yaml"),
        Path("profiles/generated-knowledge-review.yaml"),
        Path("prompt-templates/authoring.md"),
        Path("prompt-templates/review.md"),
    }
    assert (
        compile_pack(SOURCE).manifest.compatibility == compile_pack(TARGET).manifest.compatibility
    )
    for role in ("authoring", "review"):
        path = Path(f"profiles/generated-knowledge-{role}.yaml")
        old, new = yaml.safe_load(before[path]), yaml.safe_load(after[path])
        assert new["profile"]["version"] == "12.4.0"
        new["profile"]["version"] = old["profile"]["version"]
        assert new == old
        path = Path(f"prompt-templates/{role}.md")
        assert (
            after[path].decode()
            == before[path].decode().removesuffix(old_reference_rule()) + reference_rule()
        )


def test_generation_is_deterministic_without_mutating_or_overwriting_predecessor(tmp_path):
    before = tree_bytes(SOURCE)
    generated = tmp_path / "candidate"
    generate_pack(generated)
    assert tree_bytes(generated) == tree_bytes(TARGET)
    with pytest.raises(FileExistsError):
        generate_pack(generated)
    assert tree_bytes(SOURCE) == before


@pytest.mark.parametrize("role", ("authoring", "review"))
@pytest.mark.parametrize("mode", ("NOT_OFFERED", "PINNED_REFERENCE_CONTEXT"))
def test_public_prompt_renders_one_exact_guidance_without_legacy_field_requirement(role, mode):
    profile = yaml.safe_load((TARGET / f"profiles/generated-knowledge-{role}.yaml").read_text())
    context = {}
    for key in profile["required_context"]:
        pieces, branch = key.split("."), context
        for piece in pieces[:-1]:
            branch = branch.setdefault(piece, {})
        branch[pieces[-1]] = mode if key == "similarity.reference_mode" else "null"
    result = render_prompt(
        (TARGET / profile["template"]).read_text(), context, tuple(profile["required_context"])
    )
    assert "{{" not in result.text and result.text.count(RULE_MARKER) == 1
    assert "BEGIN_SYSTEM_RAG_SIMILARITY_REFERENCE_V1" not in result.text
    assert f"source_sha256=sha256:{sha256(GUIDANCE.read_bytes()).hexdigest()}" in result.text
    assert f"전달 mode: `{mode}`" in result.text
    assert "구형 `anchor_profile` 필드는 이 형식에 없다" in result.text


def test_public_guidance_preserves_specific_reasoning_and_original_review_rules():
    text = GUIDANCE.read_text()
    for required in (
        "entry.public_solution",
        "question.content.text",
        "UNAVAILABLE",
        "최대 3교",
        "R == U",
        "copy_policy",
        "STRUCTURE_PATTERN",
        "GIVEN_CONDITION",
        "DECISIVE_INFERENCE",
        "같은 풀이의 확률",
        "비공개 사고과정 전문",
        "신뢰할 수 없는",
        "새\nevidence ID",
        "CONCRETE_FACETS",
    ):
        assert required in text
    assert "원본 Graph Evidence" in text


def test_pack_keeps_native_material_and_exact_image_contract(tmp_path):
    built = build_pack(TARGET, tmp_path / "build")
    assert built.bundle_sha256 == SVG_LABEL_LAYOUT_PACK_BUNDLES["1.20.18"]
    request = WorkflowRequest.model_validate_json(
        (TARGET / "fixtures/smoke-request.json").read_bytes()
    )
    WorkflowCatalogService._require_item_brief_release(
        "generated-knowledge-item", "1.20.18", request
    )
    workflow = SimpleNamespace(
        runtime_context={
            "content_pack": {"version": "1.20.18", "release_sha256": built.bundle_sha256}
        }
    )
    assert _enforces_svg_label_layout(workflow)
    assert _local_image_prompt_contract(workflow) == "ASSESSMENT_REFERENCE_COMPOSITION_V3"
