from __future__ import annotations

import hashlib
import inspect
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from eom_api.services.mock_exam_production_coordinator import (
    MockExamProductionCoordinatorError,
    _require_assembly_manifest_family,
)
from eom_api_contracts import MockExamAssemblyViewV2, MockExamAssemblyViewV3
from eom_catalog_contracts import (
    AssessmentItemContentV3,
    MockExamMaterialProfile,
    MockExamProductionPlanV2,
    build_integrated_science_mock_exam_production_plan,
    build_integrated_science_mock_exam_production_plan_v2,
    catalog_application_schema_route,
    load_integrated_science_editorial_outline,
    load_integrated_science_mock_exam_layout_policy,
    load_integrated_science_mock_exam_policy,
    validate_content_team_mock_exam_slot_output,
    validate_content_team_mock_exam_slot_output_v2,
)
from eom_catalog_contracts import (
    validate_contract as validate_catalog_contract,
)
from eom_catalog_service.content_pack_files import compile_pack
from eom_hwpx_contracts import (
    ContentTeamImageSlot,
    ContentTeamTable,
    parse_content_team_markdown_v2,
    serialize_content_team_markdown,
)
from eom_identifiers import content_sha256
from eom_orchestrator.orchestrator import Orchestrator
from eom_workflow import compile_definition
from eom_workflow.models import (
    CONTENT_TEAM_ILLUSTRATION_PROMPT_PREFIX,
    ArtifactSpec,
    ContentTeamAuthoringRoleResultV9,
    ContentTeamImageRoleResultV9,
    ContentTeamMockExamSlotV1,
    ContentTeamRegistrationRoleResultV9,
    ContentTeamReviewRoleResultV9,
)
from eom_workflow.schemas import (
    load_codex_result_schema,
    load_role_input_schema,
    load_role_result_schema,
    role_schema_bundle_hash,
    validate_role_result,
)
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError

ROOT = Path(__file__).resolve().parents[2]
ROLES = {"authoring", "image", "review", "item_management"}


def _content_v3(
    score_display: str = "1.5",
    *,
    visuals: tuple[ContentTeamImageSlot | ContentTeamTable, ...] = (),
    visual_layout: str = "NONE",
) -> AssessmentItemContentV3:
    return AssessmentItemContentV3.model_validate(
        {
            "item_number": 1,
            "score_display": score_display,
            "stem": "주어진 정보를 해석하여 물음에 답하시오.",
            "bottom_stem": "이에 대한 설명으로 알맞은 것은?",
            "inquiry": None,
            "labeled_blocks": [],
            "visuals": [visual.model_dump(mode="json") for visual in visuals],
            "visual_layout": visual_layout,
            "statements": [],
            "choices": [
                {"number": "①", "text": "첫 번째 설명"},
                {"number": "②", "text": "두 번째 설명"},
                {"number": "③", "text": "세 번째 설명"},
                {"number": "④", "text": "네 번째 설명"},
                {"number": "⑤", "text": "다섯 번째 설명"},
            ],
            "answer": {
                "answer_kind": "DIRECT_CHOICE",
                "number": "②",
                "statement_labels": [],
                "answer_content": "두 번째 설명",
                "raw_line": "정답 : ② (두 번째 설명)",
            },
            "explanations": {
                "authoring_intent": "제시된 정보의 관계를 확인한다.",
                "concept_source": "요청에 결속된 권위 근거를 사용한다.",
                "correct_answer": "두 번째 설명이 제시된 정보와 일치한다.",
                "wrong_answer": "나머지 설명은 제시된 정보와 일치하지 않는다.",
            },
            "equation_sources": [],
        }
    )


