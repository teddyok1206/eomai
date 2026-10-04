"""Reviewed source regions are CPU data derivatives, not model-quality approval."""

from __future__ import annotations

import copy
import hashlib
import io
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_image_contracts import (
    SCHEMA_SHA256,
    SCIENCE_ORIGINAL_PAGE_SCHEMA_REF,
    SOURCE_PAGE_CROP_REVIEW_V3_SCHEMA_REF,
    SOURCE_PAGE_CROP_SET_V3_SCHEMA_REF,
    ImageEvaluationArtifactMember,
    LocalImageScienceSourcePageCropReview,
    LocalImageScienceSourcePageCropReviewV3,
    LocalImageScienceSourcePageCropSetV3,
    content_sha256,
    load_schema,
    source_page_crop_pointer,
    source_page_crop_protocol,
    source_page_crop_selection_id,
    validate_contract,
    validate_source_page_crop_set,
    validate_source_page_region_sources,
)
from eom_orchestrator import source_page_crop_inputs as admission
from eom_orchestrator import source_page_crop_publication as publication
from eom_orchestrator.control_artifact_resolution import ControlArtifactResolutionError
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.source_page_crop_processing import (
    ScienceSourcePageCropPixels,
    process_source_page_crops,
)
from jsonschema import Draft202012Validator
from jsonschema import ValidationError as JsonSchemaValidationError
from PIL import Image
from PIL import __version__ as pillow_version
from pydantic import ValidationError

from tests.unit.test_science_source_page_crop_expansion import (
    _reader as supplemental_reader,
)
from tests.unit.test_science_source_page_crop_expansion import (
    _review as supplemental_review,
)
from tests.unit.test_science_source_page_crop_expansion import expanded  # noqa: F401
from tests.unit.test_science_source_page_crops import (
    _cpu_shim,
    _crop_set,
    _fixture_review,
    _page,
    _seal_review,
)


