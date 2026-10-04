"""Synthetic page crops test provenance/pixels, not exam illustration quality."""

from __future__ import annotations

import copy
import hashlib
import io
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_image_contracts import (
    SCHEMA_SHA256,
    SCIENCE_ORIGINAL_PAGE_SCHEMA_REF,
    SOURCE_PAGE_CROP_REVIEW_SCHEMA_REF,
    SOURCE_PAGE_CROP_SET_SCHEMA_REF,
    ImageEvaluationArtifactMember,
    LocalImageScienceSourcePageCropReview,
    LocalImageScienceSourcePageCropSet,
    StyleDatasetSample,
    content_json_bytes,
    content_sha256,
    load_schema,
    source_page_crop_pointer,
    source_page_crop_selection_id,
    text_sha256,
    validate_contract,
    validate_source_page_crop_set,
)
from eom_orchestrator import sdxl_probe_inputs as original_inputs
from eom_orchestrator import source_page_crop_inputs as admission
from eom_orchestrator import source_page_crop_processing as processing
from eom_orchestrator import source_page_crop_publication as publication
from eom_orchestrator.control_artifact_resolution import ControlArtifactResolutionError
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.file_set_control_artifacts import (
    ControlFileSetMember,
    ControlFileSetPublisher,
)
from jsonschema import Draft202012Validator
from PIL import Image, ImageDraw
from PIL import __version__ as pillow_version
from pydantic import ValidationError

from tests.unit.test_sdxl_probe_inputs import _fixture, _Reader


