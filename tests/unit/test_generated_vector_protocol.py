from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from eom_workflow.compiler import compile_definition
from eom_workflow.models import (
    ArtifactSpec,
    GeneratedImageRoleResultV5,
    GeneratedImageRoleResultV6,
    GeneratedVectorDrawingV5,
    GeneratedVectorDrawingV6,
)
from eom_workflow.schemas import (
    load_role_result_schema,
    role_schema_bundle_hash,
    validate_role_result,
)
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError

ROOT = Path(__file__).resolve().parents[2]
ROLES = {"authoring", "image", "review", "item_management"}


def _drawing() -> GeneratedVectorDrawingV5:
    return GeneratedVectorDrawingV5(
        kind="apparatus",
        production_route="DETERMINISTIC_SVG",
        background_style="WHITE",
        alt_text="비커와 온도계를 사용한 가열 실험 장치",
        scene_description="비커 안 액체에 온도계를 담그고 아래에서 가열한다.",
        scientific_constraints=("온도계 구부가 비커 바닥에 닿지 않는다.",),
        required_labels=("온도계", "비커"),
        generation_prompt="교과서형 흑백 선화 실험 장치를 그린다.",
        negative_prompt=None,
        svg_overlay=(
            '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="500" '
            'viewBox="0 0 800 500">'
            '<rect fill="none" height="220" stroke="#000000" stroke-width="4" '
            'width="280" x="270" y="170"></rect>'
            '<line stroke="#000000" stroke-width="5" x1="430" x2="430" '
            'y1="70" y2="300"></line>'
            '<text fill="#000000" font-family="SM JGothic Std, Noto Sans CJK KR" font-size="20" '
            'x="445" y="100">온도계</text>'
            '<text fill="#000000" font-family="SM JGothic Std, Noto Sans CJK KR" font-size="20" '
            'x="360" y="430">비커</text>'
            "</svg>"
        ),
    )


def _drawing_v6(*, hybrid: bool = False) -> GeneratedVectorDrawingV6:
    return GeneratedVectorDrawingV6(
        kind="natural_scene" if hybrid else "apparatus",
        production_route="HYBRID_LOCAL_GENERATIVE" if hybrid else "DETERMINISTIC_SVG",
        route_reason=("HUMAN_OR_ANIMAL_REQUIRED" if hybrid else "SCIENTIFIC_SCHEMATIC"),
        background_style="WHITE",
        alt_text="학생이 비커와 온도계를 사용해 가열 실험을 관찰한다.",
        scene_description="학생과 비커, 온도계가 있는 과학 실험 장면이다.",
        scientific_constraints=("온도계 구부가 비커 바닥에 닿지 않는다.",),
        required_labels=("온도계", "비커"),
        generation_prompt=("비커를 관찰하는 학생 한 명과 자연스러운 실험 장면" if hybrid else None),
        negative_prompt=("추가 인물, 장식" if hybrid else None),
        svg_overlay=(
            '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="500" '
            'viewBox="0 0 800 500">'
            '<rect fill="none" height="220" stroke="#000000" stroke-width="4" '
            'width="280" x="270" y="170"></rect>'
            '<text fill="#000000" font-family="SM JGothic Std, Noto Sans CJK KR" font-size="20" '
            'x="445" y="100">온도계</text>'
            '<text fill="#000000" font-family="SM JGothic Std, Noto Sans CJK KR" font-size="20" '
            'x="360" y="430">비커</text>'
            "</svg>"
        ),
    )


def test_v5_vector_schema_is_schema_first_and_typed() -> None:
    drawing = _drawing()
    image_schema = load_role_result_schema("image-result@5.0")
    Draft202012Validator(image_schema["$defs"]["GeneratedVectorDrawingV5"]).validate(
        drawing.model_dump(mode="json")
    )
    authoring_schema = load_role_result_schema("authoring-result@5.0")
    brief = drawing.model_dump(mode="json")
    for output_only in ("width_px", "height_px", "svg_overlay"):
        brief.pop(output_only)
    Draft202012Validator(authoring_schema["$defs"]["GeneratedVectorImageBriefV5"]).validate(brief)


