from __future__ import annotations

import json
from datetime import UTC, datetime
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
from eom_workflow.models import ArtifactSpec, RoleWorkerInput, WorkerRequest
from eom_workflow.schemas import (
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
    assert generated_pack.manifest.provenance.mode == "built_in_general_knowledge"
    assert generated_pack.manifest.provenance.intake_batch_ids == ()


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

    projected = load_codex_result_schema("authoring-result@3.0")
    definitions = projected["$defs"]
    draft = definitions["GeneratedItemDraft"]["properties"]
    assert draft["data_table"]["$ref"].endswith("/TableBlock")
    assert definitions["GeneratedImageBrief"]["properties"]["kind"]["const"] == "line_graph"
    assert definitions["GeneratedImageBrief"]["properties"]["x_values"]["minItems"] == 2
    assert definitions["SingleChoiceInteraction"]["properties"]["choices"]["minItems"] == 5
    assert definitions["SingleChoiceInteraction"]["properties"]["choices"]["maxItems"] == 5
