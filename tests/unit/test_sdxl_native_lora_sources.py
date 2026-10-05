"""Synthetic multi-batch source admission; no institution images or GPU/model calls."""

from __future__ import annotations

import copy
import hashlib
from dataclasses import replace

import pytest
from eom_image_contracts import (
    content_json_bytes,
    content_sha256,
    text_sha256,
)
from eom_image_contracts.sdxl_native_lora import (
    LocalImageSdxlNativeLoraCommand,
    SdxlNativeLoraConditioning,
)
from eom_image_contracts.sdxl_native_lora_sources import (
    SdxlNativeLoraMetadataAdmission,
    parse_sdxl_native_lora_sources,
    sdxl_native_lora_metadata_member_path,
)
from eom_image_contracts.sdxl_native_training_targets import (
    SDXL_NATIVE_TARGET_COMMAND_SCHEMA_REF,
    SDXL_NATIVE_TARGET_PNG_SCHEMA_REF,
    SDXL_NATIVE_TARGET_RESULT_SCHEMA_REF,
    LocalImageSdxlNativeTrainingTargetCommand,
    LocalImageSdxlNativeTrainingTargetResult,
    parse_sdxl_native_training_target_sources,
    sdxl_native_target_id,
    sdxl_native_target_placement,
)
from eom_image_contracts.sdxl_training_targets import sdxl_reviewed_target_caption
from eom_image_contracts.source_page_crops import (
    LocalImageScienceSourcePageCropReview,
    source_page_crop_selection_id,
)
from eom_image_contracts.source_pdf_crops import (
    SOURCE_PDF_CROP_COMMAND_SCHEMA_REF,
    SOURCE_PDF_CROP_SET_SCHEMA_REF,
    LocalImageScienceSourcePdfCropCommand,
)
from eom_image_contracts.validation import validate_contract
from eom_orchestrator import sdxl_native_lora_inputs as admission
from eom_orchestrator import source_page_crop_inputs as provenance
from eom_orchestrator.control_artifact_resolution import ControlArtifactResolutionError
from eom_orchestrator.sdxl_probe_inputs import SdxlProbeInputMember

from tests.unit.test_science_source_page_crops import _fixture_review, _seal_review
from tests.unit.test_science_source_pdf_crops import (
    _command,
    _pointer,
    _seal_set,
    _set,
)
from tests.unit.test_science_source_pdf_crops import (
    _seal_command as _seal_pdf_command,
)
from tests.unit.test_sdxl_native_lora_contracts import _command_value, _seal_command
from tests.unit.test_sdxl_training_targets import _seal as _seal_target_command