def _sha(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _region_review(monkeypatch, partition="VALIDATION"):
    original, lineage, reader = _fixture_review(monkeypatch, count=1)
    value = original.model_dump(mode="json")
    selection = value["selections"][0]
    selection.pop("candidate_id")
    selection.pop("parent_candidate_sha256")
    selection["source_anchor"] = "REVIEWED_ORIGINAL_PAGE"
    for plan, result, pilot in zip(
        lineage.plans, lineage.results, lineage.inventory.pilot_results, strict=True
    ):
        sources = {source.document_id: source for source in plan.selected_sources}
        matched = next(
            (
                page
                for page in result.page_images
                if sources[page.document_id].partition == partition
            ),
            None,
        )
        if matched is None:
            continue
        source = sources[matched.document_id]
        selection.update(
            document_id=source.document_id,
            physical_page=matched.physical_page,
            source_document=source.pdf.model_dump(mode="json"),
            source_page={
                **pilot.pilot_result.model_dump(mode="json"),
                "schema_ref": SCIENCE_ORIGINAL_PAGE_SCHEMA_REF,
                "member_path": matched.member_path,
                "media_type": "image/png",
                "sha256": matched.sha256,
            },
            page_width_px=matched.width_px,
            page_height_px=matched.height_px,
            pixel_box=[0, 0, 64, 64],
            exam_group_sha256=source.exam_group_sha256,
            partition=partition,
        )
        break
    else:
        pytest.fail("fixture has no source page in requested partition")
    selection["selection_id"] = source_page_crop_selection_id(selection)
    value.update(
        schema_version="local-image-science-source-page-crop-review/1.2", supplemental_pilots=[]
    )
    return (
        LocalImageScienceSourcePageCropReviewV3.model_validate(_seal_review(value)),
        lineage,
        reader,
    )


def _region_set(review):
    value = _crop_set(review).model_dump(mode="json")
    value["schema_version"] = "local-image-science-source-page-crop-set/1.2"
    value["review"]["schema_ref"] = SOURCE_PAGE_CROP_REVIEW_V3_SCHEMA_REF
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
    return LocalImageScienceSourcePageCropSetV3.model_validate(value)


def test_schema_packaging_and_reviewed_region_provenance(monkeypatch):
    review, _lineage, _reader = _region_review(monkeypatch)
    crop_set = _region_set(review)
    validate_source_page_crop_set(review, crop_set)
    assert source_page_crop_protocol(review).set_model is LocalImageScienceSourcePageCropSetV3
    root = Path(__file__).resolve().parents[2]
    for kind, model in (("review", review), ("set", crop_set)):
        contract = "science-source-page-crop-" + kind + "-v3"
        filename = "local-image-" + contract + ".schema.json"
        validate_contract(contract, model.model_dump(mode="json"))
        Draft202012Validator.check_schema(load_schema(contract))
        raw = (root / "schemas/image-provider" / filename).read_bytes()
        assert (
            raw
            == (
                root / "packages/image_contracts/eom_image_contracts/schemas" / filename
            ).read_bytes()
        )
        assert _sha(raw) == SCHEMA_SHA256[contract]
        for script in ("image_provider", "image_trainer"):
            assert filename in (root / "scripts" / script / "build_release.sh").read_text()
    pointer = ImageEvaluationArtifactMember.model_validate(
        {
            **crop_set.review.model_dump(mode="json"),
            "schema_ref": SOURCE_PAGE_CROP_SET_V3_SCHEMA_REF,
        }
    )
    assert source_page_crop_pointer(pointer, crop_set.members[0]).schema_ref.endswith(
        "visual-crop/1.0"
    )


@pytest.mark.parametrize("partition", ["TRAIN", "VALIDATION", "HOLDOUT"])
def test_existing_partition_is_preserved_without_detected_candidate(monkeypatch, partition):
    review, _lineage, reader = _region_review(monkeypatch, partition)
    reads = admission.prepare_source_page_crop_reads(object(), review)
    assert len(reads) == 1 and reads[0].selections == review.selections
    assert reads[0].selections[0].partition == partition
    assert all(pointer.media_type == "application/json" for pointer in reader.calls)
    assert "candidate_id" not in review.selections[0].model_dump()
    assert admission.prepare_source_page_crop_reads(object(), review) == reads


@pytest.mark.parametrize(
    "field,updated",
    [
        ("partition", "TRAIN"),
        ("exam_group_sha256", "sha256:" + "f" * 64),
        ("page_width_px", 1192),
        ("source_document", {"sha256": "sha256:" + "f" * 64}),
        ("source_page", {"artifact_revision_id": "rev_" + "f" * 32}),
        ("source_page", {"sha256": "sha256:" + "f" * 64}),
        ("physical_page", 9),
    ],
)
def test_wrong_region_metadata_is_rejected_before_pixels(monkeypatch, field, updated):
    review, _lineage, _reader = _region_review(monkeypatch)
    value = review.model_dump(mode="json")
    selection = value["selections"][0]
    if isinstance(updated, dict):
        selection[field].update(updated)
    else:
        selection[field] = updated
    if field == "physical_page":
        selection["source_page"]["member_path"] = f"pages/{selection['document_id']}/page-9.png"
    selection["selection_id"] = source_page_crop_selection_id(selection)
    altered = LocalImageScienceSourcePageCropReviewV3.model_validate(_seal_review(value))
    monkeypatch.setattr(
        admission,
        "resolve_control_artifact_members",
        lambda *args: pytest.fail("premature pixel read"),
    )
    with pytest.raises(ValueError):
        admission.prepare_source_page_crop_reads(object(), altered)


@pytest.mark.parametrize("fault", ["missing", "stale", "hash"])
def test_original_lineage_errors_never_substitute_latest(monkeypatch, fault):
    review, _lineage, reader = _region_review(monkeypatch)
    if fault == "hash":
        reader.records[review.basis_crop_set] += b" "
    else:
        reader.records.pop(review.basis_crop_set)
    with pytest.raises(ControlArtifactResolutionError):
        admission.prepare_source_page_crop_reads(object(), review)


@pytest.mark.parametrize("fault", ["fake_parent", "wrong_anchor", "duplicate", "nonutc", "mask"])
def test_explicit_region_contract_does_not_accept_detector_or_repair_workarounds(
    monkeypatch, fault
):
    review, _lineage, _reader = _region_review(monkeypatch)
    value = review.model_dump(mode="json")
    if fault == "fake_parent":
        value["selections"][0]["candidate_id"] = "imgsciviscandidate_" + "f" * 32
    elif fault == "wrong_anchor":
        value["selections"][0]["source_anchor"] = "DETECTED_CANDIDATE"
    elif fault == "duplicate":
        value["selections"].append(copy.deepcopy(value["selections"][0]))
    elif fault == "nonutc":
        value["created_at"] = "2026-10-04T09:00:00+09:00"
    elif fault == "mask":
        value["selections"][0]["ocr_masks"] = []
    value = _seal_review(value)
    with pytest.raises((ValueError, ValidationError, JsonSchemaValidationError)):
        validate_contract("science-source-page-crop-review-v3", value)
        LocalImageScienceSourcePageCropReviewV3.model_validate(value)
    with pytest.raises(ValueError):
        LocalImageScienceSourcePageCropReview.model_validate(review.model_dump(mode="json"))


def test_same_page_regions_share_one_read_and_caption_is_revision_content(monkeypatch):
    review, _lineage, _reader = _region_review(monkeypatch)
    value = review.model_dump(mode="json")
    extra = copy.deepcopy(value["selections"][0])
    extra["pixel_box"] = [70, 0, 134, 64]
    extra["selection_id"] = source_page_crop_selection_id(extra)
    value["selections"].append(extra)
    expanded_review = LocalImageScienceSourcePageCropReviewV3.model_validate(_seal_review(value))
    reads = admission.prepare_source_page_crop_reads(object(), expanded_review)
    assert len(reads) == 1 and len(reads[0].selections) == 2
    value = review.model_dump(mode="json")
    value["selections"][0]["expression"] = "RESTRAINED_TONE"
    successor = LocalImageScienceSourcePageCropReviewV3.model_validate(_seal_review(value))
    assert successor.selections[0].selection_id == review.selections[0].selection_id
    assert successor.review_sha256 != review.review_sha256


def test_reviewed_region_reuses_literal_cpu_worker_without_model_import(monkeypatch):
    review, _lineage, _reader = _region_review(monkeypatch)
    selection = review.selections[0]
    page, raw = _page(selection)
    _cpu_shim(monkeypatch)
    result = process_source_page_crops(raw, (selection,), pillow_version=pillow_version)
    assert len(result) == 1
    with Image.open(io.BytesIO(result[0].payload)) as actual:
        assert actual.mode == "RGB"
        assert actual.tobytes() == page.crop(selection.pixel_box).tobytes()


@pytest.mark.parametrize("fault", ["duplicate_page", "duplicate_document", "future_source"])
def test_page_index_refuses_conflicting_or_future_lineage(monkeypatch, fault):
    review, lineage, _reader = _region_review(monkeypatch)
    plans, results = list(lineage.plans), list(lineage.results)
    if fault == "duplicate_page":
        results[0] = results[0].model_copy(update={"page_images": results[0].page_images * 2})
    elif fault == "duplicate_document":
        plans[0] = plans[0].model_copy(update={"selected_sources": plans[0].selected_sources * 2})
    else:
        results[0] = results[0].model_copy(
            update={"completed_at": datetime(2026, 10, 5, tzinfo=UTC)}
        )
    with pytest.raises(ValueError):
        validate_source_page_region_sources(
            review,
            plans=tuple(plans),
            results=tuple(results),
            result_pointers=tuple(pilot.pilot_result for pilot in lineage.inventory.pilot_results),
        )


def test_complete_supplemental_lineage_and_original_pages_can_be_combined(
    monkeypatch,
    expanded,  # noqa: F811
):
    detected = supplemental_review(expanded)
    supplemental_reader(monkeypatch, expanded, detected)
    value = detected.model_dump(mode="json")
    value["schema_version"] = "local-image-science-source-page-crop-review/1.2"
    selection = value["selections"][0]
    selection.pop("candidate_id")
    selection.pop("parent_candidate_sha256")
    selection["source_anchor"] = "REVIEWED_ORIGINAL_PAGE"
    selection["pixel_box"] = [0, 0, 64, 64]
    selection["selection_id"] = source_page_crop_selection_id(selection)
    review = LocalImageScienceSourcePageCropReviewV3.model_validate(_seal_review(value))
    basis = SimpleNamespace(
        **vars(expanded.basis),
        results=tuple(
            SimpleNamespace(completed_at=review.created_at, page_images=()) for _ in range(3)
        ),
    )
    basis.inventory = SimpleNamespace(
        pilot_results=tuple(
            SimpleNamespace(
                pilot_plan=pilot.pilot_plan,
                pilot_result=ImageEvaluationArtifactMember.model_validate(
                    {
                        **expanded.pairs[index]["pilot_result"],
                        "artifact_revision_id": "rev_" + f"{9500 + index:032x}",
                    }
                ),
            )
            for index, pilot in enumerate(basis.inventory.pilot_results)
        )
    )
    monkeypatch.setattr(admission, "resolve_sdxl_training_sources", lambda *a, **kw: basis)
    reads = admission.prepare_source_page_crop_reads(object(), review)
    assert len(reads) == 1 and reads[0].selections == review.selections
    incomplete = review.model_dump(mode="json")
    incomplete["supplemental_pilots"] = incomplete["supplemental_pilots"][:1]
    with pytest.raises((ValueError, JsonSchemaValidationError)):
        validate_contract("science-source-page-crop-review-v3", _seal_review(incomplete))
        LocalImageScienceSourcePageCropReviewV3.model_validate(_seal_review(incomplete))


def test_same_publication_owner_commits_region_manifest_and_pixels(monkeypatch, tmp_path):
    review, _lineage, _reader = _region_review(monkeypatch)
    calls = []

    class Publisher:
        def __init__(self, *args):
            pass

        def publish(self, **arguments):
            ControlFileSetPublisher._request(object.__new__(ControlFileSetPublisher), **arguments)
            calls.append(arguments)
            members = {member.file_name: member for member in arguments["members"]}
            for member in members.values():
                assert _sha(member.source.read_bytes()) == member.sha256
            primary = members[arguments["primary_file"]]
            return SimpleNamespace(
                artifact_id="artifact_" + "1" * 32,
                artifact_revision_id="rev_" + "2" * 32,
                primary_file=primary.file_name,
                primary_sha256=primary.sha256,
            )

    def payloads(engine, reads):
        return iter((read, _page(read.selections[0])[1]) for read in reads)

    def process(raw, selections, **kwargs):
        result = []
        for selection in selections:
            page, _raw = _page(selection)
            crop = page.crop(selection.pixel_box)
            output = io.BytesIO()
            crop.save(output, format="PNG")
            result.append(
                ScienceSourcePageCropPixels(
                    selection.selection_id, output.getvalue(), 64, 64, "f" * 16
                )
            )
        return tuple(result)

    monkeypatch.setattr(publication, "ControlFileSetPublisher", Publisher)
    monkeypatch.setattr(publication, "iter_source_page_crop_payloads", payloads)
    result = publication.materialize_and_publish_source_page_crops(
        object(),
        object(),
        review,
        workspace=tmp_path / "regions",
        created_at=datetime(2026, 10, 4, 1, tzinfo=UTC),
        process=process,
    )
    assert len(calls) == 2 and isinstance(result.crop_set, LocalImageScienceSourcePageCropSetV3)
    validate_source_page_crop_set(review, result.crop_set)
    assert result.crop_set.state == "REVIEWED_SOURCE_DERIVATIVES"
    assert result.crop_set.activation_policy == "FORBIDDEN"
    assert calls[1]["members"][-1].media_type in {"application/json", "image/png"}
    with pytest.raises(ValueError, match="NOT_EXCLUSIVE"):
        publication.materialize_and_publish_source_page_crops(
            object(),
            object(),
            review,
            workspace=tmp_path / "regions",
            created_at=datetime(2026, 10, 4, 1, tzinfo=UTC),
            process=process,
        )
