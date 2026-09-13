from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from eom_api.services.command_adapter import _workflow_request_from_api
from eom_api_contracts.workflows import WorkflowStartRequest
from eom_catalog_contracts import (
    ContentTeamMaterialRequirementV1,
    validate_content_team_material_requirement,
)
from eom_catalog_service.content_pack_files import build_pack, compile_pack
from eom_catalog_service.workflow_catalog import WorkflowCatalogService
from eom_hwpx_contracts import ContentTeamImageSlot, ContentTeamTable
from eom_workflow import ContentTeamItemBriefV4
from eom_workflow.schemas import (
    load_content_team_editorial_material_schema,
    load_content_team_image_route_schema,
    load_content_team_material_requirement_schema,
    load_knowledge_item_brief_v3_schema,
    load_knowledge_item_brief_v4_schema,
)
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from referencing import Registry, Resource

from tests.unit.test_content_team_v3_protocol import _content_v3

ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / "content/packs/generated-knowledge-item/1.16.0"


def _table(label: str = "") -> ContentTeamTable:
    return ContentTeamTable.model_validate(
        {
            "label": label,
            "headers": ["구분", "측정값"],
            "rows": [["A", "3"], ["B", "5"]],
            "alignments": ["left", "right"],
        }
    )


def _brief_request(*, form: str, panel_count: int | None, image_mode: str) -> WorkflowStartRequest:
    guidance = "검토된 자료 형식을 사용하여 새로운 통합과학 문항을 작성한다."
    digest = hashlib.sha256(guidance.encode()).hexdigest()
    return WorkflowStartRequest.model_validate(
        {
            "definition_key": "generic-item-development",
            "definition_version": "1.10.0",
            "request_name": "GENERATED_KNOWLEDGE_ITEM_REQUEST",
            "image_mode": image_mode,
            "pack_key": "generated-knowledge-item",
            "execution_preset_key": "standard-item",
            "item_brief": {
                "schema_version": "4.0",
                "subject": "통합과학",
                "topic": "측정 자료 해석",
                "task_type": "data_interpretation",
                "difficulty": "medium",
                "authoring_guidance": guidance,
                "authoring_guidance_sha256": f"sha256:{digest}",
                "curriculum_selected_unit_key": None,
                "mock_exam_slot": None,
                "material_requirement": {
                    "schema_version": "content-team-material-requirement/1.0",
                    "form": form,
                    "panel_count": panel_count,
                },
                "original_request_sha256": digest,
            },
        }
    )


@pytest.mark.parametrize(
    ("form", "panel_count", "image_mode"),
    [
        ("AUTO", None, "required"),
        ("TEXT", None, "skip"),
        ("DATA", None, "skip"),
        ("TABLE", 1, "skip"),
        ("TABLE", 2, "skip"),
        ("IMAGE", 1, "required"),
        ("IMAGE", 2, "required"),
        ("MIXED", 2, "required"),
        ("INQUIRY", None, "skip"),
    ],
)
def test_material_requirement_derives_image_capability(
    form: str, panel_count: int | None, image_mode: str
) -> None:
    requirement = ContentTeamMaterialRequirementV1.model_validate(
        {"form": form, "panel_count": panel_count}
    )

    assert requirement.image_mode == image_mode
    Draft202012Validator(load_content_team_material_requirement_schema()).validate(
        requirement.model_dump(mode="json")
    )


@pytest.mark.parametrize(
    ("form", "panel_count"),
    [("TABLE", None), ("IMAGE", 0), ("MIXED", 1), ("TEXT", 1)],
)
def test_material_requirement_rejects_incoherent_panel_count(
    form: str, panel_count: int | None
) -> None:
    value = {
        "schema_version": "content-team-material-requirement/1.0",
        "form": form,
        "panel_count": panel_count,
    }

    with pytest.raises(ValueError):
        ContentTeamMaterialRequirementV1.model_validate(value)
    with pytest.raises(JsonSchemaValidationError):
        Draft202012Validator(load_content_team_material_requirement_schema()).validate(value)


def test_table_only_is_one_native_table_and_zero_image_slots() -> None:
    content = _content_v3(visuals=(_table(),), visual_layout="TABLE_ONLY")
    requirement = ContentTeamMaterialRequirementV1(form="TABLE", panel_count=1)

    validate_content_team_material_requirement(requirement, content)
    Draft202012Validator(load_content_team_editorial_material_schema()).validate(
        content.model_dump(mode="json")
    )

    assert tuple(visual.kind for visual in content.visuals) == ("TABLE",)
    assert sum(visual.kind == "IMAGE" for visual in content.visuals) == 0