def _fixture(monkeypatch, variant=None, *, pixel_factory=None):
    review, basis, reader = _fixture_review(monkeypatch, count=12)
    special_ids = None
    if variant is not None:
        value = review.model_dump(mode="json")
        first = value["selections"][0]
        other = copy.deepcopy(first)
        if variant == "contained":
            other["pixel_box"] = [170, 230, 380, 450]
        elif variant == "disjoint":
            first["pixel_box"] = [150, 210, 270, 490]
            first["selection_id"] = source_page_crop_selection_id(first)
            other["pixel_box"] = [300, 210, 420, 490]
        elif variant == "pdf_alias":
            other["document_id"] = value["selections"][1]["document_id"]
            other["source_page"]["member_path"] = (
                f"pages/{other['document_id']}/page-{other['physical_page']}.png"
            )
        other["selection_id"] = source_page_crop_selection_id(other)
        value["selections"][1] = other
        special_ids = (first["selection_id"], other["selection_id"])
        review = LocalImageScienceSourcePageCropReview.model_validate(_seal_review(value))
    all_regions = {r.selection_id: r for r in review.selections}
    ordered = tuple(all_regions)
    if special_ids:
        rest = tuple(i for i in ordered if i not in special_ids)
        chunks = (
            tuple(sorted((special_ids[0], *rest[:5]))),
            tuple(sorted((special_ids[1], *rest[5:]))),
        )
    else:
        chunks = (ordered[:6], ordered[6:])
    records = {review.training_authorization: basis.authorization_payload}
    batches, training_samples, pixels = [], [], {}
    native_sets = []

    def record(value, schema, family, index):
        raw = content_json_bytes(value.model_dump(mode="json"))
        pointer = _pointer(raw, schema, family, index)
        records[pointer] = raw
        return pointer

    for batch_index, ids in enumerate(chunks):
        source_command_value = _command(review).model_dump(mode="json")
        source_command_value["selection_ids"] = list(ids)
        source_command = LocalImageScienceSourcePdfCropCommand.model_validate(
            _seal_pdf_command(source_command_value)
        )
        records[source_command.source_review] = content_json_bytes(review.model_dump(mode="json"))
        source_pointer = record(
            source_command,
            SOURCE_PDF_CROP_COMMAND_SCHEMA_REF,
            "science-source-pdf-crop-command",
            100 + batch_index,
        )
        crop_value = _set(_command(review), review)[0].model_dump(mode="json")
        crop_value.update(
            command=source_pointer.model_dump(mode="json"),
            command_sha256=source_command.command_sha256,
        )
        crop_value["members"] = [m for m in crop_value["members"] if m["selection_id"] in ids]
        crop_value["crop_set_id"] = "imgpdfcropset_" + content_sha256({"selection_ids": ids})[7:39]
        crop_set = _seal_set(crop_value)
        crop_pointer = record(
            crop_set,
            SOURCE_PDF_CROP_SET_SCHEMA_REF,
            "science-source-pdf-crop-set",
            200 + batch_index,
        )
        decisions = [
            {
                "sample_id": sid,
                "disposition": "PREPARE",
                "framing_box": {"left": 0, "top": 0, "right": 10000, "bottom": 10000},
                "redaction_boxes": [],
                "expression": ("CLEAN_CONTOUR", "RESTRAINED_TONE", "FINE_HATCHING")[i % 3],
                "canvas": ("SQUARE_1024", "PORTRAIT_768X1024", "LANDSCAPE_1024X768")[i % 3],
                "reviewed_caption_en": f"A complete synthetic physical object {sid[-8:]}",
            }
            for i, sid in enumerate(ids)
        ]
        target_command = LocalImageSdxlNativeTrainingTargetCommand.model_validate(
            _seal_target_command(
                {
                    "schema_version": "local-image-sdxl-training-target-command/1.2",
                    "created_at": "2026-10-04T17:00:00Z",
                    "created_by": "fixture.operator",
                    "source_commit": "a" * 40,
                    "source_crop_set": crop_pointer.model_dump(mode="json"),
                    "training_authorization": review.training_authorization.model_dump(mode="json"),
                    "decisions": decisions,
                    "policy": "REVIEWED_NATIVE_GRAY_RATIONAL_FIT_MARGIN32_NO_MASK/1.0",
                    "maximum_upscale_milli": 1500,
                    "pillow_version": review.pillow_version,
                    "purpose": "CPU_ONLY_TRAIN_TARGET_CANDIDATES",
                    "activation_policy": "FORBIDDEN",
                }
            )
        )
        sources = parse_sdxl_native_training_target_sources(
            target_command,
            crop_set_payload=records[crop_pointer],
            source_command_payload=records[source_pointer],
            review_payload=records[source_command.source_review],
            authorization_payload=basis.authorization_payload,
        )
        targets = []
        for source, decision in zip(sources.samples, target_command.decisions, strict=True):
            target_id = sdxl_native_target_id(target_command, source, decision)
            width = 768 if decision.canvas == "PORTRAIT_768X1024" else 1024
            height = 768 if decision.canvas == "LANDSCAPE_1024X768" else 1024
            payload = (
                pixel_factory(source.sample_id, width, height)
                if pixel_factory is not None
                else ("synthetic native pixels " + source.sample_id).encode()
            )
            pixels[target_id] = payload
            caption = sdxl_reviewed_target_caption(
                decision.reviewed_caption_en, decision.expression
            )
            placement = sdxl_native_target_placement(source, decision, maximum_upscale_milli=1500)
            target = {
                "sample_id": source.sample_id,
                "target_id": target_id,
                "source_crop_sha256": source.source_image.sha256,
                "member_path": f"targets/{target_id}.png",
                "sha256": "sha256:" + hashlib.sha256(payload).hexdigest(),
                "size_bytes": len(payload),
                "width_px": width,
                "height_px": height,
                "mode": "RGB",
                "training_caption_en": caption,
                "training_caption_sha256": text_sha256(caption),
                "placement": placement.model_dump(mode="json"),
            }
            target["target_revision_id"] = (
                "imgsdxltargetrev_"
                + content_sha256(
                    {
                        k: target[k]
                        for k in ("target_id", "sha256", "training_caption_sha256", "placement")
                    }
                )[7:39]
            )
            targets.append(target)
        result_value = {
            "schema_version": "local-image-sdxl-training-target-result/1.2",
            "run_id": target_command.run_id,
            "command_sha256": target_command.command_sha256,
            "source_snapshot_sha256": sources.snapshot_sha256,
            "state": "UNREVIEWED_TRAIN_TARGET_CANDIDATES",
            "activation_policy": "FORBIDDEN",
            "status": "SUCCEEDED",
            "error_code": None,
            "pillow_version": review.pillow_version,
            "prepared_targets": targets,
            "deferred_sample_ids": [],
            "started_at": "2026-10-04T17:01:00Z",
            "completed_at": "2026-10-04T17:02:00Z",
            "duration_ms": 1000,
        }
        result_value["result_sha256"] = content_sha256(result_value)
        target_result = LocalImageSdxlNativeTrainingTargetResult.model_validate(result_value)
        result_pointer = record(
            target_result,
            SDXL_NATIVE_TARGET_RESULT_SCHEMA_REF,
            "sdxl-training-target-result",
            300 + batch_index,
        )
        command_pointer = record(
            target_command,
            SDXL_NATIVE_TARGET_COMMAND_SCHEMA_REF,
            "sdxl-training-target-command",
            400 + batch_index,
        )
        batches.append(
            {
                "command": command_pointer.model_dump(mode="json"),
                "result": result_pointer.model_dump(mode="json"),
            }
        )
        native_sets.append(crop_set)
        for target, decision in zip(
            target_result.prepared_targets, target_command.decisions, strict=True
        ):
            region = all_regions[target.sample_id]
            conditioning = SdxlNativeLoraConditioning(
                literal_subject=decision.reviewed_caption_en,
                expression=decision.expression,
                composition="AUTHORED_SCENE" if len(training_samples) % 2 else "ISOLATED_ON_WHITE",
            )
            training_samples.append(
                {
                    "sample_id": target.sample_id,
                    "target_id": target.target_id,
                    "target_revision_id": target.target_revision_id,
                    "source_image": {
                        **result_pointer.model_dump(mode="json"),
                        "member_path": target.member_path,
                        "schema_ref": SDXL_NATIVE_TARGET_PNG_SCHEMA_REF,
                        "media_type": "image/png",
                        "sha256": target.sha256,
                    },
                    "source_document_id": region.document_id,
                    "exam_group_sha256": region.exam_group_sha256,
                    "canvas": decision.canvas,
                    "conditioning": conditioning.model_dump(mode="json"),
                    "training_caption_sha256": text_sha256(conditioning.training_caption_en),
                }
            )
    value = _command_value()
    value.update(
        target_batches=batches,
        training_samples=sorted(training_samples, key=lambda s: s["sample_id"]),
        training_authorization=review.training_authorization.model_dump(mode="json"),
        created_at="2026-10-04T18:00:00Z",
        reviewed_at="2026-10-04T17:40:00Z",
    )
    command = LocalImageSdxlNativeLoraCommand.model_validate(_seal_command(value))
    screening = b"Own synthetic full-cohort review; not independent review."
    value["screening_evidence"]["sha256"] = text_sha256(screening.decode())
    command = LocalImageSdxlNativeLoraCommand.model_validate(_seal_command(value))
    records[command.screening_evidence] = screening
    return command, records, pixels, review, basis, reader, tuple(native_sets)