def _slot(
    points_milli: int,
    *,
    preferred_material_profiles: tuple[MockExamMaterialProfile, ...] = ("TEXT",),
) -> ContentTeamMockExamSlotV1:
    value = {
        "schema_version": "mock-exam-slot/1.0",
        "assembly_policy_revision_id": "assemblypolicyrev_" + "1" * 32,
        "assembly_policy_sha256": "sha256:" + "2" * 64,
        "layout_policy_revision_id": "layoutpolicyrev_" + "3" * 32,
        "layout_policy_sha256": "sha256:" + "4" * 64,
        "slot_id": "slot-01",
        "position": 1,
        "points_milli": points_milli,
        "coverage_role": "BALANCE",
        "coverage_requirement_id": None,
        "balance_large_unit_key": "eom.is.large.1",
        "curriculum_selected_unit_key": "eom.is.middle.1-1",
        "large_unit_key": "eom.is.large.1",
        "inquiry_required": False,
        "preferred_difficulty": "MEDIUM",
        "preferred_material_profiles": list(preferred_material_profiles),
    }
    return ContentTeamMockExamSlotV1.model_validate({**value, "slot_sha256": content_sha256(value)})


def _envelope(role: str, *, seed: int) -> dict[str, object]:
    return {
        "job_id": "job_" + f"{seed:032x}",
        "workflow_id": "workflow_" + "2" * 32,
        "step_run_id": "steprun_" + f"{seed + 20:032x}",
        "role": role,
        "artifact": ArtifactSpec(
            logical_artifact_id="artifact_" + f"{seed + 40:032x}",
            revision_id="rev_" + f"{seed + 60:032x}",
        ),
        "completed_at": datetime(2026, 9, 8, seed, tzinfo=UTC),
    }


def _authoring_result(
    *, visuals: tuple[ContentTeamImageSlot | ContentTeamTable, ...] = (), layout: str = "NONE"
) -> ContentTeamAuthoringRoleResultV9:
    return ContentTeamAuthoringRoleResultV9(
        **_envelope("authoring", seed=1),
        output={
            "draft": _content_v3(visuals=visuals, visual_layout=layout),
            "metadata": {
                "subject": "통합과학",
                "topic": "요청으로 정해지는 주제",
                "difficulty": "medium",
                "knowledge_source_mode": "graph_grounded",
            },
        },
    )


def _image_result() -> ContentTeamImageRoleResultV9:
    prompt = CONTENT_TEAM_ILLUSTRATION_PROMPT_PREFIX + "\nA와 B의 관계만 선화로 표현한다."
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="500" '
        'viewBox="0 0 800 500"><line x1="100" y1="250" x2="700" y2="250" '
        'stroke="#000000" stroke-width="4"></line><text x="120" y="220" '
        'fill="#000000" font-family="Century Old Style" font-size="24">A</text>'
        '<text x="650" y="220" fill="#000000" font-family="Century Old Style" '
        'font-size="24">B</text></svg>'
    )
    return ContentTeamImageRoleResultV9(
        **_envelope("image", seed=2),
        output={
            "drawings": [
                {
                    "visual_ordinal": 0,
                    "label": "",
                    "illustration_prompt": prompt,
                    "drawing": {
                        "kind": "apparatus",
                        "production_route": "DETERMINISTIC_SVG",
                        "route_reason": "SCIENTIFIC_SCHEMATIC",
                        "background_style": "WHITE",
                        "alt_text": "A와 B의 관계를 나타낸 선화",
                        "scene_description": "요청된 두 대상과 관계만 배치한다.",
                        "scientific_constraints": ["표시된 관계를 바꾸지 않는다."],
                        "required_labels": ["A", "B"],
                        "generation_prompt": None,
                        "negative_prompt": None,
                        "svg_overlay": svg,
                    },
                }
            ],
            "summary": "요청된 그림 슬롯 하나를 보존했다.",
        },
    )


