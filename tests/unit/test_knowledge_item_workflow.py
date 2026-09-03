from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import pytest
import yaml
from eom_catalog_contracts import (
    AssessmentItemContent,
    ContentPackManifest,
    validate_contract,
    validate_eom_question_template_content,
)
from eom_catalog_service.content_pack_files import compile_pack
from eom_workflow import ItemBrief, compile_definition
from eom_workflow.models import (
    ArtifactSpec,
    AuthoringRoleResult,
    GeneratedAuthoringRoleResultV4,
    GeneratedItemDraftV4,
    RoleWorkerInput,
    WorkerRequest,
)
from eom_workflow.schemas import (
    WorkflowSchemaError,
    constrained_result_schema,
    load_codex_result_schema,
    load_knowledge_item_brief_schema,
    result_schema_protocol,
    role_schema_bundle_hash,
    validate_role_input,
    validate_role_result,
    validate_schema_message,
)
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError as PydanticValidationError

ROOT = Path(__file__).resolve().parents[2]
ROLES = {"authoring", "image", "review", "item_management"}


def _content() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "locale": "ko-KR",
        "title": "변인 사이의 선형 관계",
        "body": [
            {
                "block_id": "block_stem",
                "type": "paragraph",
                "purpose": "stem",
                "text": "다음 자료를 보고 물음에 답하시오.",
            },
            {
                "block_id": "block_data",
                "type": "table",
                "purpose": "data",
                "caption": "측정 결과",
                "headers": ["시간", "거리", "속력"],
                "rows": [["2", "10", "5"]],
            },
            {
                "block_id": "block_image",
                "type": "image",
                "purpose": "stimulus",
                "artifact": {
                    "artifact_id": "artifact_" + "1" * 32,
                    "artifact_revision_id": "rev_" + "2" * 32,
                    "artifact_member": "eom-question-template-reference-v1.png",
                    "sha256": "sha256:" + "3" * 64,
                    "media_type": "image/png",
                },
                "alt_text": "변인이 증가하는 관계를 나타낸 도식",
                "width_px": 800,
                "height_px": 500,
            },
            {
                "block_id": "block_equation",
                "type": "equation",
                "purpose": "stimulus",
                "notation": "hancom-equation-script",
                "source": "v=d/t",
            },
            {
                "block_id": "block_prompt",
                "type": "paragraph",
                "purpose": "prompt",
                "text": "옳은 것만을 고른 것은?",
            },
            {
                "block_id": "block_claims",
                "type": "statement_set",
                "purpose": "claims",
                "statements": [
                    {"statement_id": "statement_g", "label": "ㄱ", "text": "속력은 5이다."},
                    {
                        "statement_id": "statement_n",
                        "label": "ㄴ",
                        "text": "거리는 시간에 비례한다.",
                    },
                    {
                        "statement_id": "statement_d",
                        "label": "ㄷ",
                        "text": "시간이 4이면 거리는 20이다.",
                    },
                ],
            },
        ],
        "interaction": {
            "type": "single_choice",
            "choices": [
                {"choice_id": "choice_1", "label": "1", "text": "ㄱ"},
                {"choice_id": "choice_2", "label": "2", "text": "ㄴ"},
                {"choice_id": "choice_3", "label": "3", "text": "ㄱ, ㄴ"},
                {"choice_id": "choice_4", "label": "4", "text": "ㄴ, ㄷ"},
                {"choice_id": "choice_5", "label": "5", "text": "ㄱ, ㄴ, ㄷ"},
            ],
        },
        "solution": {
            "correct_choice_ids": ["choice_5"],
            "accepted_answers": [],
            "explanation": "거리와 시간의 비가 5로 일정하다.",
            "authoring_intent": "비례 관계와 속력의 의미를 평가한다.",
            "statement_explanations": [
                {"statement_id": "statement_g", "text": "10/2=5이므로 옳다."},
                {"statement_id": "statement_n", "text": "속력이 일정하므로 옳다."},
                {"statement_id": "statement_d", "text": "5*4=20이므로 옳다."},
            ],
        },
        "score": {"points": 3},
    }