def _staged_metadata(records):
    return {sdxl_native_lora_metadata_member_path(p): raw for p, raw in records.items()}


def test_multi_batch_sources_support_distinct_sets_one_cached_review_and_scene_derivatives(
    monkeypatch,
):
    command, records, _pixels, review, _basis, _reader, native_sets = _fixture(monkeypatch)
    assert len({s.crop_set_revision_id for s in native_sets}) == 2
    sources = parse_sdxl_native_lora_sources(command, _staged_metadata(records))
    assert len(sources.targets) == len(sources.regions) == 12
    assert len(sources.metadata_pointers) == len(records)
    assert sources.batches[0].sources.review is sources.batches[1].sources.review
    assert sources.batches[0].sources.review == review
    assert any(
        "authored scene" in sample.training_caption_en for sample in command.training_samples
    )
    assert len(
        {sdxl_native_lora_metadata_member_path(p) for p in sources.metadata_pointers}
    ) == len(records)


def test_canonical_owner_verifies_all_metadata_and_frozen_lineage_before_selected_pngs(monkeypatch):
    command, records, pixels, _review, _basis, reader, _sets = _fixture(monkeypatch)
    calls = []

    def read(_engine, reads):
        raw_members = []
        for bounded in reads:
            pointer = bounded.pointer
            calls.append(pointer.media_type)
            if pointer.media_type == "image/png":
                assert len(calls) > len(records) and "lineage" in calls
                raw_members.append(
                    pixels[pointer.member_path.removeprefix("targets/").removesuffix(".png")]
                )
            else:
                raw_members.append(records[pointer])
        return tuple(raw_members)

    original = admission.resolve_source_page_crop_provenance

    def lineage(engine, review, **kwargs):
        result = original(engine, review, **kwargs)
        calls.append("lineage")
        return result

    monkeypatch.setattr(admission, "resolve_control_artifact_members", read)
    monkeypatch.setattr(admission, "resolve_source_page_crop_provenance", lineage)
    prepared = admission.prepare_sdxl_native_lora_inputs(object(), command)
    assert calls.count("lineage") == 1
    assert calls.count("image/png") == 12
    assert calls.count("application/pdf") == 0
    assert all(p.media_type != "image/png" for p in reader.calls)
    hashes = admission.sdxl_native_lora_input_hashes(prepared)
    assert hashes == {f.member_path: f.sha256 for f in prepared.files}
    assert len(prepared.files) == len(records) + 13


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "hash",
        "noncanonical",
        "foreign",
        "schema",
        "media",
        "lifecycle",
        "permission",
        "stale",
    ],
)
def test_metadata_failures_consume_no_png_or_pdf_bytes(monkeypatch, fault):
    command, records, _pixels, _review, _basis, _reader, _sets = _fixture(monkeypatch)
    staged = _staged_metadata(records)
    if fault == "foreign":
        staged["inputs/metadata/unknown.json"] = b"{}"
        with pytest.raises(ValueError, match="FOREIGN_MEMBER"):
            parse_sdxl_native_lora_sources(command, staged)
        return
    pointer = command.target_batches[0].command
    if fault == "missing":
        records.pop(pointer)
    elif fault in {"hash", "noncanonical"}:
        records[pointer] = b"{}" if fault == "hash" else records[pointer] + b"\n"

    def read(_engine, reads):
        assert all(r.pointer.media_type != "image/png" for r in reads)
        if fault in {"schema", "media", "lifecycle", "permission", "stale"}:
            raise ControlArtifactResolutionError("CONTROL_ARTIFACT_" + fault.upper())
        try:
            return tuple(records[r.pointer] for r in reads)
        except KeyError as exc:
            raise ControlArtifactResolutionError("CONTROL_ARTIFACT_MEMBER_MISSING") from exc

    monkeypatch.setattr(admission, "resolve_control_artifact_members", read)
    with pytest.raises((ValueError, ControlArtifactResolutionError)):
        admission.prepare_sdxl_native_lora_inputs(object(), command)


