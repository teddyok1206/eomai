"""Real synthetic PDF crop and source-local recipes, never production content."""

from copy import deepcopy

import pytest
from eom_catalog_contracts.material_learning import (
    MaterialExtractionResult,
    MaterialExtractionWork,
)
from eom_catalog_contracts.material_learning_preparation import MaterialPreparedPage
from eom_catalog_contracts.material_source_visuals import MaterialPdfVisualSet
from eom_identifiers import content_sha256, sha256_bytes
from eom_orchestrator.external_item_learning_page_render import (
    MaterialPdfRenderSource,
    render_material_pdf_visual,
)
from eom_orchestrator.material_source_visual_publication import material_pdf_visual_recipes

from tests.unit.test_creative_source_visual_render import visual_result
from tests.unit.test_external_item_learning_page_render import (
    _direct_fixture_runner,
    _pdf,
    _source_for_pdf,
)
from tests.unit.test_material_item_contracts import lineage
from tests.unit.test_material_learning_contracts import extraction_result, extraction_work


def visual_case():
    original = visual_result(_source_for_pdf(_pdf()), repeat=True).model_dump(mode="json")
    data = extraction_result(original)
    # Canonical prepared page members, with 31 != delivered input index 1.
    work_value = extraction_work()
    for page in work_value["pages"]:
        page["image"]["member_path"] = f"analysis/images/page-{page['physical_page']:06d}.png"
    work_value["input_sha256"] = content_sha256(
        {key: value for key, value in work_value.items() if key != "input_sha256"}
    )
    work = MaterialExtractionWork.model_validate(work_value)
    data["input_sha256"] = work.input_sha256
    result = MaterialExtractionResult.model_validate(data)
    pages = {}
    for page in work.pages:
        pages[(page.source_role, page.physical_page)] = MaterialPreparedPage(
            physical_page=page.physical_page,
            image=page.image.model_dump(exclude={"artifact_id", "artifact_revision_id"}),
            text=dict(
                member_path=f"analysis/pages/page-{page.physical_page:06d}.md",
                schema_ref="eom://schemas/material-learning/page-text/1.0",
                media_type="text/markdown",
                sha256=page.image.sha256,
                bytes=10,
            ),
            width_pixels=page.width_pixels,
            height_pixels=page.height_pixels,
            render_dpi=180,
        )
    return work, result, pages


def test_sparse_source_page_is_not_reinterpreted_as_input_index_and_duplicates_share_crop():
    work, result, pages = visual_case()
    recipes = material_pdf_visual_recipes(work, result, pages)
    assert len(recipes) == 1
    assert recipes[0]["input_index"] == 1
    assert recipes[0]["physical_page"] == 31
    assert recipes[0]["render_dpi"] == 180
    assert recipes[0]["pixel_box"] == [20, 42, 80, 126]
    assert (
        len([block for block in result.proposal.content.body if block.type == "source_image"]) == 2
    )


def test_source_page_hash_mismatch_and_hancom_pdf_fallback_are_refused():
    work, result, pages = visual_case()
    changed = dict(pages)
    value = pages[("MAIN", 31)].model_dump(mode="json")
    value["image"]["sha256"] = "sha256:" + "0" * 64
    changed[("MAIN", 31)] = MaterialPreparedPage.model_validate(value)
    with pytest.raises(ValueError, match="MISMATCH"):
        material_pdf_visual_recipes(work, result, changed)


def test_real_poppler_crop_uses_dpi_coordinates_not_old_scale_to_2400(tmp_path):
    pdf = _pdf()
    source = MaterialPdfRenderSource(pdf, sha256_bytes(pdf))
    target = tmp_path / "figure.png"
    digest, size = render_material_pdf_visual(
        source,
        physical_page=1,
        render_dpi=180,
        pixel_box=(10, 20, 200, 180),
        output=target,
        run=_direct_fixture_runner,
    )
    assert digest == sha256_bytes(target.read_bytes())
    assert size == target.stat().st_size
    with pytest.raises(ValueError, match="PDF_INVALID"):
        MaterialPdfRenderSource(pdf + b"changed", source.sha256)
    with pytest.raises(ValueError, match="INPUT_INVALID"):
        render_material_pdf_visual(
            source,
            physical_page=1,
            render_dpi=180,
            pixel_box=(10, 20, 200, 180),
            output=target,
            run=_direct_fixture_runner,
        )


def test_visual_receipt_closes_exact_recipe_and_immutable_hash():
    work, result, pages = visual_case()
    recipe = material_pdf_visual_recipes(work, result, pages)[0]
    value = dict(
        schema_version="material-learning-visual-set/1.0",
        input_sha256=work.input_sha256,
        result_sha256=content_sha256(result.model_dump(mode="json")),
        role_result=lineage()["role_result"],
        pdftoppm_sha256="sha256:" + "1" * 64,
        crops=[{**recipe, "sha256": "sha256:" + "2" * 64, "bytes": 100}],
    )
    value["manifest_sha256"] = content_sha256(value)
    parsed = MaterialPdfVisualSet.model_validate(value)
    assert parsed.crops[0].physical_page == 31
    tampered = deepcopy(value)
    tampered["crops"][0]["physical_page"] = 1
    with pytest.raises(ValueError, match="INVALID"):
        MaterialPdfVisualSet.model_validate(tampered)