def _worker_input() -> RoleWorkerInput:
    return RoleWorkerInput(
        protocol_version="workflow-role/1.1.0",
        job_id="job_" + "1" * 32,
        workflow_id="workflow_" + "2" * 32,
        step_run_id="steprun_" + "3" * 32,
        attempt=1,
        role="authoring",
        request=WorkerRequest(
            request_name="KNOWLEDGE_ITEM_REQUEST",
            image_mode="required",
        ),
        upstream_artifacts=(),
        artifact=ArtifactSpec(
            logical_artifact_id="artifact_" + "4" * 32,
            revision_id="rev_" + "5" * 32,
        ),
    )


def _generated_authoring_result(worker_input: RoleWorkerInput) -> dict[str, object]:
    content = _content()
    body = content["body"]
    assert isinstance(body, list)
    return {
        "schema_version": "1.0",
        "protocol_version": worker_input.protocol_version,
        "job_id": worker_input.job_id,
        "workflow_id": worker_input.workflow_id,
        "step_run_id": worker_input.step_run_id,
        "role": "authoring",
        "status": "ok",
        "artifact": worker_input.artifact.model_dump(mode="json"),
        "output": {
            "draft": {
                "schema_version": "1.0",
                "locale": "ko-KR",
                "title": content["title"],
                "stem": body[0],
                "data_table": body[1],
                "image_brief": {
                    "kind": "line_graph",
                    "block_id": "block_image",
                    "alt_text": "시간에 따라 거리가 일정하게 증가하는 선그래프",
                    "x_axis_label": "time(s)",
                    "y_axis_label": "distance(m)",
                    "series_label": "object-A",
                    "x_values": [1, 2, 3],
                    "y_values": [5, 10, 15],
                },
                "equation": body[3],
                "prompt": body[4],
                "statements": body[5],
                "interaction": content["interaction"],
                "solution": content["solution"],
                "score": content["score"],
            },
            "metadata": {
                "subject": "일반 과학",
                "topic": "변인 사이의 선형 관계",
                "difficulty": "medium",
                "knowledge_source_mode": "general_model_knowledge",
            },
        },
        "completed_at": datetime(2026, 8, 22, tzinfo=UTC).isoformat(),
    }