@pytest.mark.parametrize(
    "fault",
    [
        "target_revision",
        "png_hash",
        "doc",
        "group",
        "canvas",
        "expression",
        "review_chronology",
        "png_budget",
    ],
)
def test_selected_target_bindings_cannot_be_reinterpreted_before_pixel_reads(monkeypatch, fault):
    command, records, _pixels, _review, _basis, _reader, _sets = _fixture(monkeypatch)
    value = command.model_dump(mode="json")
    sample = value["training_samples"][0]
    if fault == "target_revision":
        sample["target_revision_id"] = "imgsdxltargetrev_" + "f" * 32
    elif fault == "png_hash":
        sample["source_image"]["sha256"] = text_sha256("wrong PNG")
    elif fault == "doc":
        sample["source_document_id"] = "sciencedoc_" + "f" * 32
    elif fault == "group":
        sample["exam_group_sha256"] = text_sha256("different group")
    elif fault == "canvas":
        sample["canvas"] = (
            "PORTRAIT_768X1024" if sample["canvas"] != "PORTRAIT_768X1024" else "SQUARE_1024"
        )
    elif fault == "expression":
        conditioning = sample["conditioning"]
        conditioning["expression"] = (
            "FINE_HATCHING" if conditioning["expression"] != "FINE_HATCHING" else "CLEAN_CONTOUR"
        )
        sample["training_caption_sha256"] = text_sha256(
            SdxlNativeLoraConditioning.model_validate(conditioning).training_caption_en
        )
    elif fault == "review_chronology":
        value["reviewed_at"] = "2026-10-04T17:01:00Z"
    else:
        value["budget"]["maximum_input_png_bytes"] = 1
    altered = LocalImageSdxlNativeLoraCommand.model_validate(_seal_command(value))

    def read(_engine, reads):
        assert all(r.pointer.media_type != "image/png" for r in reads)
        return tuple(records[r.pointer] for r in reads)

    monkeypatch.setattr(admission, "resolve_control_artifact_members", read)
    with pytest.raises(ValueError):
        admission.prepare_sdxl_native_lora_inputs(object(), altered)