@pytest.mark.parametrize("score_display", ["1.5", "2", "2.5", "3"])
def test_v3_score_is_schema_valid_and_markdown_round_trips_exactly(
    score_display: str,
) -> None:
    content = _content_v3(score_display)
    validate_catalog_contract("assessment-item-content-v3", content.model_dump(mode="json"))

    markdown = serialize_content_team_markdown(content)
    reparsed = parse_content_team_markdown_v2(markdown)

    assert reparsed.score_display == score_display
    assert serialize_content_team_markdown(reparsed) == markdown
    assert markdown.decode("utf-8").count(f"[{score_display}점]") == 1


@pytest.mark.parametrize(
    ("visuals", "layout"),
    [
        ((), "NONE"),
        ((ContentTeamImageSlot(),), "IMAGE_ONLY"),
        (
            (
                ContentTeamTable(
                    headers=("구분", "값"),
                    rows=(("A", "1"),),
                    alignments=("default", "right"),
                ),
            ),
            "TABLE_ONLY",
        ),
        (
            (ContentTeamImageSlot(label="(가)"), ContentTeamImageSlot(label="(나)")),
            "IMAGE_IMAGE",
        ),
    ],
)
def test_v3_authoring_preserves_zero_or_variable_visuals(
    visuals: tuple[ContentTeamImageSlot | ContentTeamTable, ...], layout: str
) -> None:
    result = _authoring_result(visuals=visuals, layout=layout)

    parsed = validate_role_result(
        result.model_dump(mode="json"), "authoring", "authoring-result@9.0"
    )

    assert isinstance(parsed, ContentTeamAuthoringRoleResultV9)
    assert parsed.output.draft.visuals == visuals


@pytest.mark.parametrize(
    ("points_milli", "score_display"),
    [(1500, "1.5"), (2000, "2"), (2500, "2.5"), (3000, "3")],
)
def test_v3_slot_validator_binds_exact_source_and_final_score(
    points_milli: int, score_display: str
) -> None:
    slot = _slot(points_milli)
    content = _content_v3(score_display)

    assert (
        validate_content_team_mock_exam_slot_output_v2(
            slot=slot,
            content=content,
            authoring_difficulty="medium",
        )
        == "TEXT"
    )
    wrong = "2" if score_display != "2" else "3"
    with pytest.raises(ValueError, match="score"):
        validate_content_team_mock_exam_slot_output_v2(
            slot=slot,
            content=_content_v3(wrong),
            authoring_difficulty="medium",
        )


def test_v3_slot_validator_rejects_an_allowed_nonprimary_material_substitution() -> None:
    table = ContentTeamTable(
        headers=("구분", "값"),
        rows=(("A", "1"),),
        alignments=("default", "right"),
    )
    content = _content_v3(visuals=(table,), visual_layout="TABLE_ONLY")
    slot = _slot(1500, preferred_material_profiles=("TEXT", "TABLE"))

    assert (
        validate_content_team_mock_exam_slot_output(
            slot=slot,
            content=content,
            authoring_difficulty="medium",
        )
        == "TABLE"
    )
    with pytest.raises(ValueError, match="exact primary"):
        validate_content_team_mock_exam_slot_output_v2(
            slot=slot,
            content=content,
            authoring_difficulty="medium",
        )