def test_knowledge_workflow_and_pack_compile_as_pinned_contracts() -> None:
    definition = compile_definition(
        ROOT / "config/workflows/generic-item-development.v1.2.yaml", ROLES
    )
    pack = compile_pack(ROOT / "content/packs/general-knowledge-item/1.0.0")
    assert definition.definition.definition_version == "1.2.0"
    assert [
        step.result_schema for step in definition.definition.steps if hasattr(step, "result_schema")
    ] == [
        "authoring-result@2.0",
        "image-result@2.0",
        "review-result@2.0",
        "registration-result@2.0",
    ]
    assert pack.manifest.pack.key == "general-knowledge-item"
    assert pack.manifest.provenance.mode == "built_in_general_knowledge"
    assert pack.manifest.provenance.intake_batch_ids == ()
    assert len(pack.profiles) == 4

    generated_definition = compile_definition(
        ROOT / "config/workflows/generic-item-development.v1.3.yaml", ROLES
    )
    generated_pack = compile_pack(ROOT / "content/packs/generated-knowledge-item/1.0.0")
    assert generated_definition.definition.definition_version == "1.3.0"
    assert generated_definition.sha256 == (
        "sha256:0be1c592de2b341461e95876666e7ae60c8391f259ac89caeb61de028b1b5124"
    )
    assert [
        step.result_schema
        for step in generated_definition.definition.steps
        if hasattr(step, "result_schema")
    ] == [
        "authoring-result@3.0",
        "image-result@3.0",
        "review-result@3.0",
        "registration-result@3.0",
    ]
    assert generated_pack.manifest.pack.key == "generated-knowledge-item"
    assert generated_pack.source_tree_sha256 == (
        "sha256:ff2adac399c0b0adfe68fd8fb5206d97eaaf886b011c0d08f23ceb079bd884f1"
    )
    assert generated_pack.manifest.provenance.mode == "built_in_general_knowledge"
    assert generated_pack.manifest.provenance.intake_batch_ids == ()

    generated_v4_definition = compile_definition(
        ROOT / "config/workflows/generic-item-development.v1.4.yaml", ROLES
    )
    generated_v4_pack = compile_pack(ROOT / "content/packs/generated-knowledge-item/1.1.0")
    assert generated_v4_definition.definition.definition_version == "1.4.0"
    assert generated_v4_definition.sha256 == (
        "sha256:3b7c0bc7c16b961cc7b0e63544e32ddab8fd4619027b22cc6b25e4c4f90ef4b8"
    )
    assert [
        step.result_schema
        for step in generated_v4_definition.definition.steps
        if hasattr(step, "result_schema")
    ] == [
        "authoring-result@4.0",
        "image-result@4.0",
        "review-result@4.0",
        "registration-result@4.0",
    ]
    assert generated_v4_pack.manifest.pack.version == "1.1.0"
    assert generated_v4_pack.source_tree_sha256 == (
        "sha256:978f2514f6a88ab2860884eb24e5aa8d6a4ac6f7c3ad4f17b498d57ab2749b16"
    )
    assert generated_v4_pack.manifest.compatibility.workflow_definitions[0].versions == ("1.4.0",)
    assert {profile.output_schema_ref for profile in generated_v4_pack.profiles} == {
        "authoring-result@4.0",
        "image-result@4.0",
        "review-result@4.0",
        "registration-result@4.0",
    }

    generated_v5_definition = compile_definition(
        ROOT / "config/workflows/generic-item-development.v1.5.yaml", ROLES
    )
    generated_v5_pack = compile_pack(ROOT / "content/packs/generated-knowledge-item/1.3.0")
    assert generated_v5_definition.definition.definition_version == "1.5.0"
    assert generated_v5_definition.sha256 == (
        "sha256:96dc577953fb7af5f14a404aed2e92986e4a3ba36318e54432ae36c113cca65d"
    )
    assert [
        step.result_schema
        for step in generated_v5_definition.definition.steps
        if hasattr(step, "result_schema")
    ] == [
        "authoring-result@5.0",
        "image-result@5.0",
        "review-result@5.0",
        "registration-result@5.0",
    ]
    assert generated_v5_pack.manifest.pack.version == "1.3.0"
    assert generated_v5_pack.source_tree_sha256 == (
        "sha256:1a019484e8bbfcfd69f2111c6551ce034e1cd4e811b2b7fe2c710a74dbcd2436"
    )
    assert generated_v5_pack.manifest.compatibility.workflow_definitions[0].versions == ("1.5.0",)
    assert {profile.output_schema_ref for profile in generated_v5_pack.profiles} == {
        "authoring-result@5.0",
        "image-result@5.0",
        "review-result@5.0",
        "registration-result@5.0",
    }

    generated_local_image_pack = compile_pack(ROOT / "content/packs/generated-knowledge-item/1.4.0")
    assert generated_local_image_pack.manifest.pack.version == "1.4.0"
    assert generated_local_image_pack.source_tree_sha256 == (
        "sha256:427a2b2abcdcbf14a6d66e472dd79dd2aaf317c411a08aa0d9bc237d673e9684"
    )
    assert {profile.profile.version for profile in generated_local_image_pack.profiles} == {"5.0.0"}
    assert generated_local_image_pack.manifest.compatibility.workflow_definitions[0].versions == (
        "1.5.0",
    )
    assert generated_local_image_pack.manifest.compatibility.protocol.minimum == "1.12.0"

    generated_v6_definition = compile_definition(
        ROOT / "config/workflows/generic-item-development.v1.6.yaml", ROLES
    )
    generated_image_plan_pack = compile_pack(ROOT / "content/packs/generated-knowledge-item/1.5.0")
    assert generated_v6_definition.definition.definition_version == "1.6.0"
    assert generated_v6_definition.sha256 == (
        "sha256:8881c4f670e0122e0e36387e54e6a98f89706feca6eb8953ada476093be1b3b9"
    )
    assert [
        step.result_schema
        for step in generated_v6_definition.definition.steps
        if hasattr(step, "result_schema")
    ] == [
        "authoring-result@6.0",
        "image-result@6.0",
        "review-result@6.0",
        "registration-result@6.0",
    ]
    assert generated_image_plan_pack.manifest.pack.version == "1.5.0"
    assert generated_image_plan_pack.source_tree_sha256 == (
        "sha256:401a0b5423fa9866b8023e280129bab728069df67b37cf1bbe5c59100d10a42b"
    )
    assert {profile.profile.version for profile in generated_image_plan_pack.profiles} == {"6.0.0"}
    assert generated_image_plan_pack.manifest.compatibility.workflow_definitions[0].versions == (
        "1.6.0",
    )
    assert generated_image_plan_pack.manifest.compatibility.protocol.minimum == "1.13.0"
    assert {profile.output_schema_ref for profile in generated_image_plan_pack.profiles} == {
        "authoring-result@6.0",
        "image-result@6.0",
        "review-result@6.0",
        "registration-result@6.0",
    }

    generated_font_profile_pack = compile_pack(
        ROOT / "content/packs/generated-knowledge-item/1.6.0"
    )
    assert generated_font_profile_pack.manifest.pack.version == "1.6.0"
    assert generated_font_profile_pack.source_tree_sha256 == (
        "sha256:c929c6a2a54fb483e854d70d0857134ad38a775ca3d62da4b60d501db4a91a95"
    )
    assert {profile.profile.version for profile in generated_font_profile_pack.profiles} == {
        "6.0.0"
    }
    assert generated_font_profile_pack.manifest.compatibility.workflow_definitions[0].versions == (
        "1.6.0",
    )
    image_prompt = next(
        value.path.read_text(encoding="utf-8")
        for value in generated_font_profile_pack.files
        if value.relative_path == "prompt-templates/image.md"
    )
    assert "SM JGothic Std" in image_prompt
    assert "Century Old Style" in image_prompt
    assert "DejaVu Serif" in image_prompt
    assert "Droid Sans Fallback" not in image_prompt

    generated_fixed_gpu_style_pack = compile_pack(
        ROOT / "content/packs/generated-knowledge-item/1.7.0"
    )
    assert generated_fixed_gpu_style_pack.manifest.pack.version == "1.7.0"
    assert generated_fixed_gpu_style_pack.source_tree_sha256 == (
        "sha256:3cdc4f3c8c085df7345991cd8e5ac1e86c84758ed47e303303590872ca1806bb"
    )
    assert {profile.profile.version for profile in generated_fixed_gpu_style_pack.profiles} == {
        "6.0.0"
    }
    assert generated_fixed_gpu_style_pack.manifest.compatibility.workflow_definitions[
        0
    ].versions == ("1.6.0",)
    prompt_text = "\n".join(
        value.path.read_text(encoding="utf-8")
        for value in generated_fixed_gpu_style_pack.files
        if value.relative_path.startswith("prompt-templates/")
    )
    assert "결정론적 Python/SVG" in prompt_text
    assert "순백 배경" in prompt_text
    assert "실사" in prompt_text
    assert "대상·자세·배치" in prompt_text

    generated_deterministic_human_pack = compile_pack(
        ROOT / "content/packs/generated-knowledge-item/1.8.0"
    )
    assert generated_deterministic_human_pack.manifest.pack.version == "1.8.0"
    assert generated_deterministic_human_pack.source_tree_sha256 == (
        "sha256:7bf08d9bec5e7ed94dd03d2c211dcd3701a5d12caef17782c8caf68359893060"
    )
    assert {profile.profile.version for profile in generated_deterministic_human_pack.profiles} == {
        "6.0.0"
    }
    assert all(
        "local_image_provider.reviewed_binding_json" in profile.required_context
        for profile in generated_deterministic_human_pack.profiles
        if profile.profile.type in {"authoring", "image", "review"}
    )
    human_policy_text = "\n".join(
        value.path.read_text(encoding="utf-8")
        for value in generated_deterministic_human_pack.files
        if value.relative_path.startswith("prompt-templates/")
    )
    assert "사람 형상은 반드시 익명화한 단순 SVG 선화" in human_policy_text
    assert "현재 비인간 동물에만 사용한다" in human_policy_text

    generated_json_safe_pack = compile_pack(ROOT / "content/packs/generated-knowledge-item/1.9.0")
    assert generated_json_safe_pack.manifest.pack.version == "1.9.0"
    assert generated_json_safe_pack.source_tree_sha256 == (
        "sha256:7726ad91d01b8e7a2c489d8312cdbf770ea7deb7da2e80d412ffc632e2e265d7"
    )
    authoring_profile = next(
        profile
        for profile in generated_json_safe_pack.profiles
        if profile.profile.type == "authoring"
    )
    assert authoring_profile.profile.version == "6.1.0"
    authoring_prompt = next(
        value.path.read_text(encoding="utf-8")
        for value in generated_json_safe_pack.files
        if value.relative_path == "prompt-templates/authoring.md"
    )
    assert "모든 값은 반드시\n-1000 이상 1000 이하" in authoring_prompt
    assert "결과 JSON 바이트에는 `\\\\frac`" in authoring_prompt

    generated_print_safe_pack = compile_pack(ROOT / "content/packs/generated-knowledge-item/1.10.0")
    assert generated_print_safe_pack.manifest.pack.version == "1.10.0"
    assert generated_print_safe_pack.source_tree_sha256 == (
        "sha256:0e4e66e36e48ed2fbbd4e6f3443af20a22a4c1a5643897a0f36acaaec35fa6d5"
    )
    authoring_profile = next(
        profile
        for profile in generated_print_safe_pack.profiles
        if profile.profile.type == "authoring"
    )
    review_profile = next(
        profile
        for profile in generated_print_safe_pack.profiles
        if profile.profile.type == "review"
    )
    assert authoring_profile.profile.version == "6.2.0"
    assert review_profile.profile.version == "6.1.0"
    prompts = {
        value.relative_path: value.path.read_text(encoding="utf-8")
        for value in generated_print_safe_pack.files
        if value.relative_path.startswith("prompt-templates/")
    }
    assert "kind=`diagram`" in prompts["prompt-templates/authoring.md"]
    assert "`F (10^3 N)`" in prompts["prompt-templates/authoring.md"]
    assert "raw HwpQuestionEditor Markdown" in prompts["prompt-templates/review.md"]
    assert "그 자체로 blocking 사유가 아니" in prompts["prompt-templates/review.md"]

    generated_editorial_prompt_pack = compile_pack(
        ROOT / "content/packs/generated-knowledge-item/1.11.0"
    )
    assert generated_editorial_prompt_pack.manifest.pack.version == "1.11.0"
    assert generated_editorial_prompt_pack.source_tree_sha256 == (
        "sha256:4209b96b6ee7108ef2d4cc1b6c7e6e4c672964413b74e18cf816c2f1081bac53"
    )
    profiles = {
        profile.profile.type: profile.profile.version
        for profile in generated_editorial_prompt_pack.profiles
    }
    assert profiles["authoring"] == "6.3.0"
    assert profiles["review"] == "6.2.0"
    prompts = {
        value.relative_path: value.path.read_text(encoding="utf-8")
        for value in generated_editorial_prompt_pack.files
        if value.relative_path.startswith("prompt-templates/")
    }
    assert "kind=`diagram`" in prompts["prompt-templates/authoring.md"]
    assert "raw HwpQuestionEditor Markdown" in prompts["prompt-templates/review.md"]