def test_v5_image_role_result_validates_against_static_and_typed_contracts() -> None:
    result = GeneratedImageRoleResultV5(
        job_id="job_" + "1" * 32,
        workflow_id="workflow_" + "2" * 32,
        step_run_id="steprun_" + "3" * 32,
        role="image",
        artifact=ArtifactSpec(
            logical_artifact_id="artifact_" + "4" * 32,
            revision_id="rev_" + "5" * 32,
        ),
        completed_at=datetime(2026, 8, 28, tzinfo=UTC),
        output={"drawing": _drawing(), "summary": "과학 제약을 보존한 SVG 장치를 설계했다."},
    )
    parsed = validate_role_result(result.model_dump(mode="json"), "image", "image-result@5.0")
    assert isinstance(parsed, GeneratedImageRoleResultV5)


def test_v5_workflow_uses_one_new_protocol_without_rewriting_v4() -> None:
    compiled = compile_definition(
        ROOT / "config/workflows/generic-item-development.v1.5.yaml",
        ROLES,
    )
    assert compiled.definition.definition_version == "1.5.0"
    assert [
        step.result_schema for step in compiled.definition.steps if hasattr(step, "result_schema")
    ] == [
        "authoring-result@5.0",
        "image-result@5.0",
        "review-result@5.0",
        "registration-result@5.0",
    ]
    assert role_schema_bundle_hash("workflow-role/1.12.0") == (
        "sha256:d1b0254d6b52cf1be6f009c3188d85113e61c37d6e4001e7aa41a8f7bdf7ba04"
    )


def test_historical_v4_role_schema_bytes_remain_pinned() -> None:
    expected = {
        "authoring": "574f6e639b490e4ccdb5575eb69ab1f5449d9ef0cdcfdb10ff5c5502ba71fee8",
        "image": "98f31f61396be3acd262c4adb07b4f560ed0469bd7d4c4b854a4c1a16846bd1f",
        "review": "97734037944887cce2d28527b811c68824fc5d0efb1ad8e68f050f8263785acd",
        "registration": "0f6d39e3bdeaaf527bf3563621f76270f6f7d30e89cded3829f30f4e56f6b308",
    }
    for role, digest in expected.items():
        payload = (ROOT / f"schemas/workflow/roles/{role}-result-v4.schema.json").read_bytes()
        assert hashlib.sha256(payload).hexdigest() == digest


def test_v5_role_schema_family_is_mirrored_and_pinned() -> None:
    expected = {
        "authoring": "9cc1b0579b186fb9d26329734b8f82ed814ae2cff22a17a2c76af2cfc61def9e",
        "image": "957f9ec6863df0de76540d9f8a666299e45883239f806bafb745bf37f23fcfc4",
        "review": "aa50f25d107e02ead3c8711802adb69171050f078011ef6a2480b208cfe11d4a",
        "registration": "97aa836b02139b98a769ce4a70fc9e03dbef288970cb5b9beb71972975ef8283",
    }
    for role, digest in expected.items():
        canonical = ROOT / f"schemas/workflow/roles/{role}-result-v5.schema.json"
        packaged = (
            ROOT / f"packages/workflow/eom_workflow/resources/roles/{role}-result-v5.schema.json"
        )
        assert hashlib.sha256(canonical.read_bytes()).hexdigest() == digest
        assert packaged.read_bytes() == canonical.read_bytes()


@pytest.mark.parametrize("hybrid", [False, True])
def test_v6_image_plan_is_schema_first_and_typed(hybrid: bool) -> None:
    drawing = _drawing_v6(hybrid=hybrid)
    schema = load_role_result_schema("image-result@6.0")["$defs"]["GeneratedVectorDrawingV6"]
    Draft202012Validator(schema).validate(drawing.model_dump(mode="json"))
    assert (drawing.production_route == "HYBRID_LOCAL_GENERATIVE") is hybrid
    assert (drawing.generation_prompt is not None) is hybrid