def test_workflow_role_119_has_exact_inputs_all_four_v9_outputs_and_bundle_hash() -> None:
    compiled = compile_definition(
        ROOT / "config/workflows/generic-item-development.v1.9.yaml", ROLES
    )
    assert compiled.sha256 == (
        "sha256:698a800f7d02e1974833f290bf14e6b823477d8ea0b62d5d1ee069a71824eed6"
    )
    assert role_schema_bundle_hash("workflow-role/1.19.0") == (
        "sha256:4074b06eea595f8dcfbee29c902d16cd0a97bd593963cc474640df0b90c33c6c"
    )
    for role in ROLES:
        schema = load_role_input_schema(role, "workflow-role/1.19.0")
        assert schema["properties"]["protocol_version"]["const"] == "workflow-role/1.19.0"
        assert (
            schema["$defs"]["request"]["properties"]["request_name"]["const"]
            == "GENERATED_KNOWLEDGE_ITEM_REQUEST"
        )

    results = (
        ("authoring", "authoring-result@9.0", _authoring_result()),
        ("image", "image-result@9.0", _image_result()),
        (
            "review",
            "review-result@9.0",
            ContentTeamReviewRoleResultV9(
                **_envelope("review", seed=3),
                output={
                    "review": {
                        "decision": "ready_for_human",
                        "findings": [],
                        "summary": "배점과 권위 근거가 핀된 요청과 일치한다.",
                    }
                },
            ),
        ),
        (
            "item_management",
            "registration-result@9.0",
            ContentTeamRegistrationRoleResultV9(
                **_envelope("item_management", seed=4),
                output={
                    "registration": {
                        "result": "ready_for_registration",
                        "summary": "검증된 V3 문항 포인터를 등록할 준비가 되었다.",
                    }
                },
            ),
        ),
    )
    for role, schema_id, result in results:
        schema = load_role_result_schema(schema_id)
        Draft202012Validator(schema).validate(result.model_dump(mode="json"))
        assert validate_role_result(result.model_dump(mode="json"), role, schema_id) == result


def test_workflow_role_120_schema_bundle_hash_is_immutable() -> None:
    assert role_schema_bundle_hash("workflow-role/1.20.0") == (
        "sha256:4fe0172ef46c490ccb9c82aa7360c12c1a52c0f2644757190236b9c81fcb459c"
    )


def test_v9_unsafe_svg_is_rejected_by_schema_and_typed_acceptance() -> None:
    unsafe = _image_result().model_dump(mode="json")
    unsafe["output"]["drawings"][0]["drawing"]["svg_overlay"] = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="500" '
        'viewBox="0 0 800 500"><linearGradient id="g"></linearGradient>'
        '<rect x="0" y="0" width="800" height="500" fill="url(#g)"></rect>'
        '<text x="20" y="20" font-family="Century Old Style">A B</text></svg>'
    )
    schema = load_role_result_schema("image-result@9.0")

    with pytest.raises(JsonSchemaValidationError):
        Draft202012Validator(schema).validate(unsafe)
    with pytest.raises(ValueError, match="forbidden"):
        ContentTeamImageRoleResultV9.model_validate(unsafe)
    with pytest.raises(ValueError):
        validate_role_result(unsafe, "image", "image-result@9.0")

    projected = load_codex_result_schema("image-result@9.0")
    projected_svg = projected["$defs"]["GeneratedVectorDrawingV9"]["properties"]["svg_overlay"]
    assert "not" not in projected_svg

    acceptance_source = inspect.getsource(Orchestrator.submit_workflow_role)
    validation_offset = acceptance_source.index("result = validate_role_result(")
    assert validation_offset < acceptance_source.index("commit_file_set_artifact(")
    assert validation_offset < acceptance_source.index("commit_artifact(")