def test_content_pack_provenance_never_fakes_a_source_pointer() -> None:
    pack_path = ROOT / "content/packs/general-knowledge-item/1.0.0/pack.yaml"
    raw = yaml.safe_load(pack_path.read_text(encoding="utf-8"))
    validate_contract("content-pack-v2", raw)
    assert ContentPackManifest.model_validate(raw).provenance.intake_batch_ids == ()

    false_external = json.loads(json.dumps(raw))
    false_external["provenance"]["intake_batch_ids"] = ["intake_" + "1" * 32]
    with pytest.raises(PydanticValidationError):
        ContentPackManifest.model_validate(false_external)
    with pytest.raises(JsonSchemaValidationError):
        validate_contract("content-pack-v2", false_external)

    source_claim_without_pointers = json.loads(json.dumps(raw))
    source_claim_without_pointers["provenance"]["mode"] = "manual_external_source"
    with pytest.raises(PydanticValidationError):
        ContentPackManifest.model_validate(source_claim_without_pointers)
    with pytest.raises(JsonSchemaValidationError):
        validate_contract("content-pack-v2", source_claim_without_pointers)


def test_knowledge_brief_is_schema_first_and_template_bounded() -> None:
    brief = ItemBrief(
        subject="일반 과학",
        topic="변인 사이의 선형 관계",
        task_type="data_interpretation",
        difficulty="medium",
        quality_profile="balanced",
        original_request_sha256="0" * 64,
    )
    validate_schema_message(
        load_knowledge_item_brief_schema(), brief.model_dump(mode="json"), "knowledge-brief"
    )
    content = AssessmentItemContent.model_validate(_content())
    assert validate_eom_question_template_content(content) == content