@pytest.mark.parametrize(
    ("route", "reason", "prompt"),
    [
        ("DETERMINISTIC_SVG", "HUMAN_OR_ANIMAL_REQUIRED", None),
        ("DETERMINISTIC_SVG", "SCIENTIFIC_SCHEMATIC", "GPU를 호출한다."),
        ("HYBRID_LOCAL_GENERATIVE", "SCIENTIFIC_SCHEMATIC", "학생 한 명"),
        ("HYBRID_LOCAL_GENERATIVE", "HUMAN_OR_ANIMAL_REQUIRED", None),
    ],
)
def test_v6_image_plan_rejects_contradictory_gpu_decisions(
    route: str, reason: str, prompt: str | None
) -> None:
    value = _drawing_v6(hybrid=False).model_dump(mode="json")
    value.update(
        {
            "kind": "natural_scene",
            "production_route": route,
            "route_reason": reason,
            "generation_prompt": prompt,
        }
    )
    with pytest.raises(ValueError):
        GeneratedVectorDrawingV6.model_validate(value)
    schema = load_role_result_schema("image-result@6.0")["$defs"]["GeneratedVectorDrawingV6"]
    with pytest.raises(JsonSchemaValidationError):
        Draft202012Validator(schema).validate(value)


def test_v6_role_result_and_workflow_use_one_new_immutable_protocol() -> None:
    result = GeneratedImageRoleResultV6(
        job_id="job_" + "1" * 32,
        workflow_id="workflow_" + "2" * 32,
        step_run_id="steprun_" + "3" * 32,
        role="image",
        artifact=ArtifactSpec(
            logical_artifact_id="artifact_" + "4" * 32,
            revision_id="rev_" + "5" * 32,
        ),
        completed_at=datetime(2026, 9, 1, tzinfo=UTC),
        output={"drawing": _drawing_v6(), "summary": "GPU 없이 결정론적 SVG를 선택했다."},
    )
    parsed = validate_role_result(result.model_dump(mode="json"), "image", "image-result@6.0")
    assert isinstance(parsed, GeneratedImageRoleResultV6)
    compiled = compile_definition(
        ROOT / "config/workflows/generic-item-development.v1.6.yaml",
        ROLES,
    )
    assert compiled.definition.definition_version == "1.6.0"
    assert [
        step.result_schema for step in compiled.definition.steps if hasattr(step, "result_schema")
    ] == [
        "authoring-result@6.0",
        "image-result@6.0",
        "review-result@6.0",
        "registration-result@6.0",
    ]
    assert role_schema_bundle_hash("workflow-role/1.13.0") == (
        "sha256:7a3975489146f6982830acf1fb0605d9f3ff39739343f939337e88c5c86b87eb"
    )


def test_v6_role_schema_family_is_mirrored_and_pinned() -> None:
    expected = {
        "authoring": "a923eda220287c84fcd79c14ed6054e3cbae496e57f2208e271875b8fa9a20a3",
        "image": "fd6be81ccf2a63edd3801b0fba16742242842057a2f0b8c491a93b90b7b43e1e",
        "review": "118c76d95720001081e4140fe0250d4ae9cf1a2930775a43111730f42ef8eccc",
        "registration": "5366e92538b7feccdf6edbdc092f1f1fba1b18ff37de87c6207c70d829d48b41",
    }
    for role, digest in expected.items():
        canonical = ROOT / f"schemas/workflow/roles/{role}-result-v6.schema.json"
        packaged = (
            ROOT / f"packages/workflow/eom_workflow/resources/roles/{role}-result-v6.schema.json"
        )
        assert hashlib.sha256(canonical.read_bytes()).hexdigest() == digest
        assert packaged.read_bytes() == canonical.read_bytes()
    assert "LOCAL_GENERATIVE_BACKGROUND" not in json.dumps(
        load_role_result_schema("image-result@6.0"), sort_keys=True
    )
