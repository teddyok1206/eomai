"""Upload receipts bind actual media, uploader and immutable source members."""

from copy import deepcopy
from datetime import UTC, datetime

import pytest
from eom_catalog_contracts.material_learning_intake import (
    MATERIAL_SOURCE_FORMATS,
    CreateMaterialLearningCommand,
    MaterialSourceUploadCommand,
    MaterialSourceUploadManifest,
    MaterialSourceUploadReceipt,
)
from pydantic import ValidationError

from tests.unit.test_material_learning_contracts import HASH, member

ACTOR = "operator_" + "1" * 32


def source_receipt(source_format="PDF", actor=ACTOR):
    descriptor = MATERIAL_SOURCE_FORMATS[source_format]
    original = member(
        "source/original" + descriptor.suffix,
        descriptor.media_type,
        descriptor.schema_ref.removeprefix("eom://schemas/"),
    )
    return {
        "schema_version": "material-learning-source-receipt/1.0",
        "manifest": member(
            "material/source-upload-manifest.json",
            "application/json",
            "material-learning/source-manifest/1.0",
        ),
        "original": original,
        "uploaded_by": actor,
        "created_at": datetime(2026, 11, 5, tzinfo=UTC).isoformat(),
        "original_filename": "자료.hwp",
        "source_format": source_format,
    }


@pytest.mark.parametrize("source_format", ["PDF", "HWP", "HWPX"])
def test_receipt_and_intrinsic_manifest_preserve_detected_format(source_format):
    raw = source_receipt(source_format)
    receipt = MaterialSourceUploadReceipt.model_validate(raw)
    manifest = MaterialSourceUploadManifest(
        uploaded_by=ACTOR,
        original_filename=raw["original_filename"],
        source_format=source_format,
        rights_confirmed=True,
        original={
            key: value
            for key, value in raw["original"].items()
            if key not in {"artifact_id", "artifact_revision_id"}
        },
    )
    assert manifest.original.sha256 == receipt.original.sha256
    assert receipt.original_filename == "자료.hwp"
    assert "artifact_id" not in manifest.model_dump()["original"]


@pytest.mark.parametrize("field", ["artifact_id", "artifact_revision_id"])
def test_receipt_cannot_join_unrelated_artifacts(field):
    raw = source_receipt()
    raw["manifest"][field] = raw["manifest"][field].replace("2", "3").replace("1", "3")
    with pytest.raises(ValidationError, match="MATERIAL_LEARNING_SOURCE_RECEIPT_MISMATCH"):
        MaterialSourceUploadReceipt.model_validate(raw)


@pytest.mark.parametrize("rights", [False, 1, "true", None])
def test_upload_requires_explicit_boolean_attestation(rights):
    with pytest.raises(ValidationError):
        MaterialSourceUploadCommand(
            actor_id=ACTOR,
            original_filename="자료.pdf",
            source_format="PDF",
            media_type="application/pdf",
            content_length=100,
            sha256=HASH,
            rights_confirmed=rights,
            idempotency_key="material-source-1234",
        )


def create_command():
    return {
        "actor_id": ACTOR,
        "idempotency_key": "material-create-1234",
        "upload": {
            "title": "교재",
            "material_kind": "WORKBOOK",
            "source_description": "내부 교재",
            "additional_instructions": "",
            "curriculum_unit_hints": [],
            "rights_confirmed": True,
        },
        "sources": [{"source_role": "MAIN", "source_upload": source_receipt()}],
    }


def test_material_create_keeps_main_and_separate_solutions_in_order():
    raw = create_command()
    second = source_receipt()
    second["original"]["sha256"] = "sha256:" + "b" * 64
    raw["sources"].append({"source_role": "SOLUTIONS", "source_upload": second})
    command = CreateMaterialLearningCommand.model_validate(raw)
    assert tuple(source.source_role for source in command.sources) == ("MAIN", "SOLUTIONS")
    assert command.upload.material_kind == "WORKBOOK"


@pytest.mark.parametrize("mismatch", ["owner", "role", "duplicate"])
def test_create_rejects_forged_owner_or_role_or_duplicate_file(mismatch):
    raw = create_command()
    second = deepcopy(raw["sources"][0])
    second["source_role"] = "SOLUTIONS"
    if mismatch == "owner":
        second["source_upload"]["uploaded_by"] = "operator_" + "2" * 32
        second["source_upload"]["original"]["sha256"] = "sha256:" + "b" * 64
    elif mismatch == "role":
        second["source_role"] = "MAIN"
        second["source_upload"]["original"]["sha256"] = "sha256:" + "b" * 64
    raw["sources"].append(second)
    with pytest.raises(ValidationError):
        CreateMaterialLearningCommand.model_validate(raw)