def test_authoring_v2_result_is_self_contained_and_typed() -> None:
    worker_input = _worker_input()
    validate_role_input(worker_input.model_dump(mode="json"), "authoring", "workflow-role/1.1.0")
    result = {
        "schema_version": "1.0",
        "protocol_version": "workflow-role/1.1.0",
        "job_id": worker_input.job_id,
        "workflow_id": worker_input.workflow_id,
        "step_run_id": worker_input.step_run_id,
        "role": "authoring",
        "status": "ok",
        "artifact": worker_input.artifact.model_dump(mode="json"),
        "output": {
            "content": _content(),
            "metadata": {
                "subject": "일반 과학",
                "topic": "변인 사이의 선형 관계",
                "difficulty": "medium",
                "knowledge_source_mode": "general_model_knowledge",
            },
        },
        "completed_at": datetime(2026, 8, 22, tzinfo=UTC).isoformat(),
    }
    constrained = constrained_result_schema("authoring-result@2.0", worker_input)
    assert '"$ref": "eom://schemas/item-registry' not in json.dumps(constrained)
    parsed = validate_role_result(result, "authoring", "authoring-result@2.0")
    assert parsed.output.content.title == "변인 사이의 선형 관계"  # type: ignore[union-attr]

    invalid = _content()
    body = invalid["body"]
    assert isinstance(body, list) and isinstance(body[2], dict)
    body[2]["width_px"] = 799
    result["output"]["content"] = invalid  # type: ignore[index]
    with pytest.raises(ValueError):
        validate_role_result(result, "authoring", "authoring-result@2.0")