def _sha(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _seal_review(value):
    value["selections"].sort(key=lambda item: item["selection_id"])
    value["review_id"] = (
        "imgsourcecropreview_"
        + content_sha256(
            {key: item for key, item in value.items() if key not in {"review_id", "review_sha256"}}
        )[7:39]
    )
    value["review_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "review_sha256"}
    )
    return value


def _fixture_review(monkeypatch, count=2):
    _command, policy, records = _fixture()
    reader = _Reader(records)
    monkeypatch.setattr(original_inputs, "resolve_control_artifact_member", reader)
    crop_pointer = ImageEvaluationArtifactMember.model_validate(policy["crop_set"])
    auth_pointer = ImageEvaluationArtifactMember.model_validate(policy["training_authorization"])
    lineage = original_inputs.resolve_sdxl_training_sources(
        object(), crop_set_pointer=crop_pointer, authorization_pointer=auth_pointer
    )
    candidates = {
        candidate.candidate_id: (candidate, result, pilot)
        for result, pilot in zip(lineage.results, lineage.inventory.pilot_results, strict=True)
        for candidate in result.visual_candidates
    }
    sources = {
        source.document_id: source for plan in lineage.plans for source in plan.selected_sources
    }
    entries = []
    for member in [item for item in lineage.crop_set.members if item.partition == "TRAIN"][:count]:
        candidate, result, pilot = candidates[member.parent_candidate_id]
        page = next(
            page
            for page in result.page_images
            if page.document_id == member.document_id and page.physical_page == member.physical_page
        )
        value = {
            "candidate_id": candidate.candidate_id,
            "parent_candidate_sha256": candidate.sha256,
            "document_id": member.document_id,
            "physical_page": member.physical_page,
            "source_document": sources[member.document_id].pdf.model_dump(mode="json"),
            "source_page": {
                **pilot.pilot_result.model_dump(mode="json"),
                "member_path": page.member_path,
                "schema_ref": SCIENCE_ORIGINAL_PAGE_SCHEMA_REF,
                "media_type": "image/png",
                "sha256": page.sha256,
            },
            "page_width_px": page.width_px,
            "page_height_px": page.height_px,
            "page_render_dpi": 144,
            "pixel_box": [150, 210, 420, 490],
            "exam_group_sha256": member.exam_group_sha256,
            "partition": "TRAIN",
            "depiction_key": "TEST_OBJECT",
            "caption_en": "A complete synthetic test object with no labels",
            "caption_sha256": text_sha256("A complete synthetic test object with no labels"),
            "expression": "CLEAN_CONTOUR",
        }
        value["selection_id"] = source_page_crop_selection_id(value)
        entries.append(value)
    review = LocalImageScienceSourcePageCropReview.model_validate(
        _seal_review(
            {
                "schema_version": "local-image-science-source-page-crop-review/1.0",
                "created_at": "2026-10-04T00:00:00Z",
                "created_by": "fixture.operator",
                "source_commit": "a" * 40,
                "basis_crop_set": crop_pointer.model_dump(mode="json"),
                "training_authorization": auth_pointer.model_dump(mode="json"),
                "selections": entries,
                "policy": "REVIEWED_LITERAL_ORIGINAL_PAGE_PIXELS/1.0",
                "pillow_version": pillow_version,
                "activation_policy": "FORBIDDEN",
            }
        )
    )
    return review, lineage, reader


def _crop_set(review):
    raw = content_json_bytes(review.model_dump(mode="json"))
    value = {
        "schema_version": "local-image-science-source-page-crop-set/1.0",
        "crop_set_id": "imgsourcecropset_"
        + content_sha256(
            {"selection_ids": tuple(selection.selection_id for selection in review.selections)}
        )[7:39],
        "created_at": "2026-10-04T01:00:00Z",
        "review": {
            "artifact_id": "artifact_" + "1" * 32,
            "artifact_revision_id": "rev_" + "2" * 32,
            "member_path": "manifests/science-source-page-crop-review.json",
            "schema_ref": SOURCE_PAGE_CROP_REVIEW_SCHEMA_REF,
            "media_type": "application/json",
            "sha256": _sha(raw),
        },
        "pillow_version": pillow_version,
        "members": [
            {
                "selection_id": selection.selection_id,
                "member_path": "crops/" + selection.selection_id + ".png",
                "sha256": "sha256:" + f"{index + 1:064x}",
                "size_bytes": 1024,
                "width_px": selection.pixel_box[2] - selection.pixel_box[0],
                "height_px": selection.pixel_box[3] - selection.pixel_box[1],
                "perceptual_hash": f"{index:016x}",
            }
            for index, selection in enumerate(review.selections)
        ],
        "state": "REVIEWED_SOURCE_DERIVATIVES",
        "activation_policy": "FORBIDDEN",
    }
    value["crop_set_revision_id"] = "imgsourcecropsetrev_" + content_sha256(value)[7:39]
    value["crop_set_sha256"] = content_sha256(value)
    return LocalImageScienceSourcePageCropSet.model_validate(value)


def test_schemas_hashes_packaging_and_existing_split_compatibility(monkeypatch):
    review, _lineage, _reader = _fixture_review(monkeypatch)
    crop_set = _crop_set(review)
    validate_source_page_crop_set(review, crop_set)
    root = Path(__file__).resolve().parents[2]
    for kind, model in (("review", review), ("set", crop_set)):
        name = "science-source-page-crop-" + kind
        validate_contract(name, model.model_dump(mode="json"))
        Draft202012Validator.check_schema(load_schema(name))
        filename = "local-image-" + name + "-v1.schema.json"
        raw = (root / "schemas/image-provider" / filename).read_bytes()
        assert (
            raw
            == (
                root / "packages/image_contracts/eom_image_contracts/schemas" / filename
            ).read_bytes()
        )
        assert _sha(raw) == SCHEMA_SHA256[name]
        assert filename in (root / "scripts/image_trainer/build_release.sh").read_text()
    pointer = ImageEvaluationArtifactMember.model_validate(
        {
            **crop_set.review.model_dump(mode="json"),
            "schema_ref": SOURCE_PAGE_CROP_SET_SCHEMA_REF,
        }
    )
    selection, member = review.selections[0], crop_set.members[0]
    sample = {
        "crop": source_page_crop_pointer(pointer, member).model_dump(mode="json"),
        "source_document": selection.source_document.model_dump(mode="json"),
        "exam_group_sha256": selection.exam_group_sha256,
        "near_duplicate_group_sha256": None,
        "depiction_key": selection.depiction_key,
    }
    sample["sample_id"] = "imgstylesample_" + content_sha256(sample)[7:39]
    StyleDatasetSample.model_validate(sample)


def test_full_lineage_admission_does_not_read_pixels_and_preserves_partition(monkeypatch):
    review, _lineage, reader = _fixture_review(monkeypatch)
    reads = admission.prepare_source_page_crop_reads(object(), review)
    assert len(reads) == 2
    assert all(pointer.media_type == "application/json" for pointer in reader.calls)
    assert all(selection.partition == "TRAIN" for read in reads for selection in read.selections)
    assert admission.prepare_source_page_crop_reads(object(), review) == reads


@pytest.mark.parametrize(
    "field,value",
    [
        ("candidate_id", "imgsciviscandidate_" + "f" * 32),
        ("parent_candidate_sha256", "sha256:" + "f" * 64),
        ("partition", "HOLDOUT"),
        ("exam_group_sha256", "sha256:" + "f" * 64),
        ("page_width_px", 1192),
        ("pixel_box", [0, 0, 64, 64]),
    ],
)
def test_metadata_drift_fails_before_any_pixel_or_publication(monkeypatch, field, value):
    review, _lineage, _reader = _fixture_review(monkeypatch, count=1)
    changed = review.model_dump(mode="json")
    changed["selections"][0][field] = value
    changed["selections"][0]["selection_id"] = source_page_crop_selection_id(
        changed["selections"][0]
    )
    altered = LocalImageScienceSourcePageCropReview.model_validate(_seal_review(changed))
    monkeypatch.setattr(
        admission, "resolve_control_artifact_members", lambda *args: pytest.fail("read pixels")
    )
    with pytest.raises(ValueError):
        admission.prepare_source_page_crop_reads(object(), altered)


@pytest.mark.parametrize("kind", ["missing", "stale", "hash"])
def test_immutable_metadata_resolution_error_is_not_recovered(monkeypatch, kind):
    review, _lineage, reader = _fixture_review(monkeypatch)
    if kind == "hash":
        reader.records[review.basis_crop_set] += b" "
    else:
        reader.records.pop(review.basis_crop_set)
    with pytest.raises(ControlArtifactResolutionError):
        admission.prepare_source_page_crop_reads(object(), review)


def test_corrected_caption_keeps_crop_identity_but_changes_review_revision(monkeypatch):
    review, _lineage, _reader = _fixture_review(monkeypatch, count=1)
    value = review.model_dump(mode="json")
    selection = value["selections"][0]
    selection["caption_en"] = "A telescope rather than a microscope"
    selection["caption_sha256"] = text_sha256(selection["caption_en"])
    successor = LocalImageScienceSourcePageCropReview.model_validate(_seal_review(value))
    assert successor.selections[0].selection_id == review.selections[0].selection_id
    assert successor.review_id != review.review_id
    assert _crop_set(successor).crop_set_id == _crop_set(review).crop_set_id
    assert _crop_set(successor).crop_set_revision_id != _crop_set(review).crop_set_revision_id


def test_same_page_selections_share_one_input_read(monkeypatch):
    review, _lineage, _reader = _fixture_review(monkeypatch, count=1)
    value = review.model_dump(mode="json")
    extra = copy.deepcopy(value["selections"][0])
    extra["pixel_box"] = [430, 210, 700, 490]
    extra["selection_id"] = source_page_crop_selection_id(extra)
    value["selections"].append(extra)
    expanded = LocalImageScienceSourcePageCropReview.model_validate(_seal_review(value))
    reads = admission.prepare_source_page_crop_reads(object(), expanded)
    assert len(reads) == 1 and len(reads[0].selections) == 2


@pytest.mark.parametrize("fault", ["coverage", "dimensions", "review_hash", "duplicate_pixels"])
def test_output_contract_rejects_incomplete_drift_and_duplicate_pixels(monkeypatch, fault):
    review, _lineage, _reader = _fixture_review(monkeypatch)
    value = _crop_set(review).model_dump(mode="json")
    if fault == "coverage":
        value["members"].pop()
        value["crop_set_id"] = (
            "imgsourcecropset_"
            + content_sha256(
                {"selection_ids": tuple(member["selection_id"] for member in value["members"])}
            )[7:39]
        )
    elif fault == "dimensions":
        value["members"][0]["width_px"] += 1
    elif fault == "review_hash":
        value["review"]["sha256"] = "sha256:" + "f" * 64
    elif fault == "duplicate_pixels":
        value["members"][1]["sha256"] = value["members"][0]["sha256"]
    value["crop_set_revision_id"] = (
        "imgsourcecropsetrev_"
        + content_sha256(
            {
                key: item
                for key, item in value.items()
                if key not in {"crop_set_revision_id", "crop_set_sha256"}
            }
        )[7:39]
    )
    value["crop_set_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "crop_set_sha256"}
    )
    with pytest.raises(ValueError):
        candidate = LocalImageScienceSourcePageCropSet.model_validate(value)
        validate_source_page_crop_set(review, candidate)


def test_materialized_pixel_dto_cannot_hide_invalid_media(monkeypatch):
    review, _lineage, _reader = _fixture_review(monkeypatch, count=1)
    with pytest.raises(ValueError, match="PIXELS_INVALID"):
        processing.ScienceSourcePageCropPixels(
            review.selections[0].selection_id, b"x" * 100, 270, 280, "f" * 16
        )


@pytest.mark.parametrize(
    "change", ["box", "caption_hash", "path", "duplicate", "mask", "timezone", "concentration"]
)
def test_strict_review_contract_rejects_invalid_recipe(monkeypatch, change):
    review, _lineage, _reader = _fixture_review(monkeypatch, count=1)
    value = review.model_dump(mode="json")
    selection = value["selections"][0]
    if change == "box":
        selection["pixel_box"] = [0, 0, 50000, 100]
    elif change == "caption_hash":
        selection["caption_en"] = "A different object"
    elif change == "path":
        selection["source_page"]["member_path"] = "crops/incorrect.png"
    elif change == "duplicate":
        value["selections"] *= 2
    elif change == "mask":
        selection["redaction_boxes"] = []
    elif change == "timezone":
        value["created_at"] = "2026-10-04T09:00:00+09:00"
    elif change == "concentration":
        for index in range(3):
            extra = copy.deepcopy(selection)
            extra["pixel_box"][0] += index + 1
            extra["selection_id"] = source_page_crop_selection_id(extra)
            value["selections"].append(extra)
    with pytest.raises((ValueError, ValidationError)):
        LocalImageScienceSourcePageCropReview.model_validate(_seal_review(value))


def test_batched_unique_page_materialization_and_hash_error(monkeypatch):
    review, _lineage, _reader = _fixture_review(monkeypatch)
    reads = admission.prepare_source_page_crop_reads(object(), review)
    calls = []

    def reader(engine, requests):
        calls.append(requests)
        return tuple(b"x" * request.maximum_bytes for request in requests)

    monkeypatch.setattr(admission, "resolve_control_artifact_members", reader)
    assert len(tuple(admission.iter_source_page_crop_payloads(object(), reads))) == 2
    assert len(calls) == 1 and len(calls[0]) == 2

    def rejected(*args):
        raise ControlArtifactResolutionError("CONTROL_ARTIFACT_HASH_MISMATCH")

    monkeypatch.setattr(admission, "resolve_control_artifact_members", rejected)
    with pytest.raises(ControlArtifactResolutionError):
        tuple(admission.iter_source_page_crop_payloads(object(), reads))
    with pytest.raises(ValueError):
        tuple(admission.iter_source_page_crop_payloads(object(), reads + reads))


def _page(selection):
    page = Image.new("RGB", (selection.page_width_px, selection.page_height_px), "white")
    draw = ImageDraw.Draw(page)
    left, top, right, bottom = selection.pixel_box
    draw.rectangle((left + 5, top + 5, right - 5, bottom - 5), outline="black", width=2)
    draw.line((left + 10, top + 10, right - 10, bottom - 10), fill=(90, 90, 90), width=2)
    output = io.BytesIO()
    page.save(output, format="PNG")
    return page, output.getvalue()


def _cpu_shim(monkeypatch):
    run = subprocess.run

    def invoke(arguments, **kwargs):
        assert arguments[:4] == ["/usr/sbin/runuser", "--user", "eom-image", "--"]
        assert arguments[4:7] == ["/srv/eom/conda/envs/eom-image-trainer/bin/python", "-I", "-c"]
        assert kwargs["env"]["CUDA_VISIBLE_DEVICES"] == ""
        assert not any("DATABASE" in key or "TOKEN" in key for key in kwargs["env"])
        kwargs["env"] = {**kwargs["env"], "PYTHONPATH": os.environ["PYTHONPATH"]}
        script = arguments[7] + "\nassert 'torch' not in sys.modules\n"
        return run([sys.executable, "-c", script, *arguments[8:]], **kwargs)

    monkeypatch.setattr(processing.subprocess, "run", invoke)


def test_cpu_literal_pixels_no_masks_resize_or_torch(monkeypatch):
    review, _lineage, _reader = _fixture_review(monkeypatch, count=1)
    selection = review.selections[0]
    page, raw = _page(selection)
    _cpu_shim(monkeypatch)
    outputs = processing.process_source_page_crops(raw, (selection,), pillow_version=pillow_version)
    assert len(outputs) == 1
    with Image.open(io.BytesIO(outputs[0].payload)) as output:
        assert output.mode == "RGB"
        assert output.tobytes() == page.crop(selection.pixel_box).tobytes()
    with pytest.raises(ValueError, match="PROCESSING_FAILED"):
        processing.process_source_page_crops(raw, (selection,), pillow_version="0.0.0")


@pytest.mark.parametrize(
    "fault", ["alpha", "wrong_dimensions", "white", "invalid_png", "timeout", "invalid_zip"]
)
def test_cpu_untrusted_source_and_output_fail_explicitly(monkeypatch, fault):
    review, _lineage, _reader = _fixture_review(monkeypatch, count=1)
    selection = review.selections[0]
    page, raw = _page(selection)
    _cpu_shim(monkeypatch)
    if fault in {"alpha", "wrong_dimensions", "white"}:
        page = (
            page.convert("RGBA")
            if fault == "alpha"
            else Image.new("RGB", (100, 100) if fault == "wrong_dimensions" else page.size, "white")
        )
        output = io.BytesIO()
        page.save(output, format="PNG")
        raw = output.getvalue()
    elif fault == "invalid_png":
        raw = b"x" * 100
    elif fault == "timeout":

        def timeout(*args, **kwargs):
            raise subprocess.TimeoutExpired("test", 30)

        monkeypatch.setattr(processing.subprocess, "run", timeout)
    elif fault == "invalid_zip":
        monkeypatch.setattr(
            processing.subprocess,
            "run",
            lambda *a, **k: SimpleNamespace(returncode=0, stdout=b"x" * 100),
        )
    with pytest.raises(ValueError):
        processing.process_source_page_crops(raw, (selection,), pillow_version=pillow_version)


def test_orchestrator_publication_owns_closure_and_partial_failure(monkeypatch, tmp_path):
    review, _lineage, _reader = _fixture_review(monkeypatch, count=1)
    _cpu_shim(monkeypatch)
    calls = []

    class Publisher:
        def __init__(self, engine, settings):
            pass

        def publish(self, **arguments):
            # Exercise the real receiver's pure preflight, not an accepting mock contract.
            ControlFileSetPublisher._request(object.__new__(ControlFileSetPublisher), **arguments)
            calls.append(arguments)
            members = {member.file_name: member for member in arguments["members"]}
            for member in members.values():
                raw = member.source.read_bytes()
                assert _sha(raw) == member.sha256 and len(raw) == member.bytes
            primary = members[arguments["primary_file"]]
            return SimpleNamespace(
                artifact_id="artifact_" + "1" * 32,
                artifact_revision_id="rev_" + "2" * 32,
                primary_file=primary.file_name,
                primary_sha256=primary.sha256,
            )

    monkeypatch.setattr(publication, "ControlFileSetPublisher", Publisher)

    def payloads(engine, reads):
        return iter((read, _page(read.selections[0])[1]) for read in reads)

    monkeypatch.setattr(publication, "iter_source_page_crop_payloads", payloads)
    result = publication.materialize_and_publish_source_page_crops(
        object(),
        object(),
        review,
        workspace=tmp_path / "success",
        created_at=datetime(2026, 10, 4, 1, tzinfo=UTC),
    )
    assert len(calls) == 2
    assert calls[0]["artifact_type"] == "control_local_image_science_source_page_crop_review"
    assert calls[1]["artifact_type"] == "control_local_image_science_source_page_crop_set"
    assert len(calls[0]["members"]) == 1 and len(calls[1]["members"]) == 2
    validate_source_page_crop_set(review, result.crop_set)
    assert result.crop_set.activation_policy == "FORBIDDEN"
    with pytest.raises(ValueError, match="NOT_EXCLUSIVE"):
        publication.materialize_and_publish_source_page_crops(
            object(),
            object(),
            review,
            workspace=tmp_path / "success",
            created_at=datetime(2026, 10, 4, 1, tzinfo=UTC),
        )

    def failed(*args, **kwargs):
        raise ValueError("test processor failed")

    before = len(calls)
    with pytest.raises(ValueError, match="processor failed"):
        publication.materialize_and_publish_source_page_crops(
            object(),
            object(),
            review,
            workspace=tmp_path / "failed",
            created_at=datetime(2026, 10, 4, 1, tzinfo=UTC),
            process=failed,
        )
    assert len(calls) == before + 1
    assert (tmp_path / "failed/manifests/science-source-page-crop-review.json").exists()
    assert not (tmp_path / "failed/manifests/science-source-page-crop-set.json").exists()


def test_invalid_control_namespace_is_rejected_before_job_state(monkeypatch, tmp_path):
    source = tmp_path / "example.json"
    raw = b"{}"
    source.write_bytes(raw)
    member = ControlFileSetMember(
        "manifests/example.json",
        source,
        _sha(raw),
        len(raw),
        "eom://schemas/image-provider/example/1.0",
        "application/json",
    )
    receiver = object.__new__(ControlFileSetPublisher)
    monkeypatch.setattr(receiver, "_load_or_create_job", lambda **kw: pytest.fail("created job"))
    with pytest.raises(ControlPlaneError, match="file-set input is invalid"):
        receiver.publish(
            members=(member,),
            primary_file="manifests/example.json",
            artifact_type="SCIENCE_SOURCE_PAGE_CROP_SET",
            manifest_version="science-source-page-crop-set-files/1.0",
            idempotency_key="source-page-crop-set:invalid-example",
            source_commit="a" * 40,
            created_at=datetime(2026, 10, 4, tzinfo=UTC),
        )
