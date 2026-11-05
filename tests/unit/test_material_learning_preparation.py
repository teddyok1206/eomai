"""Long books have complete bounded chunks, exact original pointers and no fake license."""

from copy import deepcopy

import pytest
from eom_catalog_contracts.material_learning_preparation import (
    MaterialDocumentRevision,
    MaterialPageBundle,
    MaterialPageChunk,
    MaterialPreparationInput,
)
from eom_workflow.material_learning_state import (
    MaterialTaskKind,
    MaterialTaskState,
    require_material_task_transition,
)
from pydantic import ValidationError

from tests.unit.test_material_learning_contracts import HASH, member, rehash


def profile():
    return rehash(
        {
            "schema_version": "material-learning-preparation-profile/1.0",
            "source_commit": "1" * 40,
            "extractor": {
                "implementation": "synthetic",
                "version": "1.0",
                "implementation_sha256": HASH,
                "options_sha256": HASH,
            },
            "office_tool_source_commit": None,
            "libreoffice_sha256": None,
            "h2orestart_sha256": None,
            "maximum_pages": 2000,
            "maximum_rendered_bytes": 4 * 1024 * 1024 * 1024,
            "chunk_page_limit": 128,
            "chunk_soft_bytes": 256 * 1024 * 1024,
        },
        "profile_sha256",
    )


def chunk(first=1, last=2):
    return {
        "schema_version": "material-learning-page-chunk/1.0",
        "document_id": "edudoc_" + "1" * 32,
        "document_revision_id": "edudocrev_" + "2" * 32,
        "source_role": "MAIN",
        "pdf_sha256": HASH,
        "profile_sha256": profile()["profile_sha256"],
        "first_physical_page": first,
        "last_physical_page": last,
        "pages": [
            {
                "physical_page": number,
                "text": {
                    "member_path": f"analysis/pages/page-{number:06d}.md",
                    "schema_ref": "eom://schemas/material-learning/page-text/1.0",
                    "media_type": "text/markdown",
                    "sha256": HASH,
                    "bytes": 100,
                },
                "image": {
                    "member_path": f"analysis/images/page-{number:06d}.png",
                    "schema_ref": "eom://schemas/educational-document/page-image/1.0",
                    "media_type": "image/png",
                    "sha256": HASH,
                    "bytes": 200,
                },
                "width_pixels": 1000,
                "height_pixels": 1400,
                "render_dpi": 180,
            }
            for number in range(first, last + 1)
        ],
    }


def bundle():
    pdf = member(schema="educational-document/pdf-source/1.0")
    chunks = []
    for number, (first, last) in enumerate(((1, 128), (129, 256), (257, 300)), 1):
        pointer = member(
            "analysis/chunk.json", "application/json", "material-learning/page-chunk/1.0"
        )
        pointer["artifact_id"] = "artifact_" + str(number) * 32
        pointer["artifact_revision_id"] = "rev_" + str(number) * 32
        chunks.append(
            {
                "manifest": pointer,
                "first_physical_page": first,
                "last_physical_page": last,
                "content_bytes": (last - first + 1) * 300,
            }
        )
    return {
        "schema_version": "material-learning-page-bundle/1.0",
        "document_id": "edudoc_" + "1" * 32,
        "document_revision_id": "edudocrev_" + "2" * 32,
        "source_role": "MAIN",
        "original": pdf,
        "pdf": deepcopy(pdf),
        "conversion": {
            "conversion_kind": "IDENTITY_PDF",
            "review_pdf_sha256": HASH,
            "libreoffice_version": None,
            "libreoffice_sha256": None,
            "h2orestart_sha256": None,
        },
        "profile": profile(),
        "page_count": 300,
        "chunks": chunks,
        "office_catalog": None,
    }


def test_chunk_has_exact_physical_page_and_native_members():
    parsed = MaterialPageChunk.model_validate(chunk())
    assert [page.physical_page for page in parsed.pages] == [1, 2]
    value = chunk()
    value["pages"][0]["image"]["member_path"] = "analysis/images/page-000002.png"
    with pytest.raises(ValidationError, match="PAGE_MEMBER_MISMATCH"):
        MaterialPageChunk.model_validate(value)