def test_knowledge_authoring_codex_projection_preserves_template_bounds() -> None:
    projected = load_codex_result_schema("authoring-result@2.0")
    encoded = json.dumps(projected, ensure_ascii=False)
    assert all(
        keyword not in encoded
        for keyword in (
            '"allOf"',
            '"oneOf"',
            '"prefixItems"',
            '"minLength"',
            '"maxLength"',
            '"uniqueItems"',
        )
    )
    content = projected["properties"]["output"]["properties"]["content"]
    assert content["properties"]["locale"] == {"type": "string", "const": "ko-KR"}
    assert content["properties"]["body"]["minItems"] == 6
    assert content["properties"]["body"]["maxItems"] == 6
    definitions = projected["$defs"]
    assert definitions["item_tableBlock"]["properties"]["purpose"]["const"] == "data"
    assert definitions["item_imageBlock"]["properties"]["width_px"]["const"] == 800
    assert definitions["item_imageBlock"]["properties"]["height_px"]["const"] == 500
    assert definitions["item_equationBlock"]["properties"]["notation"]["const"] == (
        "hancom-equation-script"
    )
    assert definitions["item_singleChoice"]["properties"]["choices"]["minItems"] == 5
    assert definitions["item_singleChoice"]["properties"]["choices"]["maxItems"] == 5
    assert definitions["item_score"]["properties"]["points"]["enum"] == [2, 3]


def test_protocol_versions_preserve_legacy_hash_and_isolate_v2() -> None:
    assert result_schema_protocol("authoring-result@1.0") == "workflow-role/1.0.1"
    assert result_schema_protocol("authoring-result@2.0") == "workflow-role/1.1.0"
    assert role_schema_bundle_hash("workflow-role/1.0.1") == (
        "sha256:6fff452bb8c39ed8bc98487c29ad8f7f68e0b152181849a007c7f7eec56636a7"
    )
    assert role_schema_bundle_hash("workflow-role/1.1.0") != role_schema_bundle_hash(
        "workflow-role/1.0.1"
    )
    assert result_schema_protocol("authoring-result@3.0") == "workflow-role/1.2.0"
    assert role_schema_bundle_hash("workflow-role/1.2.0") == (
        "sha256:09c325824484d1bbcb46e14fa3007aa2b51f9750235a1969dee67b2b795d60f4"
    )
    assert result_schema_protocol("authoring-result@4.0") == "workflow-role/1.3.0"
    assert role_schema_bundle_hash("workflow-role/1.3.0") == (
        "sha256:dce3e0921cf2d0d236f813101406286cb86cabaef07c95030f05028fad664ab8"
    )