def test_two_tables_require_text_panel_labels_inside_the_layout() -> None:
    content = _content_v3(
        visuals=(_table("(가)"), _table("(나)")),
        visual_layout="TABLE_TABLE",
    )

    validate_content_team_material_requirement(
        ContentTeamMaterialRequirementV1(form="TABLE", panel_count=2),
        content,
    )

    assert tuple(visual.label for visual in content.visuals) == ("(가)", "(나)")


def test_table_requirement_rejects_image_or_data_placeholder_substitution() -> None:
    requirement = ContentTeamMaterialRequirementV1(form="TABLE", panel_count=1)
    image = _content_v3(
        visuals=(ContentTeamImageSlot(),),
        visual_layout="IMAGE_ONLY",
    )
    table_with_duplicate_data = _content_v3(
        visuals=(_table(),),
        visual_layout="TABLE_ONLY",
    ).model_dump(mode="json")
    table_with_duplicate_data["labeled_blocks"] = [
        {"kind": "DATA", "content": "표와 중복되는 자료 문장"}
    ]

    with pytest.raises(ValueError, match="TABLE form"):
        validate_content_team_material_requirement(requirement, image)
    with pytest.raises(ValueError, match="DATA blocks"):
        validate_content_team_material_requirement(
            requirement,
            type(image).model_validate(table_with_duplicate_data),
        )


def test_v4_api_request_maps_to_internal_brief_and_skips_image_profile_for_table() -> None:
    request = _brief_request(form="TABLE", panel_count=1, image_mode="skip")
    internal = _workflow_request_from_api(request)

    assert isinstance(internal.item_brief, ContentTeamItemBriefV4)
    assert internal.item_brief.material_requirement.form == "TABLE"
    assert internal.image_mode == "skip"
    assert internal.profiles is not None
    assert internal.profiles.image is None
    WorkflowCatalogService._require_item_brief_release(
        "generated-knowledge-item", "1.16.0", internal
    )


def test_v4_api_request_rejects_image_capability_drift() -> None:
    with pytest.raises(ValueError, match="image capability"):
        _brief_request(form="TABLE", panel_count=1, image_mode="required")


def test_v4_brief_schema_resolves_only_pinned_local_resources() -> None:
    schemas = (
        load_content_team_material_requirement_schema(),
        # The V4 schema reuses immutable V3 curriculum and mock-exam definitions.
        load_knowledge_item_brief_v3_schema(),
        load_knowledge_item_brief_v4_schema(),
    )
    registry = Registry().with_resources(
        (schema["$id"], Resource.from_contents(schema)) for schema in schemas
    )
    internal = _workflow_request_from_api(
        _brief_request(form="TABLE", panel_count=1, image_mode="skip")
    )

    Draft202012Validator(schemas[-1], registry=registry).validate(
        internal.item_brief.model_dump(mode="json") if internal.item_brief is not None else None
    )


def test_image_route_guard_rejects_hybrid_reason_on_deterministic_route() -> None:
    value = {
        "output": {
            "drawings": [
                {
                    "drawing": {
                        "kind": "apparatus",
                        "production_route": "DETERMINISTIC_SVG",
                        "route_reason": "REALISTIC_NATURAL_SCENE_REQUIRED",
                        "generation_prompt": None,
                        "negative_prompt": None,
                    }
                }
            ]
        }
    }

    with pytest.raises(JsonSchemaValidationError):
        Draft202012Validator(load_content_team_image_route_schema()).validate(value)


def test_pack_116_is_additive_material_aware_and_deterministic(tmp_path: Path) -> None:
    predecessor = compile_pack(ROOT / "content/packs/generated-knowledge-item/1.15.9")
    compiled = compile_pack(PACK)
    built = build_pack(PACK, tmp_path)

    assert predecessor.source_tree_sha256 == (
        "sha256:bb309a4542b87d94e9699a8fce3905c779e41f004df581c1343821e077d55ce7"
    )
    assert compiled.manifest.pack.version == "1.16.0"
    assert compiled.source_tree_sha256 == (
        "sha256:02b4ea7987abb25d5a34a939961a518ad54987f44792532e6b824f7419518a00"
    )
    assert built.bundle_sha256 == (
        "sha256:6767e020ff2be15d5fb557cae02fb318e18a36b41cc06f287dd51129f0505c41"
    )
    assert built.manifest_sha256 == (
        "sha256:a3f1ac3e8811d49c285d954dee92a4060764bca5eff34ca071886616fe9f01b1"
    )
    prompt = (PACK / "prompt-templates/authoring.md").read_text(encoding="utf-8")
    review = (PACK / "prompt-templates/review.md").read_text(encoding="utf-8")
    for required in (
        "native editable TABLE",
        "IMAGE worker를 실행할 수 있는지 나타내는 실행 capability",
        "TABLE_ONLY",
        "표의 실제 scalar",
    ):
        assert required in prompt
    assert "MATERIAL_REQUIREMENT_MISMATCH" in review