def test_every_v3_json_schema_has_a_byte_exact_canonical_and_packaged_mirror() -> None:
    schema_pairs = (
        (
            "schemas/item-registry/assessment-item-content-v3.schema.json",
            "packages/catalog_contracts/eom_catalog_contracts/resources/item-registry/"
            "assessment-item-content-v3.schema.json",
        ),
        (
            "schemas/assessment-assembly/mock-exam-production-plan-v2.schema.json",
            "packages/catalog_contracts/eom_catalog_contracts/resources/assessment-assembly/"
            "mock-exam-production-plan-v2.schema.json",
        ),
        (
            "schemas/assessment-assembly/mock-exam-assembly-plan-v2.schema.json",
            "packages/catalog_contracts/eom_catalog_contracts/resources/assessment-assembly/"
            "mock-exam-assembly-plan-v2.schema.json",
        ),
        (
            "schemas/assessment-assembly/mock-exam-assembly-manifest-v3.schema.json",
            "packages/catalog_contracts/eom_catalog_contracts/resources/assessment-assembly/"
            "mock-exam-assembly-manifest-v3.schema.json",
        ),
        *(
            (
                f"schemas/assessment-assembly/{name}",
                "packages/catalog_contracts/eom_catalog_contracts/resources/"
                f"assessment-assembly/{name}",
            )
            for name in (
                "mock-exam-item-review-decision-v2.schema.json",
                "mock-exam-item-review-publication-result-v2.schema.json",
                "mock-exam-review-eligibility-result-v2.schema.json",
            )
        ),
        *(
            (
                f"schemas/workflow/roles/{role}-result-v9.schema.json",
                f"packages/workflow/eom_workflow/resources/roles/{role}-result-v9.schema.json",
            )
            for role in ("authoring", "image", "review", "registration")
        ),
        *(
            (
                f"schemas/hwpx/{name}",
                f"packages/hwpx_contracts/eom_hwpx_contracts/schemas/{name}",
            )
            for name in (
                "hwpx-content-team-editorial-question-v2.schema.json",
                "hwpx-content-team-render-request-v3.schema.json",
                "hwpx-content-team-build-result-v3.schema.json",
                "hwpx-content-team-exam-render-request-v3.schema.json",
                "hwpx-content-team-exam-build-result-v3.schema.json",
            )
        ),
    )
    for canonical_name, packaged_name in schema_pairs:
        canonical = ROOT / canonical_name
        packaged = ROOT / packaged_name
        assert canonical.read_bytes() == packaged.read_bytes()
        schema = json.loads(canonical.read_text(encoding="utf-8"))
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        Draft202012Validator.check_schema(schema)

    for version in (10, 12):
        for kind in ("request", "response"):
            name = f"catalog-application-{kind}-v{version}.schema.json"
            assert (ROOT / "schemas/catalog-application" / name).read_bytes() == (
                ROOT
                / "packages/catalog_contracts/eom_catalog_contracts/resources/catalog-application"
                / name
            ).read_bytes()


def test_catalog_application_v10_is_pinned_and_v12_carries_v3_additively() -> None:
    historical_hashes = {
        "catalog-application-request-v10.schema.json": (
            "fc89d31db0aa51d97c991187b5553f82954b497d5cbebc8edc54b908b1484366"
        ),
        "catalog-application-response-v10.schema.json": (
            "d24f2d2ca3fb3fd593f087c3658d17be45d00863df94ff8b6ada867ba0d92308"
        ),
    }
    for name, expected_sha256 in historical_hashes.items():
        assert (
            hashlib.sha256((ROOT / "schemas/catalog-application" / name).read_bytes()).hexdigest()
            == expected_sha256
        )

    content = _content_v3().model_dump(mode="json")
    request = {
        "operation": "IMPORT_REVIEWED_ITEM_CONTENT",
        "base_revision_id": "itemrev_" + "1" * 32,
        "expected_version": 1,
        "reviewed_by": "operator_test_admin",
        "review_reason": "검토된 V3 문항의 정확한 콘텐츠 포인터를 승인합니다.",
        "content": content,
    }
    response = {"status": "OK", "operation": "GET_ITEM_CONTENT", "content": content}
    with pytest.raises(JsonSchemaValidationError):
        validate_catalog_contract("catalog-application-request-v10", request)
    with pytest.raises(JsonSchemaValidationError):
        validate_catalog_contract("catalog-application-response-v10", response)
    validate_catalog_contract("catalog-application-request-v12", request)
    validate_catalog_contract("catalog-application-response-v12", response)

    historical = catalog_application_schema_route("GET_ITEM_CONTENT")
    successor = catalog_application_schema_route(
        "GET_ITEM_CONTENT",
        content_schema_version="3.0",
    )
    review_successor = catalog_application_schema_route(
        "PUBLISH_MOCK_EXAM_ITEM_REVIEW",
        review_result_schema="review-result@9.0",
    )
    assert (historical.request_schema, historical.response_schema) == (
        "catalog-application-request-v10",
        "catalog-application-response-v10",
    )
    assert successor == review_successor
    assert (successor.request_schema, successor.response_schema) == (
        "catalog-application-request-v12",
        "catalog-application-response-v12",
    )


