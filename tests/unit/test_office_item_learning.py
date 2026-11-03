"""Bind native picture instances without changing V1/V2 analysis or source pins."""

from copy import deepcopy

import pytest
from eom_catalog_contracts.external_item_learning_work import ExternalItemLearningWorkInput
from eom_catalog_contracts.office_item_learning import (
    OfficeItemLearningWorkInput,
    OfficeVisualBindings,
    parse_creative_learning_work,
    validate_office_visual_bindings,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_image_contracts.office_embedded_images import OfficeEmbeddedImageSet
from eom_image_contracts.office_picture_uses import (
    OfficeObjectLocator,
    OfficePictureGeometry,
    OfficePictureUse,
    OfficePictureUseCatalog,
    OfficePictureView,
    office_object_id,
)

from tests.unit.test_creative_source_visual_render import visual_result
from tests.unit.test_external_item_learning_work_contract import _work


def office_case():
    legacy = ExternalItemLearningWorkInput.model_validate(_work())
    source_sha = legacy.source.preview_manifest.source_sha256
    image_sha = "sha256:" + "a" * 64
    images = {
        "schema_version": "office-embedded-image-set/1.0",
        "source_sha256": source_sha,
        "source_format": "HWP5",
        "extractor_profile": "WHOLE_EMBEDDED_RASTER_V1",
        "images": [
            {
                "source_member": "BinData/BIN0008.bmp",
                "source_member_sha256": "sha256:" + "b" * 64,
                "source_format": "BMP",
                "pixel_sha256": "sha256:" + "c" * 64,
                "member_path": "images/" + image_sha[7:] + ".png",
                "sha256": image_sha,
                "width_px": 19,
                "height_px": 13,
                "content_length": 64,
            }
        ],
        "unsupported_members": [],
    }
    embedded = OfficeEmbeddedImageSet.model_validate(
        {**images, "manifest_sha256": content_sha256(images)}
    )
    uses = []
    for ordinal in (10, 90):
        locator = OfficeObjectLocator(member_path="BodyText/Section0", ordinal=ordinal)
        uses.append(
            OfficePictureUse(
                use_id=office_object_id(source_sha, locator),
                locator=locator,
                source_member="BinData/BIN0008.bmp",
                native_sha256="sha256:" + "d" * 64,
                group_id=None,
                placement=None,
                geometry=OfficePictureGeometry(
                    original_extent=(1900, 1300),
                    viewport=(0, 0, 1900, 1300),
                    clockwise_quarter_turns=0,
                    flip_horizontal=False,
                    flip_vertical=False,
                ),
                unresolved_reasons=(),
            )
        )
    views = [
        OfficePictureView(
            use_id=use.use_id,
            member_path=embedded.images[0].member_path,
            sha256=image_sha,
            width_px=19,
            height_px=13,
            content_length=64,
        )
        for use in uses
    ]
    catalog_value = {
        "schema_version": "office-picture-use-catalog/1.0",
        "extractor_profile": "HANCOM_NATIVE_PICTURE_USES_V1",
        "embedded_images": embedded.model_dump(mode="json"),
        "picture_uses": [use.model_dump(mode="json") for use in uses],
        "rendered_uses": [view.model_dump(mode="json") for view in views],
        "native_objects": [],
    }
    catalog = OfficePictureUseCatalog.model_validate(
        {**catalog_value, "manifest_sha256": content_sha256(catalog_value)}
    )
    work_value = legacy.model_dump(mode="json", exclude={"request_sha256"})
    work_value.update(
        schema_version="external-item-learning-work-input/2.0",
        office_artifact={
            "artifact_type": "control_office_picture_use_catalog",
            "artifact_id": "artifact_" + "1" * 32,
            "artifact_revision_id": "rev_" + "2" * 32,
            "member_path": "picture-use-catalog.json",
            "schema_ref": "eom://schemas/image-provider/office-picture-use-catalog/1.0",
            "media_type": "application/json",
            "sha256": sha256_bytes(canonical_json_bytes(catalog.model_dump(mode="json"))),
            "file_set_manifest_sha256": "sha256:" + "3" * 64,
        },
    )
    work = OfficeItemLearningWorkInput.model_validate(
        {**work_value, "request_sha256": content_sha256(work_value)}
    )
    result = visual_result(work.source)
    block = result.proposal.content.body[-1]
    bindings = OfficeVisualBindings.model_validate(
        {
            "office_catalog_sha256": work.office_artifact.sha256,
            "bindings": [
                {
                    "block_id": block.block_id,
                    "picture_use_id": uses[0].use_id,
                    "source_region_id": block.source_region_id,
                    "selection_reason": (
                        "본문의 도식과 원문 표기를 확인하고 참고란의 다른 사용 개체를 제외했다."
                    ),
                }
            ],
        }
    )
    return work, result, catalog, bindings


def test_successor_work_and_binding_preserve_unchanged_source_analysis():
    work, result, catalog, bindings = office_case()
    before = result.model_dump(mode="json")
    validate_office_visual_bindings(bindings, result=result, work=work, catalog=catalog)
    assert result.model_dump(mode="json") == before
    assert isinstance(
        parse_creative_learning_work(work.model_dump(mode="json")), OfficeItemLearningWorkInput
    )
    assert isinstance(parse_creative_learning_work(_work()), ExternalItemLearningWorkInput)
    assert catalog.picture_uses[0].source_member == catalog.picture_uses[1].source_member
    assert bindings.bindings[0].picture_use_id != catalog.picture_uses[1].use_id
    assert not any(
        key in work.model_dump() for key in ("base64", "png_bytes", "pdf_bytes", "workspace_path")
    )


@pytest.mark.parametrize(
    "field",
    [
        "catalog-pin",
        "catalog-source",
        "missing-block",
        "extra-block",
        "missing-use",
        "reference-region",
        "wrong-region",
        "unresolved-use",
        "different-source",
    ],
)
def test_binding_failures_do_not_accept_unrelated_or_incomplete_images(field):
    work, result, catalog, selection = office_case()
    value = selection.model_dump(mode="json")
    if field == "catalog-pin":
        value["office_catalog_sha256"] = "sha256:" + "0" * 64
    elif field == "catalog-source":
        catalog = catalog.model_copy(update={"manifest_sha256": "sha256:" + "0" * 64})
    elif field == "missing-block":
        value["bindings"] = []
    elif field == "extra-block":
        value["bindings"][0]["block_id"] = "block_unrelated"
    elif field == "missing-use":
        value["bindings"][0]["picture_use_id"] = "officeobj_" + "0" * 32
    elif field == "reference-region":
        identifier = value["bindings"][0]["source_region_id"]
        result = result.model_copy(
            update={
                "regions": tuple(
                    region.model_copy(update={"role": "REFERENCE_ORIGINAL"})
                    if region.region_id == identifier
                    else region
                    for region in result.regions
                )
            }
        )
    elif field == "wrong-region":
        value["bindings"][0]["source_region_id"] = "extregion_" + "0" * 32
    elif field == "unresolved-use":
        use = catalog.picture_uses[0].model_copy(
            update={"unresolved_reasons": ("GEOMETRY_UNRESOLVED",)}
        )
        catalog = catalog.model_copy(update={"picture_uses": (use, *catalog.picture_uses[1:])})
    else:
        result = result.model_copy(update={"external_number": "99999"})
    with pytest.raises(ValueError):
        validate_office_visual_bindings(
            OfficeVisualBindings.model_validate(value), result=result, work=work, catalog=catalog
        )


def test_duplicate_use_is_not_published_twice_as_two_different_panels():
    _work_value, _result, _catalog, selection = office_case()
    value = selection.model_dump(mode="json")
    other = deepcopy(value["bindings"][0])
    other["block_id"] = "block_second_panel"
    value["bindings"].append(other)
    with pytest.raises(ValueError, match="BINDING_DUPLICATE"):
        OfficeVisualBindings.model_validate(value)


def test_old_work_rejects_office_fields_and_new_work_rejects_missing_pointer():
    work, _result, _catalog, _selection = office_case()
    value = work.model_dump(mode="json")
    with pytest.raises(ValueError):
        ExternalItemLearningWorkInput.model_validate(value)
    del value["office_artifact"]
    with pytest.raises(ValueError):
        OfficeItemLearningWorkInput.model_validate(value)


def test_office_role_successor_schema_and_generation_keep_analysis_v2():
    from eom_workflow.models import ExternalItemLearningRoleResultV3, RoleWorkerInput
    from eom_workflow.schemas import (
        constrained_result_schema,
        load_role_input_schema,
        load_role_result_schema,
        validate_role_input,
        validate_role_result,
    )

    from tests.unit.test_external_item_learning_role_schemas import _input
    from tests.unit.test_external_item_learning_workflow_models import _references

    work, result, _catalog, selection = office_case()
    raw_input = _input()
    raw_input["protocol_version"] = "workflow-role/1.36.0"
    raw_input["request"]["work_input"] = work.model_dump(mode="json")
    parsed = validate_role_input(raw_input, "support", "workflow-role/1.36.0")
    assert isinstance(parsed, RoleWorkerInput)
    raw_result = {
        "schema_version": "1.0",
        "protocol_version": "workflow-role/1.36.0",
        "job_id": raw_input["job_id"],
        "workflow_id": raw_input["workflow_id"],
        "step_run_id": raw_input["step_run_id"],
        "artifact": raw_input["artifact"],
        "completed_at": "2026-11-03T16:00:00Z",
        "status": "ok",
        "role": "support",
        "output": {
            "learning_result": result.model_dump(mode="json"),
            "office_visuals": selection.model_dump(mode="json"),
        },
    }
    admitted = validate_role_result(raw_result, "support", "external-item-learning-result@3.0")
    assert isinstance(admitted, ExternalItemLearningRoleResultV3)
    assert admitted.output.learning_result == result
    projected = constrained_result_schema("external-item-learning-result@3.0", parsed)
    assert "result_sha256" not in projected["$defs"]["ExternalItemLearningResultV2"]["properties"]
    for schema in (
        projected,
        load_role_input_schema("support", "workflow-role/1.36.0"),
        load_role_result_schema("external-item-learning-result@3.0"),
    ):
        assert all(reference.startswith("#/$defs/") for reference in _references(schema))


def test_released_source_role_contract_hashes_are_not_reinterpreted():
    from eom_workflow.schemas import role_schema_bundle_hash

    assert (
        role_schema_bundle_hash("workflow-role/1.33.0")
        == "sha256:926c8f0ecce98016b62515561b2fbf25a594b1ba5c4cfc8791fa6ab7323db025"
    )
    assert (
        role_schema_bundle_hash("workflow-role/1.34.0")
        == "sha256:c4f572af3bf8afbae19e42946c0b484a3f056acd6d1f2b896d299c75f68a91e2"
    )
