"""The generic input cannot claim archive identity or lose mixed-page coverage."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
from eom_catalog_contracts.material_learning import (
    PERMITTED_USES,
    MaterialDiscoveryResult,
    MaterialDiscoveryWork,
    MaterialExtractionResult,
    MaterialExtractionWork,
    MaterialLearningRights,
    MaterialLearningUpload,
    validate_material_discovery,
    validate_material_extraction,
)
from eom_catalog_contracts.validation import validate_contract
from eom_identifiers import content_sha256
from jsonschema import ValidationError as SchemaError
from pydantic import ValidationError

from tests.unit.test_external_item_learning_result_v2 import result_v2, undetermined_result_v2

ROOT = Path(__file__).resolve().parents[2]
HASH = "sha256:" + "a" * 64


def member(path="source/original.pdf", media="application/pdf", schema="pdf-source/1.0"):
    return {
        "artifact_id": "artifact_" + "1" * 32,
        "artifact_revision_id": "rev_" + "2" * 32,
        "member_path": path,
        "schema_ref": "eom://schemas/" + schema,
        "media_type": media,
        "sha256": HASH,
        "bytes": 100,
    }


def source(role="MAIN"):
    pdf = member()
    return {
        "source_role": role,
        "actual_format": "PDF",
        "original_filename": "자료.pdf",
        "document_id": "edudoc_" + "3" * 32,
        "document_revision_id": "edudocrev_" + "4" * 32,
        "document_manifest_sha256": HASH,
        "original": pdf,
        "pdf": deepcopy(pdf),
        "page_bundle": member(
            "analysis/manifest.json", "application/json", "material-learning/page-bundle/1.0"
        ),
        "office_catalog": None,
        "page_count": 100,
    }


def rehash(value, field="input_sha256"):
    value[field] = content_sha256({key: child for key, child in value.items() if key != field})
    return value


def work():
    return rehash(
        {
            "schema_version": "material-learning-discovery-work/1.0",
            "task_kind": "DISCOVER",
            "material_id": "material_" + "5" * 32,
            "material_revision_id": "materialrev_" + "6" * 32,
            "task_id": "materialtask_" + "7" * 32,
            "sources": [source()],
            "rights_attestation": member(
                "rights/attestation.json", "application/json", "material-learning/rights/1.0"
            ),
            "pages": [
                {
                    "input_index": index,
                    "source_role": "MAIN",
                    "physical_page": number,
                    "image": member(
                        f"pages/page-{number:06d}.png",
                        "image/png",
                        "educational-document/page-image/1.0",
                    ),
                    "text": None,
                    "width_pixels": 1000,
                    "height_pixels": 1400,
                }
                for index, number in enumerate((31, 32), 1)
            ],
            "additional_instructions": "문항과 해설의 원문을 보존한다.",
            "core_pages": [{"source_role": "MAIN", "physical_page": 31}],
        }
    )


def unit(kind="QUESTION", label="1", page=31):
    return {
        "local_key": kind.lower() + label,
        "kind": kind,
        "section_path": ["1장"],
        "printed_label": label,
        "anchors": [
            {
                "source_role": "MAIN",
                "physical_page": page,
                "bounding_box": {"left": 100, "top": 100, "right": 9000, "bottom": 9000},
            }
        ],
        "continuation": "COMPLETE",
        "related_item_labels": [],
        "summary": "원문 위치를 가진 학습 단위",
        "warnings": [],
    }


def discovery():
    return {
        "schema_version": "material-learning-discovery-result/1.0",
        "input_sha256": work()["input_sha256"],
        "coverage": [
            {
                "source_role": "MAIN",
                "physical_page": number,
                "roles": ["EXPLANATION", "QUESTION"],
                "note": "설명과 연습 문제가 공존함",
            }
            for number in (31, 32)
        ],
        "units": [
            unit(),
            unit("EXPLANATION", page=31),
            {**unit(page=32), "local_key": "context-question"},
            {**unit("EXPLANATION", page=32), "local_key": "context-explanation"},
        ],
        "warnings": [],
    }


def extraction_work():
    value = work()
    value.pop("core_pages")
    value.update(
        schema_version="material-learning-extraction-work/1.0",
        task_kind="EXTRACT_ITEM",
        unit_key="materialunit_" + "8" * 32,
        question=unit(),
        solutions=[unit("SOLUTION")],
    )
    return rehash(value)


def extraction_result(original=None):
    value = original or result_v2()
    return {
        "schema_version": "material-learning-extraction-result/1.0",
        "input_sha256": extraction_work()["input_sha256"],
        **{
            key: value[key]
            for key in ("status", "regions", "proposal", "solution_report", "conflicts")
        },
        "office_bindings": None,
    }


def test_generic_source_pins_without_inventing_notion_or_occurrence():
    document = work()
    validate_contract("material-learning-discovery-work-v1", document)
    parsed = MaterialDiscoveryWork.model_validate(document)
    assert parsed.pages[0].physical_page == 31
    assert not {"external_number", "source_namespace", "assessment_occurrence"}.intersection(
        document
    )
    assert parsed.sources[0].original == parsed.sources[0].pdf


def test_mixed_page_discovery_and_context_are_preserved():
    value = discovery()
    value["units"][2]["local_key"] = "context-question"
    result = MaterialDiscoveryResult.model_validate(value)
    validate_material_discovery(result, MaterialDiscoveryWork.model_validate(work()))
    assert result.coverage[0].roles == ("EXPLANATION", "QUESTION")


def test_claimed_question_coverage_cannot_hide_a_missing_unit():
    value = discovery()
    value["units"][2]["local_key"] = "context-question"
    value["units"].pop()
    with pytest.raises(ValueError, match="CONTENT_WITHOUT_UNIT"):
        validate_material_discovery(
            MaterialDiscoveryResult.model_validate(value),
            MaterialDiscoveryWork.model_validate(work()),
        )


@pytest.mark.parametrize(
    "change,code",
    [
        (lambda value: value["pages"][0].update(input_index=2), "PAGE_INDEX"),
        (lambda value: value["pages"][0].update(physical_page=101), "OUTSIDE_SOURCE"),
        (lambda value: value["sources"].append(source()), "ROLE_DUPLICATE"),
        (lambda value: value["pages"].append(value["pages"][0]), "PAGE_INDEX"),
        (
            lambda value: value["core_pages"].append({"source_role": "MAIN", "physical_page": 40}),
            "CORE_PAGES",
        ),
        (
            lambda value: value["sources"][0]["original"].update(sha256="sha256:" + "0" * 64),
            "DUPLICATED",
        ),
        (lambda value: value["pages"][0]["image"].update(media_type="image/jpeg"), "PAGE_IMAGE"),
        (
            lambda value: value["rights_attestation"].update(
                schema_ref="eom://schemas/educational-document/rights-attestation/1.0"
            ),
            "RIGHTS_SCHEMA",
        ),
    ],
)
def test_invalid_input_closure_rejected(change, code):
    value = deepcopy(work())
    change(value)
    rehash(value)
    with pytest.raises(ValidationError, match=code):
        MaterialDiscoveryWork.model_validate(value)


def test_wrong_hash_is_not_repaired_by_contract():
    value = work()
    value["task_id"] = "materialtask_" + "0" * 32
    with pytest.raises(ValidationError, match="HASH_MISMATCH"):
        MaterialDiscoveryWork.model_validate(value)


@pytest.mark.parametrize("field,value", [("physical_page", "31"), ("physical_page", True)])
def test_raw_schema_and_model_reject_coerced_page_numbers(field, value):
    document = work()
    document["pages"][0][field] = value
    rehash(document)
    with pytest.raises(SchemaError):
        validate_contract("material-learning-discovery-work-v1", document)
    with pytest.raises(ValidationError):
        MaterialDiscoveryWork.model_validate(document)


def test_discovery_coverage_cannot_drop_pages_or_include_other_input():
    value = discovery()
    value["units"][2]["local_key"] = "context-question"
    value["coverage"].pop()
    with pytest.raises(ValueError, match="COVERAGE_INCOMPLETE"):
        validate_material_discovery(
            MaterialDiscoveryResult.model_validate(value),
            MaterialDiscoveryWork.model_validate(work()),
        )
    value = discovery()
    value["units"][2]["local_key"] = "context-question"
    value["input_sha256"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="INPUT_MISMATCH"):
        validate_material_discovery(
            MaterialDiscoveryResult.model_validate(value),
            MaterialDiscoveryWork.model_validate(work()),
        )


def test_question_and_solution_share_existing_source_analysis_rules():
    value = extraction_result()
    validate_contract("material-learning-extraction-result-v1", value)
    parsed = MaterialExtractionResult.model_validate(value)
    validate_material_extraction(parsed, MaterialExtractionWork.model_validate(extraction_work()))
    assert parsed.proposal is not None
    assert parsed.proposal.content.solution_origin == "EDITORIAL_SOURCE"


def test_source_error_and_independent_solution_survive_without_forcing_approval():
    result = MaterialExtractionResult.model_validate(extraction_result(undetermined_result_v2()))
    assert result.status == "NEEDS_DECISION"
    assert result.solution_report.answer_state == "UNDETERMINED"
    assert result.proposal is not None


def test_solution_from_another_page_cannot_be_cited_as_source():
    value = extraction_work()
    value["solutions"][0]["anchors"][0]["physical_page"] = 32
    rehash(value)
    result = extraction_result()
    result["input_sha256"] = value["input_sha256"]
    with pytest.raises(ValueError, match="ROLE_OUTSIDE_SELECTION"):
        validate_material_extraction(
            MaterialExtractionResult.model_validate(result),
            MaterialExtractionWork.model_validate(value),
        )


def test_unresolved_cross_page_fragment_cannot_be_registered_as_complete():
    value = extraction_work()
    value["question"]["continuation"] = "TO_NEXT"
    rehash(value)
    with pytest.raises(ValidationError, match="CONTINUATION_UNRESOLVED"):
        MaterialExtractionWork.model_validate(value)


def test_rights_are_actual_uploader_attestation_not_purchased_license():
    value = {
        "schema_version": "material-learning-rights/1.0",
        "material_id": "material_" + "5" * 32,
        "material_revision_id": "materialrev_" + "6" * 32,
        "attested_by": "actual-uploader",
        "attested_at": "2026-11-05T18:00:00Z",
        "basis": "UPLOADER_ATTESTED_INTERNAL_PROCESSING",
        "source_hashes": [HASH],
        "permitted_uses": list(PERMITTED_USES),
        "public_redistribution_permitted": False,
        "withdrawal_policy": "DENY_NEW_RESOLUTION_PRESERVE_PINNED_AUDIT",
    }
    rehash(value, "attestation_sha256")
    assert MaterialLearningRights.model_validate(value).attested_by == "actual-uploader"
    value["basis"] = "PURCHASED_AND_NEGOTIATED"
    rehash(value, "attestation_sha256")
    with pytest.raises((ValidationError, SchemaError)):
        MaterialLearningRights.model_validate(value)


def test_upload_accepts_optional_hints_but_requires_explicit_rights():
    value = {
        "schema_version": "material-learning-upload/1.0",
        "title": "참고서",
        "material_kind": "WORKBOOK",
        "source_description": "내부 승인 자료",
        "additional_instructions": "",
        "curriculum_unit_hints": [],
        "rights_confirmed": True,
    }
    assert MaterialLearningUpload.model_validate(value).material_kind == "WORKBOOK"
    value["rights_confirmed"] = False
    with pytest.raises(ValidationError):
        MaterialLearningUpload.model_validate(value)


@pytest.mark.parametrize(
    "name",
    [
        "types",
        "upload",
        "rights",
        "discovery-work",
        "discovery-result",
        "extraction-work",
        "extraction-result",
    ],
)
def test_installed_schema_bytes_equal_canonical_protocol(name):
    filename = f"material-learning-{name}-v1.schema.json"
    assert (ROOT / "schemas/material-learning" / filename).read_bytes() == (
        ROOT
        / "packages/catalog_contracts/eom_catalog_contracts/resources/material-learning"
        / filename
    ).read_bytes()