def test_v2_v8_workflow_and_pack_bytes_remain_immutable() -> None:
    historical_hashes = {
        "schemas/item-registry/assessment-item-content-v2.schema.json": (
            "2136413f5059905be0c066c8fd657cbfc5238ba47e36ac3502be669ae130b9a8"
        ),
        "packages/workflow/eom_workflow/resources/roles/authoring-result-v8.schema.json": (
            "34d4336ea3708f02023d1711a878a23238a964e91624b19a7a5c6fa465a13289"
        ),
        "packages/workflow/eom_workflow/resources/roles/image-result-v8.schema.json": (
            "4eeadc1545de0d01f7aaa01d46af84cebcbd21554181de8551198280d02f2afc"
        ),
        "packages/workflow/eom_workflow/resources/roles/review-result-v8.schema.json": (
            "2d109a3861af5671e708e70e39f73fbbf58902d5dcc9e0cb11afe65342c28872"
        ),
        "packages/workflow/eom_workflow/resources/roles/registration-result-v8.schema.json": (
            "9f94aa730bbdaa198d1c1ffc76da42fd5e5cae69fcc4977b95c11f91d43dbd5a"
        ),
        "packages/hwpx_contracts/eom_hwpx_contracts/schemas/"
        "hwpx-content-team-editorial-question-v1.schema.json": (
            "7e52bf010fd0e47af817d26671dcd51282374f94700ea3236f572275a6e9d333"
        ),
        "packages/hwpx_contracts/eom_hwpx_contracts/schemas/"
        "hwpx-content-team-render-request-v2.schema.json": (
            "ffc2e505043281c2de74eb8e0e2de1014a3c905d16135d6b7504172967e7e660"
        ),
        "packages/hwpx_contracts/eom_hwpx_contracts/schemas/"
        "hwpx-content-team-build-result-v2.schema.json": (
            "e4242b10053389235c20a5a7989814ce4bbe4278b3a141ec0655dfb4a1d2b7b4"
        ),
        "packages/hwpx_contracts/eom_hwpx_contracts/schemas/"
        "hwpx-content-team-exam-render-request-v2.schema.json": (
            "0a98ee32f2713d9c6e56fd13926177c434812ec165ee197e2318e3ee8058d4fe"
        ),
        "packages/hwpx_contracts/eom_hwpx_contracts/schemas/"
        "hwpx-content-team-exam-build-result-v2.schema.json": (
            "ad6473ff89414718827ee6eb0bd0f00ae21cf77da736ef70bd38e195190da890"
        ),
        "schemas/assessment-assembly/mock-exam-production-plan-v1.schema.json": (
            "9f0cd769669d7394c59a8683f467bcc93a0846f6e6620a64d374f17802099f41"
        ),
    }
    for relative_path, expected in historical_hashes.items():
        assert hashlib.sha256((ROOT / relative_path).read_bytes()).hexdigest() == expected
    assert (
        compile_definition(
            ROOT / "config/workflows/generic-item-development.v1.8.yaml", ROLES
        ).sha256
        == "sha256:c54495195e8860bc037f96d778a6399af24f84fa6c0d8646aa62fd6e237862c9"
    )
    assert compile_pack(
        ROOT / "content/packs/generated-knowledge-item/1.13.0"
    ).source_tree_sha256 == (
        "sha256:a91aa67eb4916166681f8f58ed665253dd491bea72ccaf775036d1e6f1cc48b3"
    )