def test_generated_v3_schema_resources_remain_historically_immutable() -> None:
    expected = {
        "authoring-result-v3.schema.json": (
            "c49ca324ec4ba487cf93062d835953c82074ee1a49e751560bc28570e9d5f1c5"
        ),
        "image-result-v3.schema.json": (
            "5f7c809b60df94b6b817d351af8a1506f27294dca2a7c161d9cfd5d9bf728231"
        ),
        "review-result-v3.schema.json": (
            "81f6a8536d947d816d67c21d6f2deb686096ea5f6cd0e2f2ee3a03fd129241c0"
        ),
        "registration-result-v3.schema.json": (
            "7cb6fc5f3c4a5dfc154c9c1316051ed8727825303e3ca5c4a74463df9a8baeb6"
        ),
    }
    for file_name, digest in expected.items():
        canonical = ROOT / "schemas/workflow/roles" / file_name
        packaged = ROOT / "packages/workflow/eom_workflow/resources/roles" / file_name
        assert sha256(canonical.read_bytes()).hexdigest() == digest
        assert packaged.read_bytes() == canonical.read_bytes()


def test_generated_authoring_result_is_a_draft_without_a_fake_media_pointer() -> None:
    worker_input = _worker_input().model_copy(
        update={
            "protocol_version": "workflow-role/1.2.0",
            "request": WorkerRequest(
                request_name="GENERATED_KNOWLEDGE_ITEM_REQUEST",
                image_mode="required",
            ),
        }
    )
    content = _content()
    body = content["body"]
    assert isinstance(body, list)
    result = {
        "schema_version": "1.0",
        "protocol_version": "workflow-role/1.2.0",
        "job_id": worker_input.job_id,
        "workflow_id": worker_input.workflow_id,
        "step_run_id": worker_input.step_run_id,
        "role": "authoring",
        "status": "ok",
        "artifact": worker_input.artifact.model_dump(mode="json"),
        "output": {
            "draft": {
                "schema_version": "1.0",
                "locale": "ko-KR",
                "title": content["title"],
                "stem": body[0],
                "data_table": body[1],
                "image_brief": {
                    "kind": "line_graph",
                    "block_id": "block_image",
                    "alt_text": "시간에 따라 거리가 일정하게 증가하는 선그래프",
                    "x_axis_label": "time(s)",
                    "y_axis_label": "distance(m)",
                    "series_label": "object-A",
                    "x_values": [1, 2, 3],
                    "y_values": [5, 10, 15],
                },
                "equation": body[3],
                "prompt": body[4],
                "statements": body[5],
                "interaction": content["interaction"],
                "solution": content["solution"],
                "score": content["score"],
            },
            "metadata": {
                "subject": "일반 과학",
                "topic": "변인 사이의 선형 관계",
                "difficulty": "medium",
                "knowledge_source_mode": "general_model_knowledge",
            },
        },
        "completed_at": datetime(2026, 8, 22, tzinfo=UTC).isoformat(),
    }
    constrained = constrained_result_schema("authoring-result@3.0", worker_input)
    validate_schema_message(constrained, result, "generated-authoring")
    parsed = validate_role_result(result, "authoring", "authoring-result@3.0")
    assert parsed.output.draft.image_brief.x_values == (1, 2, 3)  # type: ignore[union-attr]
    assert "artifact" not in result["output"]["draft"]["image_brief"]  # type: ignore[index]

    historical_result = json.loads(json.dumps(result))
    historical_result["output"]["draft"]["solution"]["accepted_answers"] = ["5 N"]
    historical = validate_role_result(historical_result, "authoring", "authoring-result@3.0")
    assert historical.output.draft.solution.accepted_answers == ("5 N",)  # type: ignore[union-attr]

    projected = load_codex_result_schema("authoring-result@3.0")
    definitions = projected["$defs"]
    draft = definitions["GeneratedItemDraft"]["properties"]
    assert draft["data_table"]["$ref"].endswith("/TableBlock")
    assert definitions["GeneratedImageBrief"]["properties"]["kind"]["const"] == "line_graph"
    assert definitions["GeneratedImageBrief"]["properties"]["x_values"]["minItems"] == 2
    assert definitions["SingleChoiceInteraction"]["properties"]["choices"]["minItems"] == 5
    assert definitions["SingleChoiceInteraction"]["properties"]["choices"]["maxItems"] == 5


