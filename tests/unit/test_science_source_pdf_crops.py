"""Native source preparation contracts/admission; no live PDF rendering or model calls."""

from __future__ import annotations

import ast
import copy
import hashlib
from dataclasses import replace
from pathlib import Path

import pytest
from eom_image_contracts import ImageEvaluationArtifactMember, content_json_bytes, content_sha256
from eom_image_contracts.source_page_crops import (
    LocalImageScienceSourcePageCropReview,
    LocalImageScienceSourcePageCropReviewV3,
    parse_source_page_crop_review,
    source_page_crop_protocol,
    source_page_crop_selection_id,
)
from eom_image_contracts.source_pdf_crops import (
    SOURCE_PDF_CROP_COMMAND_SCHEMA_REF,
    LocalImageScienceSourcePdfCropCommand,
    LocalImageScienceSourcePdfCropSet,
    native_source_pdf_crop_dimensions,
    select_native_source_pdf_regions,
    validate_native_source_pdf_crop_set,
)
from eom_image_contracts.validation import SCHEMA_SHA256, load_schema, validate_contract
from eom_orchestrator import source_pdf_crop_inputs as admission
from eom_orchestrator.control_artifact_resolution import ControlArtifactResolutionError
from jsonschema import ValidationError as SchemaError
from pydantic import ValidationError

from tests.unit.test_science_source_page_crops import _fixture_review, _seal_review
from tests.unit.test_science_source_page_regions import _region_review