def test_three_hundred_page_book_uses_three_pointer_chunks_not_one_giant_fileset():
    value = MaterialPageBundle.model_validate(bundle())
    assert len(value.chunks) == 3 and value.page_count == 300
    assert value.original == value.pdf


@pytest.mark.parametrize("mismatch", ["gap", "overlap", "duplicate", "count", "separate_pdf"])
def test_bundle_cannot_hide_missing_or_duplicate_pages(mismatch):
    value = bundle()
    if mismatch == "gap":
        value["chunks"][1]["first_physical_page"] += 1
    elif mismatch == "overlap":
        value["chunks"][1]["first_physical_page"] -= 1
    elif mismatch == "duplicate":
        value["chunks"][1]["manifest"] = deepcopy(value["chunks"][0]["manifest"])
    elif mismatch == "count":
        value["page_count"] += 1
    else:
        value["pdf"]["artifact_id"] = "artifact_" + "c" * 32
    with pytest.raises(ValidationError):
        MaterialPageBundle.model_validate(value)


def test_preparation_input_pins_profile_and_actual_intake():
    value = rehash(
        {
            "schema_version": "material-learning-preparation-input/1.0",
            "task_id": "materialtask_" + "3" * 32,
            "material_id": "material_" + "1" * 32,
            "material_revision_id": "materialrev_" + "2" * 32,
            "intake_manifest": member(
                "material/intake.json", "application/json", "material-learning/intake/1.0"
            ),
            "profile": profile(),
        }
    )
    parsed = MaterialPreparationInput.model_validate(value)
    assert parsed.profile.maximum_pages == 2000
    value["profile"]["source_commit"] = "2" * 40
    with pytest.raises(ValidationError, match="HASH_MISMATCH"):
        MaterialPreparationInput.model_validate(value)


def test_generic_textbook_does_not_fabricate_publisher_volume_or_purchased_license():
    value = rehash(
        {
            "schema_version": "material-learning-document-revision/1.0",
            "document_id": "edudoc_" + "1" * 32,
            "document_revision_id": "edudocrev_" + "2" * 32,
            "document_key": "material-test-main",
            "revision_number": 1,
            "previous_revision_id": None,
            "material_id": "material_" + "1" * 32,
            "material_revision_id": "materialrev_" + "2" * 32,
            "source_role": "MAIN",
            "document_kind": "TEXTBOOK",
            "source_class": "TEXTBOOK",
            "title": "업로드 교과서",
            "source_description": "사용자가 제공한 설명",
            "publisher_key": None,
            "curriculum_volume": None,
            "edition_label": None,
            "original": bundle()["original"],
            "source": bundle()["pdf"],
            "source_page_count": 300,
            "analysis_bundle_manifest": member(
                "analysis/manifest.json", "application/json", "material-learning/page-bundle/1.0"
            ),
            "rights_attestation": member(
                "rights/attestation.json", "application/json", "material-learning/rights/1.0"
            ),
            "registered_by": "operator_" + "1" * 32,
            "registered_at": "2026-11-05T00:00:00Z",
            "registration_request_sha256": HASH,
        },
        "document_revision_sha256",
    )
    parsed = MaterialDocumentRevision.model_validate(value)
    assert parsed.publisher_key is None and parsed.curriculum_volume is None


def test_preparation_task_does_not_use_codex_lane():
    require_material_task_transition(
        MaterialTaskState.PREPARING, MaterialTaskState.RESULT_READY, kind=MaterialTaskKind.PREPARE
    )
    require_material_task_transition(
        MaterialTaskState.RESULT_READY, MaterialTaskState.COMPLETED, kind=MaterialTaskKind.PREPARE
    )
    with pytest.raises(ValueError):
        require_material_task_transition(
            MaterialTaskState.PREPARING,
            MaterialTaskState.RESULT_READY,
            kind=MaterialTaskKind.QUESTION,
        )
    with pytest.raises(ValueError):
        require_material_task_transition(
            MaterialTaskState.PREPARING, MaterialTaskState.RUNNING, kind=MaterialTaskKind.PREPARE
        )