def test_generated_authoring_v4_closes_the_canonical_item_reference_contract() -> None:
    worker_input = _worker_input().model_copy(
        update={
            "protocol_version": "workflow-role/1.3.0",
            "request": WorkerRequest(
                request_name="GENERATED_KNOWLEDGE_ITEM_REQUEST",
                image_mode="required",
            ),
        }
    )
    result = _generated_authoring_result(worker_input)
    constrained = constrained_result_schema("authoring-result@4.0", worker_input)
    validate_schema_message(constrained, result, "generated-authoring-v4")
    parsed = validate_role_result(result, "authoring", "authoring-result@4.0")
    assert parsed.protocol_version == "workflow-role/1.3.0"

    projected = load_codex_result_schema("authoring-result@4.0")
    solution_schema = projected["$defs"]["ItemSolution"]["properties"]
    assert solution_schema["correct_choice_ids"]["minItems"] == 1
    assert solution_schema["correct_choice_ids"]["maxItems"] == 1
    assert solution_schema["accepted_answers"]["maxItems"] == 0
    assert solution_schema["statement_explanations"]["minItems"] == 3
    assert solution_schema["statement_explanations"]["maxItems"] == 3

    for correct_choice_ids in ([], ["choice_1", "choice_2"]):
        wrong_cardinality = json.loads(json.dumps(result))
        wrong_cardinality["output"]["draft"]["solution"]["correct_choice_ids"] = correct_choice_ids
        with pytest.raises(WorkflowSchemaError, match="correct_choice_ids"):
            validate_role_result(wrong_cardinality, "authoring", "authoring-result@4.0")

    accepted_text_answer = json.loads(json.dumps(result))
    accepted_text_answer["output"]["draft"]["solution"]["accepted_answers"] = ["5 N"]
    with pytest.raises(WorkflowSchemaError, match="accepted_answers"):
        validate_role_result(accepted_text_answer, "authoring", "authoring-result@4.0")

    unresolved_choice = json.loads(json.dumps(result))["output"]["draft"]
    unresolved_choice["solution"]["correct_choice_ids"] = ["choice_missing"]
    with pytest.raises(PydanticValidationError, match="correct choice pointer does not resolve"):
        GeneratedItemDraftV4.model_validate(unresolved_choice)

    duplicate_block = json.loads(json.dumps(result))["output"]["draft"]
    duplicate_block["prompt"]["block_id"] = duplicate_block["stem"]["block_id"]
    with pytest.raises(PydanticValidationError, match="block IDs must be unique"):
        GeneratedItemDraftV4.model_validate(duplicate_block)

    incomplete_explanations = json.loads(json.dumps(result))["output"]["draft"]
    incomplete_explanations["solution"]["statement_explanations"] = incomplete_explanations[
        "solution"
    ]["statement_explanations"][:2]
    with pytest.raises(
        PydanticValidationError,
        match="statement explanations must exactly cover statement IDs",
    ):
        GeneratedItemDraftV4.model_validate(incomplete_explanations)

    wrong_explanation_pointer = json.loads(json.dumps(result))["output"]["draft"]
    wrong_explanation_pointer["solution"]["statement_explanations"][2]["statement_id"] = (
        "statement_x"
    )
    with pytest.raises(
        PydanticValidationError,
        match="statement explanations must exactly cover statement IDs",
    ):
        GeneratedItemDraftV4.model_validate(wrong_explanation_pointer)


def test_typed_role_results_retain_exact_protocol_identity() -> None:
    worker_input = _worker_input()
    legacy = {
        "schema_version": "1.0",
        "protocol_version": "workflow-role/1.3.0",
        "job_id": worker_input.job_id,
        "workflow_id": worker_input.workflow_id,
        "step_run_id": worker_input.step_run_id,
        "role": "authoring",
        "status": "ok",
        "artifact": worker_input.artifact.model_dump(mode="json"),
        "output": {
            "draft": {"title": "PLACEHOLDER_CONTENT", "body": "PLACEHOLDER_CONTENT"},
            "metadata": {"domain": "placeholder"},
        },
        "completed_at": datetime(2026, 8, 22, tzinfo=UTC).isoformat(),
    }
    with pytest.raises(PydanticValidationError, match="protocol_version"):
        AuthoringRoleResult.model_validate(legacy)

    generated = _generated_authoring_result(
        worker_input.model_copy(update={"protocol_version": "workflow-role/1.3.0"})
    )
    assert GeneratedAuthoringRoleResultV4.model_validate(generated).protocol_version == (
        "workflow-role/1.3.0"
    )
