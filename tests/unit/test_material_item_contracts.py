"""Uploaded questions reuse canonical content and native-use rules without fake archives."""

from copy import deepcopy
from pathlib import Path

import pytest
from eom_catalog_contracts.material_item_lineage import (
    MaterialItemLineage,
    material_item_registration_key,
)
from eom_catalog_contracts.material_learning import MaterialExtractionResult
from eom_catalog_service.content_pack_files import compile_pack
from eom_catalog_service.creative_source_content import materialize_source_observation_content
from eom_identifiers import content_sha256
from eom_orchestrator.office_picture_use_publication import resolve_material_office_source_images
from eom_protocol.artifact_members import ArtifactMemberPointer

from tests.unit.test_material_learning_contracts import extraction_result, extraction_work, member
from tests.unit.test_material_learning_execution import request
from tests.unit.test_office_item_learning import office_case

ROOT = Path(__file__).resolve().parents[2]


def lineage():
    work = extraction_work()
    selected = request().model_dump(mode="json")
    selected["input_sha256"] = work["input_sha256"]
    data = dict(
        schema_version="material-learning-item-lineage/1.0",
        material_id=work["material_id"],
        material_revision_id=work["material_revision_id"],
        task_id=work["task_id"],
        unit_key=work["unit_key"],
        selection=selected,
        work_input=member(
            "material/work.json", "application/json", "material-learning/extraction-work/1.0"
        ),
        role_result=dict(
            artifact_id="artifact_" + "8" * 32,
            artifact_revision_id="rev_" + "9" * 32,
            member_path="result.json",
            schema_ref="material-learning-result@1.0",
            media_type="application/json",
            sha256="sha256:" + "a" * 64,
        ),
        input_sha256=work["input_sha256"],
        result_sha256=content_sha256(extraction_result()),
        proposed_content_sha256="sha256:" + "b" * 64,
        registered_content_sha256="sha256:" + "c" * 64,
        source_answer_mode="EDITORIAL_SOURCE",
        warning_codes=[],
        registration_policy="PRESERVE_SOURCE_WITH_REVIEW_WARNINGS_V1",
        requested_by="operator_" + "d" * 32,
        created_at="2026-11-05T22:00:00Z",
    )
    return {**data, "lineage_sha256": content_sha256(data)}


def test_lineage_is_pointer_only_and_has_no_notion_or_official_exam_identity():
    value = lineage()
    parsed = MaterialItemLineage.model_validate(value)
    assert not {
        "external_number",
        "import_id",
        "assessment_occurrence_revision_id",
        "proposal",
    }.intersection(parsed.model_dump())
    assert len(parsed.model_dump_json()) < 8000
    assert material_item_registration_key(
        parsed.material_revision_id, parsed.unit_key
    ) == material_item_registration_key(parsed.material_revision_id, parsed.unit_key)
    other = material_item_registration_key("materialrev_" + "0" * 32, parsed.unit_key)
    assert other != material_item_registration_key(parsed.material_revision_id, parsed.unit_key)
    changed = deepcopy(value)
    changed["result_sha256"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="INVALID"):
        MaterialItemLineage.model_validate(changed)


def test_general_source_compiler_preserves_original_instead_of_substituting_public_solution():
    parsed = MaterialExtractionResult.model_validate(extraction_result())
    before = parsed.model_dump(mode="json")
    compiled = materialize_source_observation_content(parsed, resolved_images={})
    assert compiled.content.solution == parsed.proposal.content.solution
    assert parsed.model_dump(mode="json") == before
    assert compiled.registered_content_sha256 == content_sha256(
        compiled.content.model_dump(mode="json")
    )


def test_material_office_images_reuse_original_use_members_with_no_pdf_crop():
    work, observed, catalog, bindings = office_case()
    pointer = ArtifactMemberPointer(
        **work.office_artifact.model_dump(include=set(ArtifactMemberPointer.model_fields))
    )
    images = resolve_material_office_source_images(
        result=observed,
        selection=bindings,
        catalog=catalog,
        catalog_pointer=pointer,
        expected_source_sha256=work.source.preview_manifest.source_sha256,
    )
    expected = {view.use_id: view for view in catalog.rendered_uses}
    for binding in bindings.bindings:
        image = images[binding.block_id]
        assert image.artifact.artifact_id == pointer.artifact_id
        assert image.artifact.artifact_revision_id == pointer.artifact_revision_id
        assert image.artifact.artifact_member == expected[binding.picture_use_id].member_path


def test_registration_pack_is_an_isolated_existing_registry_profile_not_generated_authoring():
    pack = compile_pack(ROOT / "content/packs/uploaded-material-item/1.0.0")
    assert pack.manifest.pack.key == "uploaded-material-item"
    assert pack.manifest.compatibility.workflow_definitions[0].key == "material-learning"