def test_cross_batch_contained_frame_is_not_an_independent_drawing(monkeypatch):
    command, records, *_ = _fixture(monkeypatch, "contained")
    with pytest.raises(ValueError, match="PHYSICAL_SOURCE_VARIANT_REUSED"):
        parse_sdxl_native_lora_sources(command, _staged_metadata(records))


def test_disjoint_actual_drawings_can_share_one_detector_candidate(monkeypatch):
    command, records, *_ = _fixture(monkeypatch, "disjoint")
    sources = parse_sdxl_native_lora_sources(command, _staged_metadata(records))
    assert len(sources.targets) == 12


def test_same_pdf_bytes_under_different_declared_documents_cannot_evade_caps(monkeypatch):
    command, records, *_ = _fixture(monkeypatch, "pdf_alias")
    with pytest.raises(ValueError, match="PDF_ALIAS_OR_POINTER_CONFLICT"):
        parse_sdxl_native_lora_sources(command, _staged_metadata(records))


def test_cached_basis_must_pin_same_artifact_revision_and_authorization(monkeypatch):
    _command, _records, _pixels, review, basis, _reader, _sets = _fixture(monkeypatch)
    monkeypatch.setattr(
        provenance,
        "resolve_sdxl_training_sources",
        lambda *_a, **_k: pytest.fail("cached root re-resolved"),
    )
    assert provenance.resolve_source_page_crop_provenance(object(), review, basis=basis).pdf_sources
    wrong = basis.crop_set_pointer.model_copy(update={"artifact_revision_id": "rev_" + "f" * 32})
    with pytest.raises(ValueError, match="CACHED_BASIS_POINTER_MISMATCH"):
        provenance.resolve_source_page_crop_provenance(
            object(), review, basis=replace(basis, crop_set_pointer=wrong)
        )