def test_v3_plan_and_pack_pin_only_the_new_family_without_copying_authority_bytes() -> None:
    plan = build_integrated_science_mock_exam_production_plan_v2(
        policy=load_integrated_science_mock_exam_policy(),
        layout_policy=load_integrated_science_mock_exam_layout_policy(),
        outline=load_integrated_science_editorial_outline(),
    )
    assert isinstance(plan, MockExamProductionPlanV2)
    assert plan.production_plan_id == "productionplan_f5de90cbffb98909cdf358b410353ffc"
    assert plan.plan_sha256 == (
        "sha256:f5de90cbffb98909cdf358b410353ffc81386f1589afaaaa960f9c12ab7f36d6"
    )
    assert (
        plan.one_item_generation_block.block_revision,
        plan.one_item_generation_block.workflow_definition_version,
        plan.one_item_generation_block.content_pack_version,
    ) == ("2.0", "1.9.0", "1.14.0")
    assert len(plan.workflow_calls) == 25
    validate_catalog_contract("mock-exam-production-plan-v2", plan.model_dump(mode="json"))
    pack = compile_pack(ROOT / "content/packs/generated-knowledge-item/1.14.0")
    assert pack.source_tree_sha256 == (
        "sha256:31f15f4811090045a92ad3a465e94f91ec430e638fe7b07f132c024e079a5792"
    )

    bootstrap = json.loads(
        json.dumps(
            __import__("yaml").safe_load(
                (ROOT / "config/control-plane/standard-item-v8/bootstrap.yaml").read_text(
                    encoding="utf-8"
                )
            )
        )
    )
    references = {row["reference_key"]: row for row in bootstrap["references"]}
    expected = {
        "content-team-integrated-science-authoring-v05": (
            ROOT / "config/control-plane/standard-item-v5/references/guidance/"
            "content-team-integrated-science-authoring-v05.md"
        ),
        "content-team-hwp-question-editor-handoff-v1": (
            ROOT / "config/control-plane/standard-item-v6/references/guidance/"
            "content-team-hwp-question-editor-handoff-v1.md"
        ),
    }
    for key, path in expected.items():
        assert "references" not in {
            child.name for child in (ROOT / "config/control-plane/standard-item-v8").iterdir()
        }
        assert (
            "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest() == references[key]["sha256"]
        )


def test_api_assembly_view_and_coordinator_pair_manifest_family_exactly() -> None:
    policy = load_integrated_science_mock_exam_policy()
    layout = load_integrated_science_mock_exam_layout_policy()
    outline = load_integrated_science_editorial_outline()
    plan_v1 = build_integrated_science_mock_exam_production_plan(
        policy=policy,
        layout_policy=layout,
        outline=outline,
    )
    plan_v2 = build_integrated_science_mock_exam_production_plan_v2(
        policy=policy,
        layout_policy=layout,
        outline=outline,
    )
    view_v2 = MockExamAssemblyViewV2.model_construct(
        schema_version="mock-exam-assembly-manifest/2.0"
    )
    view_v3 = MockExamAssemblyViewV3.model_construct(
        schema_version="mock-exam-assembly-manifest/3.0"
    )

    _require_assembly_manifest_family(plan_v1, view_v2)
    _require_assembly_manifest_family(plan_v2, view_v3)
    with pytest.raises(MockExamProductionCoordinatorError) as v2_error:
        _require_assembly_manifest_family(plan_v2, view_v2)
    with pytest.raises(MockExamProductionCoordinatorError) as v3_error:
        _require_assembly_manifest_family(plan_v1, view_v3)

    assert v2_error.value.code == "ASSEMBLY_SCHEMA_UNSUPPORTED"
    assert v3_error.value.code == "ASSEMBLY_SCHEMA_UNSUPPORTED"
    v2_schema = MockExamAssemblyViewV2.model_json_schema()
    v3_schema = MockExamAssemblyViewV3.model_json_schema()
    assert v2_schema["properties"]["schema_version"]["const"] == ("mock-exam-assembly-manifest/2.0")
    assert v3_schema["properties"]["schema_version"]["const"] == ("mock-exam-assembly-manifest/3.0")
