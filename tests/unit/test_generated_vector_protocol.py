from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from eom_workflow.compiler import compile_definition
from eom_workflow.models import ArtifactSpec, GeneratedImageRoleResultV5, GeneratedVectorDrawingV5
from eom_workflow.schemas import (
    load_role_result_schema,
    role_schema_bundle_hash,
    validate_role_result,
)
from jsonschema import Draft202012Validator

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
            '<text fill="#000000" font-family="Droid Sans Fallback" font-size="20" '
            'x="445" y="100">온도계</text>'
            '<text fill="#000000" font-family="Droid Sans Fallback" font-size="20" '
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