def test_cache_rejects_repeated_admission_and_incomplete_closure(monkeypatch):
    command, records, *_ = _fixture(monkeypatch)
    cache = SdxlNativeLoraMetadataAdmission(command)
    pointer = command.training_authorization
    cache.admit(pointer, records[pointer])
    with pytest.raises(ValueError, match="REPEATED_METADATA"):
        cache.admit(pointer, records[pointer])
    with pytest.raises(ValueError, match="CLOSURE_INCOMPLETE"):
        cache.validated_sources()


def test_conflicting_hash_declarations_for_one_immutable_member_fail_before_reads(monkeypatch):
    command, *_ = _fixture(monkeypatch)
    value = command.model_dump(mode="json")
    first = value["target_batches"][0]["command"]
    other = value["target_batches"][1]["command"]
    other.update(
        artifact_id=first["artifact_id"], artifact_revision_id=first["artifact_revision_id"]
    )
    command = LocalImageSdxlNativeLoraCommand.model_validate(_seal_command(value))
    with pytest.raises(ValueError, match="CONFLICTING_IMMUTABLE_POINTERS"):
        SdxlNativeLoraMetadataAdmission(command)


def test_shared_metadata_is_decoded_once_per_full_pointer(monkeypatch):
    from eom_image_contracts import sdxl_native_lora_sources as decoder

    command, records, *_ = _fixture(monkeypatch)
    original = decoder._decode_metadata
    calls = []

    def counted(pointer, raw):
        calls.append(pointer)
        return original(pointer, raw)

    monkeypatch.setattr(decoder, "_decode_metadata", counted)
    parse_sdxl_native_lora_sources(command, _staged_metadata(records))
    assert len(calls) == len(set(calls)) == len(records)


def test_metadata_total_byte_budget_is_applied_before_decoder(monkeypatch):
    from eom_image_contracts import sdxl_native_lora_sources as decoder

    command, records, *_ = _fixture(monkeypatch)
    pointer = command.training_authorization
    monkeypatch.setattr(decoder, "NATIVE_LORA_MAX_METADATA_TOTAL_BYTES", len(records[pointer]) - 1)
    monkeypatch.setattr(
        decoder, "_decode_metadata", lambda *args: pytest.fail("over-budget parsed")
    )
    with pytest.raises(ValueError, match="METADATA_TOTAL_BUDGET_EXCEEDED"):
        SdxlNativeLoraMetadataAdmission(command).admit(pointer, records[pointer])


def test_handoff_hashes_reject_foreign_missing_or_duplicated_inputs(monkeypatch):
    command, records, pixels, *_ = _fixture(monkeypatch)
    monkeypatch.setattr(
        admission,
        "resolve_control_artifact_members",
        lambda _e, reads: tuple(
            records[r.pointer]
            if r.pointer.media_type != "image/png"
            else pixels[r.pointer.member_path.removeprefix("targets/").removesuffix(".png")]
            for r in reads
        ),
    )
    prepared = admission.prepare_sdxl_native_lora_inputs(object(), command)
    validate_contract("sdxl-native-lora-command", command.model_dump(mode="json"))
    for files in (
        prepared.files[:-1],
        (*prepared.files, prepared.files[0]),
        (
            *prepared.files,
            SdxlProbeInputMember("unexpected.txt", text_sha256("unexpected"), b"unexpected"),
        ),
    ):
        with pytest.raises(ValueError):
            admission.sdxl_native_lora_input_hashes(replace(prepared, files=files))