def _sha(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _pointer(raw, schema, member, index=1):
    return ImageEvaluationArtifactMember(
        artifact_id="artifact_" + f"{index:032x}",
        artifact_revision_id="rev_" + f"{index + 1:032x}",
        member_path="manifests/" + member + ".json",
        schema_ref=schema,
        media_type="application/json",
        sha256=_sha(raw),
    )


def _seal_command(value):
    value = copy.deepcopy(value)
    value.pop("command_id", None)
    value.pop("command_sha256", None)
    value["command_id"] = "imgpdfcropcommand_" + content_sha256(value)[7:39]
    value["command_sha256"] = content_sha256(value)
    return value


def _command(review, renderer=None, *, selection_ids=None):
    raw = content_json_bytes(review.model_dump(mode="json"))
    return LocalImageScienceSourcePdfCropCommand.model_validate(
        _seal_command(
            {
                "schema_version": "local-image-science-source-pdf-crop-command/1.0",
                "created_at": "2026-10-04T15:00:00Z",
                "created_by": "fixture.operator",
                "source_commit": "a" * 40,
                "source_review": _pointer(
                    raw,
                    source_page_crop_protocol(review).review_schema_ref,
                    "science-source-page-crop-review",
                ).model_dump(mode="json"),
                "selection_ids": (
                    [selection.selection_id for selection in review.selections]
                    if selection_ids is None
                    else list(selection_ids)
                ),
                "render_dpi": 576,
                "renderer": renderer
                or {
                    "path": "/usr/bin/pdftoppm",
                    "version": "24.02.0",
                    "sha256": "sha256:" + "1" * 64,
                },
                "pillow_version": review.pillow_version,
                "policy": "PINNED_TRAIN_REVIEW_144_DPI_FRAME_RENDERED_AT_576_DPI/1.0",
                "activation_policy": "FORBIDDEN",
            }
        )
    )


def _set(command, review):
    pointer = _pointer(
        content_json_bytes(command.model_dump(mode="json")),
        SOURCE_PDF_CROP_COMMAND_SCHEMA_REF,
        "science-source-pdf-crop-command",
        10,
    )
    value = {
        "schema_version": "local-image-science-source-pdf-crop-set/1.0",
        "crop_set_id": "imgpdfcropset_"
        + content_sha256({"selection_ids": command.selection_ids})[7:39],
        "created_at": "2026-10-04T16:00:00Z",
        "command": pointer.model_dump(mode="json"),
        "command_sha256": command.command_sha256,
        "members": [
            {
                "selection_id": selection.selection_id,
                "member_path": "crops/" + selection.selection_id + ".png",
                "sha256": content_sha256({"fixture": selection.selection_id}),
                "size_bytes": 1024,
                "width_px": native_source_pdf_crop_dimensions(selection)[0],
                "height_px": native_source_pdf_crop_dimensions(selection)[1],
                "perceptual_hash": "0" * 16,
            }
            for selection in review.selections
            if selection.selection_id in command.selection_ids
        ],
        "state": "RENDERED_SOURCE_DERIVATIVES_PENDING_TARGET_REVIEW",
        "activation_policy": "FORBIDDEN",
    }
    return _seal_set(value), pointer


def _seal_set(value):
    value = copy.deepcopy(value)
    value.pop("crop_set_revision_id", None)
    value.pop("crop_set_sha256", None)
    value["crop_set_revision_id"] = "imgpdfcropsetrev_" + content_sha256(value)[7:39]
    value["crop_set_sha256"] = content_sha256(value)
    return LocalImageScienceSourcePdfCropSet.model_validate(value)


def test_contract_roundtrip_and_new_schema_hashes(monkeypatch):
    review, _lineage, _reader = _fixture_review(monkeypatch)
    command = _command(review)
    crop_set, pointer = _set(command, review)
    validate_native_source_pdf_crop_set(command, review, crop_set, command_pointer=pointer)
    for name, model in (
        ("science-source-pdf-crop-command", command),
        ("science-source-pdf-crop-set", crop_set),
    ):
        schema = load_schema(name)
        assert schema["$schema"].endswith("2020-12/schema")
        validate_contract(name, model.model_dump(mode="json"))
        assert (
            type(model).model_validate_json(content_json_bytes(model.model_dump(mode="json")))
            == model
        )
        path = (
            Path(__file__).resolve().parents[2]
            / "packages/image_contracts/eom_image_contracts/schemas"
        )
        filename = "local-image-" + name + "-v1.schema.json"
        assert _sha((path / filename).read_bytes()) == SCHEMA_SHA256[name]
        root = Path(__file__).resolve().parents[2]
        assert (root / "schemas/image-provider" / filename).read_bytes() == (
            path / filename
        ).read_bytes()
        for script in ("image_provider", "image_trainer"):
            assert filename in (root / "scripts" / script / "build_release.sh").read_text()
    assert not {"image_bytes", "pdf_bytes", "payload", "png"} & type(command).model_fields.keys()


@pytest.mark.parametrize(
    "change",
    [
        {"render_dpi": 144},
        {"render_dpi": 288},
        {"activation_policy": "ALLOWED"},
        {"selection_ids": []},
        {"selection_ids": ["bad"]},
        {"source_commit": "bad"},
        {"created_at": "2026-10-04T15:00:00+09:00"},
        {
            "renderer": {
                "path": "/usr/bin/tesseract",
                "version": "24.02.0",
                "sha256": "sha256:" + "1" * 64,
            }
        },
        {"arbitrary_worker_path": "/mnt/nas/private"},
    ],
)
def test_command_rejects_reinterpretation_and_unknown_fields(monkeypatch, change):
    review, _, _ = _fixture_review(monkeypatch)
    value = _command(review).model_dump(mode="json")
    value.update(change)
    with pytest.raises((ValidationError, ValueError)):
        LocalImageScienceSourcePdfCropCommand.model_validate(_seal_command(value))


def test_command_sorted_unique_ids_and_identity(monkeypatch):
    review, _, _ = _fixture_review(monkeypatch)
    command = _command(review)
    for ids in (list(reversed(command.selection_ids)), [command.selection_ids[0]] * 2):
        value = command.model_dump(mode="json")
        value["selection_ids"] = ids
        with pytest.raises(ValidationError):
            LocalImageScienceSourcePdfCropCommand.model_validate(_seal_command(value))
    value = command.model_dump(mode="json")
    value["command_id"] = "imgpdfcropcommand_" + "f" * 32
    with pytest.raises(ValidationError, match="identity/hash"):
        LocalImageScienceSourcePdfCropCommand.model_validate(value)


@pytest.mark.parametrize("partition", ["TRAIN", "VALIDATION", "HOLDOUT"])
def test_direct_page_regions_preserve_partition_and_forbid_reserved(monkeypatch, partition):
    review, _, _ = _region_review(monkeypatch, partition)
    command = _command(review)
    if partition == "TRAIN":
        assert select_native_source_pdf_regions(command, review) == review.selections
    else:
        with pytest.raises(ValueError, match="RESERVED_SOURCE_FORBIDDEN"):
            select_native_source_pdf_regions(command, review)


def test_missing_selection_and_wrong_review_hash_fail(monkeypatch):
    review, _, _ = _fixture_review(monkeypatch)
    value = _command(review).model_dump(mode="json")
    value["selection_ids"] = ["imgsourcecrop_" + "f" * 32]
    with pytest.raises(ValueError, match="SELECTION_MISSING"):
        select_native_source_pdf_regions(
            LocalImageScienceSourcePdfCropCommand.model_validate(_seal_command(value)), review
        )
    value = _command(review).model_dump(mode="json")
    value["source_review"]["sha256"] = "sha256:" + "f" * 64
    with pytest.raises(ValueError, match="REVIEW_HASH_MISMATCH"):
        select_native_source_pdf_regions(
            LocalImageScienceSourcePdfCropCommand.model_validate(_seal_command(value)), review
        )


def test_canonical_review_parser_rejects_hash_alias_latest_and_spacing(monkeypatch):
    review, _, _ = _fixture_review(monkeypatch)
    command = _command(review)
    raw = content_json_bytes(review.model_dump(mode="json"))
    assert parse_source_page_crop_review(command.source_review, raw) == review
    with pytest.raises(ValueError, match="POINTER_INVALID"):
        parse_source_page_crop_review(command.source_review, raw + b" ")
    pointer = command.source_review.model_copy(update={"sha256": _sha(raw + b" ")})
    with pytest.raises(ValueError, match="NONCANONICAL"):
        parse_source_page_crop_review(pointer, raw + b" ")
    pointer = command.source_review.model_copy(
        update={"schema_ref": "eom://schemas/image-provider/latest"}
    )
    with pytest.raises(ValueError, match="POINTER_INVALID"):
        parse_source_page_crop_review(pointer, raw)


def test_set_requires_exact_command_revision_and_native_dimensions(monkeypatch):
    review, _, _ = _fixture_review(monkeypatch)
    command = _command(review)
    crop_set, pointer = _set(command, review)
    wrong = pointer.model_copy(update={"artifact_revision_id": "rev_" + "f" * 32})
    with pytest.raises(ValueError, match="COMMAND_MISMATCH"):
        validate_native_source_pdf_crop_set(command, review, crop_set, command_pointer=wrong)
    value = crop_set.model_dump(mode="json")
    value["members"][0]["width_px"] -= 4
    with pytest.raises(ValueError, match="DIMENSIONS_MISMATCH"):
        validate_native_source_pdf_crop_set(
            command, review, _seal_set(value), command_pointer=pointer
        )


def test_duplicate_output_pixels_and_false_training_acceptance_rejected(monkeypatch):
    review, _, _ = _fixture_review(monkeypatch)
    crop_set, _ = _set(_command(review), review)
    value = crop_set.model_dump(mode="json")
    value["members"][1]["sha256"] = value["members"][0]["sha256"]
    with pytest.raises(ValidationError, match="repeats"):
        _seal_set(value)
    value = crop_set.model_dump(mode="json")
    value["state"] = "TRAINING_APPROVED"
    with pytest.raises(ValidationError):
        _seal_set(value)
    with pytest.raises(SchemaError):
        validate_contract("science-source-pdf-crop-set", value)


def test_metadata_first_admission_reuses_complete_lineage_without_png_reads(monkeypatch):
    review, _lineage, _reader = _fixture_review(monkeypatch)
    command = _command(review)
    raw = content_json_bytes(review.model_dump(mode="json"))
    calls = []

    def metadata(_engine, pointer, *, maximum_bytes):
        calls.append(pointer)
        assert pointer == command.source_review and pointer.media_type == "application/json"
        return raw

    monkeypatch.setattr(admission, "resolve_control_artifact_member", metadata)
    monkeypatch.setattr(
        admission,
        "resolve_control_artifact_members",
        lambda *_: pytest.fail("premature binary read"),
    )
    prepared = admission.prepare_source_pdf_crop_reads(object(), command)
    assert calls == [command.source_review]
    assert len(prepared.reads) == len({selection.document_id for selection in review.selections})
    assert all(read.source.partition == "TRAIN" for read in prepared.reads)
    assert {
        selection.selection_id for read in prepared.reads for selection in read.selections
    } == set(command.selection_ids)


@pytest.mark.parametrize(
    "code",
    [
        "CONTROL_ARTIFACT_MISSING",
        "CONTROL_ARTIFACT_HASH_MISMATCH",
        "CONTROL_ARTIFACT_REVISION_STALE",
    ],
)
def test_missing_stale_hash_source_refused_without_binary_lookup(monkeypatch, code):
    review, _, _ = _fixture_review(monkeypatch)

    def unavailable(*_args, **_kwargs):
        raise ControlArtifactResolutionError(code)

    monkeypatch.setattr(admission, "resolve_control_artifact_member", unavailable)
    monkeypatch.setattr(
        admission,
        "resolve_control_artifact_members",
        lambda *_: pytest.fail("premature binary read"),
    )
    with pytest.raises(ControlArtifactResolutionError, match=code):
        admission.prepare_source_pdf_crop_reads(object(), _command(review))


def test_indexed_pdf_batch_resolves_unique_documents_once(monkeypatch):
    review, _, _ = _fixture_review(monkeypatch)
    command = _command(review)
    monkeypatch.setattr(
        admission,
        "resolve_control_artifact_member",
        lambda *_a, **_k: content_json_bytes(review.model_dump(mode="json")),
    )
    prepared = admission.prepare_source_pdf_crop_reads(object(), command)
    calls = []

    def batch(_engine, reads):
        calls.append(reads)
        assert len({read.pointer for read in reads}) == len(reads)
        return tuple(b"x" * read.maximum_bytes for read in reads)

    monkeypatch.setattr(admission, "resolve_control_artifact_members", batch)
    assert len(tuple(admission.iter_source_pdf_crop_payloads(object(), prepared))) == len(
        prepared.reads
    )
    assert len(calls) == 1


@pytest.mark.parametrize("change", ["reserved", "duplicate", "oversized", "missing_selection"])
def test_binary_boundary_refuses_forged_or_unbounded_read_set(monkeypatch, change):
    review, _, _ = _fixture_review(monkeypatch)
    command = _command(review)
    monkeypatch.setattr(
        admission,
        "resolve_control_artifact_member",
        lambda *_a, **_k: content_json_bytes(review.model_dump(mode="json")),
    )
    prepared = admission.prepare_source_pdf_crop_reads(object(), command)
    reads = prepared.reads
    if change == "reserved":
        first = replace(
            reads[0], source=reads[0].source.model_copy(update={"partition": "HOLDOUT"})
        )
        reads = (first, *reads[1:])
    elif change == "oversized":
        first = replace(
            reads[0], source=reads[0].source.model_copy(update={"bytes": 64 * 1024**2 + 1})
        )
        reads = (first, *reads[1:])
    elif change == "duplicate":
        reads = (*reads, reads[0])
    else:
        reads = (replace(reads[0], selections=()), *reads[1:])
    monkeypatch.setattr(
        admission, "resolve_control_artifact_members", lambda *_: pytest.fail("premature PDF read")
    )
    with pytest.raises(ValueError, match="READS_INVALID"):
        tuple(admission.iter_source_pdf_crop_payloads(object(), replace(prepared, reads=reads)))


def test_native_pixel_budget_counts_all_rectangles_not_just_each_dimension(monkeypatch):
    review, _, _ = _region_review(monkeypatch, "TRAIN")
    value = review.model_dump(mode="json")
    original = value["selections"][0]
    value["selections"] = []
    for left in range(3):
        selection = copy.deepcopy(original)
        selection.update(page_width_px=2000, page_height_px=2000)
        selection["pixel_box"] = [left, 0, left + 1024, 1024]
        selection["selection_id"] = source_page_crop_selection_id(selection)
        value["selections"].append(selection)
    changed = LocalImageScienceSourcePageCropReviewV3.model_validate(_seal_review(value))
    with pytest.raises(ValueError, match="PIXEL_BUDGET_EXCEEDED"):
        select_native_source_pdf_regions(_command(changed), changed)


def test_frame_dimensions_and_original_page_edge_are_bounded(monkeypatch):
    review, _, _ = _fixture_review(monkeypatch, count=1)
    value = review.model_dump(mode="json")
    selection = value["selections"][0]
    selection["pixel_box"] = [0, 0, selection["page_width_px"], 128]
    selection["selection_id"] = source_page_crop_selection_id(selection)
    changed = LocalImageScienceSourcePageCropReview.model_validate(_seal_review(value))
    with pytest.raises(ValueError, match=r"DIMENSIONS_INVALID|PAGE_EDGE_UNSUPPORTED"):
        select_native_source_pdf_regions(_command(changed), changed)


def test_native_contract_module_keeps_dependency_direction():
    path = (
        Path(__file__).resolve().parents[2]
        / "packages/image_contracts/eom_image_contracts/source_pdf_crops.py"
    )
    tree = ast.parse(path.read_text())
    modules = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    modules += [
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    ]
    assert not any(
        module.startswith(
            (
                "sqlalchemy",
                "subprocess",
                "pathlib",
                "os",
                "eom_orchestrator",
                "eom_catalog_service",
                "torch",
            )
        )
        for module in modules
    )
