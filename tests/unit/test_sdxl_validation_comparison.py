"""Synthetic admission evidence, never an institution-style or GPU acceptance."""

from __future__ import annotations

import copy
import hashlib
import io
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
from eom_image_contracts.models import (
    ImageEvaluationArtifactMember,
    content_json_bytes,
    content_sha256,
    text_sha256,
)
from eom_image_contracts.sdxl_validation_comparison import (
    LocalImageSdxlValidationComparisonCommand,
    LocalImageSdxlValidationComparisonResult,
    parse_sdxl_validation_crop_source,
    validate_sdxl_validation_result,
    validate_sdxl_validation_sources,
)
from eom_image_contracts.source_page_crops import (
    SOURCE_PAGE_CROP_SET_V3_SCHEMA_REF,
    LocalImageScienceSourcePageCropReviewV3,
    LocalImageScienceSourcePageCropSetV3,
    source_page_crop_pointer,
    source_page_crop_selection_id,
)
from eom_image_contracts.validation import (
    SCHEMA_FILES,
    SCHEMA_SHA256,
    load_schema,
    validate_contract,
)
from eom_orchestrator import sdxl_canny_reference_inputs as anchor_admission
from eom_orchestrator import sdxl_validation_inputs as admission
from eom_orchestrator.control_artifact_resolution import ControlArtifactResolutionError
from eom_orchestrator.local_image_training_control_artifacts import (
    LocalImageTrainingControlArtifactPublisher,
)
from jsonschema import Draft202012Validator
from PIL import Image, ImageDraw
from pydantic import ValidationError

from tests.unit.test_local_image_training_control_artifacts import _Publisher
from tests.unit.test_science_source_page_crops import _seal_review
from tests.unit.test_sdxl_canny_reference import _fixture as _anchor_fixture


def _sha(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _seal(value):
    value = copy.deepcopy(value)
    value.pop("run_id", None)
    value.pop("command_sha256", None)
    value["run_id"] = "imgsdxlvalcmprun_" + content_sha256(value)[7:39]
    value["command_sha256"] = content_sha256(value)
    return value


def _seal_set(value):
    value = copy.deepcopy(value)
    value.pop("crop_set_revision_id", None)
    value.pop("crop_set_sha256", None)
    value["crop_set_id"] = (
        "imgsourcecropset_"
        + content_sha256({"selection_ids": tuple(row["selection_id"] for row in value["members"])})[
            7:39
        ]
    )
    value["crop_set_revision_id"] = "imgsourcecropsetrev_" + content_sha256(value)[7:39]
    value["crop_set_sha256"] = content_sha256(value)
    return value


def _png(index):
    image = Image.new("RGB", (64, 64), "white")
    ImageDraw.Draw(image).rectangle((8, 8, 30 + index, 50), outline="black")
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


def _fixture(tmp_path, monkeypatch, fault=None):
    anchor, reader, _trace, _leases = _anchor_fixture(tmp_path, monkeypatch)
    inherited = anchor_admission.resolve_sdxl_canny_reference_metadata(object(), anchor)
    metadata = {file.member_path: file.payload for file in inherited.files}
    import json

    training_review = json.loads(metadata["inputs/source-review.json"])
    at = anchor.created_at + timedelta(seconds=1)

    def pin(model, family, identity, version):
        raw = content_json_bytes(model.model_dump(mode="json"))
        pointer = ImageEvaluationArtifactMember(
            artifact_id="artifact_" + f"{identity:032x}",
            artifact_revision_id="rev_" + f"{identity:032x}",
            member_path="manifests/" + family + ".json",
            schema_ref="eom://schemas/image-provider/local-image-" + family + "/" + version,
            media_type="application/json",
            sha256=_sha(raw),
        )
        reader.records[pointer] = raw
        return pointer

    anchor_pin = pin(anchor, "sdxl-canny-reference-command", 900, "1.0")
    template = training_review["selections"][0]
    selections = []
    pixels = {}
    for index in range(12):
        row = copy.deepcopy(template)
        row.pop("candidate_id")
        row.pop("parent_candidate_sha256")
        row.update(
            source_anchor="REVIEWED_ORIGINAL_PAGE",
            document_id="sciencedoc_" + f"{1000 + index // 2:032x}",
            exam_group_sha256="sha256:" + f"{1000 + index // 2:064x}",
            partition="VALIDATION",
            physical_page=1,
            pixel_box=[index * 70, 0, index * 70 + 64, 64],
            depiction_key=f"TEST_OBJECT_{index:02d}",
        )
        row["source_document"].update(
            artifact_id="artifact_" + f"{1100 + index // 2:032x}",
            sha256="sha256:" + f"{1100 + index // 2:064x}",
        )
        row["source_page"]["member_path"] = f"pages/{row['document_id']}/page-1.png"
        row["source_page"]["artifact_id"] = "artifact_" + f"{1200 + index // 2:032x}"
        if index < 2 and fault in {"TRAIN", "HOLDOUT"}:
            row["partition"] = fault
        if index == 0 and fault == "training-document":
            row["document_id"] = template["document_id"]
            row["source_page"]["member_path"] = f"pages/{row['document_id']}/page-1.png"
        if index == 0 and fault == "training-pdf":
            row["source_document"] = copy.deepcopy(template["source_document"])
        if index == 0 and fault == "training-group":
            row["exam_group_sha256"] = template["exam_group_sha256"]
        row["selection_id"] = source_page_crop_selection_id(row)
        selections.append(row)
        pixels[row["selection_id"]] = _png(index)
    review_value = {
        key: value
        for key, value in training_review.items()
        if key not in {"supplemental_pilots", "review_id", "review_sha256"}
    }
    review_value.update(
        schema_version="local-image-science-source-page-crop-review/1.2",
        created_at=at.isoformat().replace("+00:00", "Z"),
        selections=selections,
        supplemental_pilots=[],
    )
    review = LocalImageScienceSourcePageCropReviewV3.model_validate(_seal_review(review_value))
    review_pin = pin(review, "science-source-page-crop-review", 901, "1.2")
    crop_set = LocalImageScienceSourcePageCropSetV3.model_validate(
        _seal_set(
            {
                "schema_version": "local-image-science-source-page-crop-set/1.2",
                "created_at": (at + timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
                "review": review_pin.model_dump(mode="json"),
                "pillow_version": review.pillow_version,
                "members": [
                    dict(
                        selection_id=row.selection_id,
                        member_path="crops/" + row.selection_id + ".png",
                        sha256=_sha(pixels[row.selection_id]),
                        size_bytes=len(pixels[row.selection_id]),
                        width_px=64,
                        height_px=64,
                        perceptual_hash=f"{index:016x}",
                    )
                    for index, row in enumerate(review.selections)
                ],
                "state": "REVIEWED_SOURCE_DERIVATIVES",
                "activation_policy": "FORBIDDEN",
            }
        )
    )
    set_pin = pin(crop_set, "science-source-page-crop-set", 902, "1.2")
    cases = []
    by_selection = {row.selection_id: row for row in review.selections}
    for member in crop_set.members:
        selection = by_selection[member.selection_id]
        pointer = source_page_crop_pointer(set_pin, member)
        reader.records[pointer] = pixels[member.selection_id]
        payload = dict(
            depiction_key=selection.depiction_key,
            reference_image=pointer.model_dump(mode="json"),
            reference_width_px=64,
            reference_height_px=64,
            prompt_en=(
                "A clean black scientific line drawing of a complete test object on white paper"
            ),
            negative_prompt_en="color, gray background, text, extra objects, photo, shading",
            seeds=[inherited.sources.spatial_sources.parent.seed],
        )
        payload["prompt_sha256"] = text_sha256(payload["prompt_en"])
        payload["negative_prompt_sha256"] = text_sha256(payload["negative_prompt_en"])
        payload["case_id"] = "imgsdxlcase_" + content_sha256(payload)[7:39]
        payload["staged_member_path"] = "inputs/" + payload["case_id"] + ".png"
        cases.append(
            dict(source_set_sha256=set_pin.sha256, selection_id=member.selection_id, case=payload)
        )
    cases.sort(key=lambda entry: entry["case"]["case_id"])
    command = LocalImageSdxlValidationComparisonCommand.model_validate(
        _seal(
            dict(
                schema_version="local-image-sdxl-validation-comparison-command/1.0",
                source_commit="a" * 40,
                created_at=(at + timedelta(seconds=2)).isoformat().replace("+00:00", "Z"),
                purpose="EVALUATION_ONLY_RESERVED_SPATIAL_DIAGNOSTIC",
                activation_policy="FORBIDDEN",
                experiment_partition="VALIDATION",
                configuration_role="NUMERICAL_CONFIGURATION_ONLY_NOT_CASE_AUTHORITY",
                configuration_anchor=anchor_pin.model_dump(mode="json"),
                crop_sources=[
                    dict(
                        review=review_pin.model_dump(mode="json"),
                        crop_set=set_pin.model_dump(mode="json"),
                    )
                ],
                cases=cases,
                seed=inherited.sources.spatial_sources.parent.seed,
                budget=dict(
                    maximum_duration_ms=60000,
                    maximum_peak_gpu_memory_bytes=16 * 1024**3,
                    maximum_outputs=32,
                ),
            )
        )
    )
    events = []
    monkeypatch.setattr(admission, "resolve_control_artifact_member", reader)
    monkeypatch.setattr(admission, "resolve_sdxl_canny_reference_metadata", lambda *args: inherited)

    def lineage(engine, checked):
        assert checked == review
        events.append("FULL_LINEAGE")
        if fault == "lineage":
            raise ValueError("original page hash or partition mismatch")
        return ()

    def binary(engine, reads):
        assert events == ["FULL_LINEAGE"]
        events.append("SELECTED_BINARIES")
        for read in reads:
            assert read.pointer not in {
                entry.case.reference_image
                for entry in inherited.sources.spatial_sources.parent.cases
            }
        return tuple(
            reader(engine, read.pointer, maximum_bytes=read.maximum_bytes) for read in reads
        )

    monkeypatch.setattr(admission, "prepare_source_page_crop_reads", lineage)
    monkeypatch.setattr(admission, "resolve_control_artifact_members", binary)
    reader.calls.clear()
    return command, reader, events


def test_metadata_first_admission_selected_crop_identity_and_no_training_pixels(
    tmp_path, monkeypatch
):
    command, reader, events = _fixture(tmp_path, monkeypatch)
    admitted = admission.resolve_sdxl_validation_metadata(object(), command)
    assert events == ["FULL_LINEAGE"]
    assert all(pointer.media_type == "application/json" for pointer in reader.calls)
    assert admission.sdxl_validation_metadata_hashes(admitted) == {
        file.member_path: file.sha256 for file in admitted.files
    }
    events.clear()
    prepared = admission.prepare_sdxl_validation_inputs(object(), command)
    assert events == ["FULL_LINEAGE", "SELECTED_BINARIES"]
    expected = admission.sdxl_validation_input_hashes(prepared)
    assert expected == {file.member_path: file.sha256 for file in prepared.files}
    pngs = [file for file in prepared.files if file.member_path.endswith(".png")]
    assert len(pngs) == 12
    assert not any(file.member_path.startswith("inputs/canny/") for file in prepared.files)
    assert len(validate_sdxl_validation_sources(command, admitted.sources)) == 12


@pytest.mark.parametrize(
    "fault", ["TRAIN", "HOLDOUT", "training-document", "training-pdf", "training-group", "lineage"]
)
def test_rejected_source_reads_no_binary(tmp_path, monkeypatch, fault):
    command, reader, events = _fixture(tmp_path, monkeypatch, fault=fault)
    with pytest.raises(ValueError):
        admission.prepare_sdxl_validation_inputs(object(), command)
    assert "SELECTED_BINARIES" not in events
    assert all(pointer.media_type == "application/json" for pointer in reader.calls)


@pytest.mark.parametrize(
    "fault",
    ["duplicate", "seed", "source-set", "TRAIN", "anchor-family", "hash", "role", "extra-sampler"],
)
def test_command_closed_fields_and_immutable_identity(tmp_path, monkeypatch, fault):
    command, _reader, _events = _fixture(tmp_path, monkeypatch)
    value = command.model_dump(mode="json")
    if fault == "duplicate":
        value["cases"][1] = copy.deepcopy(value["cases"][0])
    elif fault == "seed":
        value["seed"] += 1
    elif fault == "source-set":
        value["cases"][0]["source_set_sha256"] = "sha256:" + "0" * 64
    elif fault == "TRAIN":
        value["experiment_partition"] = "TRAIN"
    elif fault == "anchor-family":
        value["configuration_anchor"]["schema_ref"] = SOURCE_PAGE_CROP_SET_V3_SCHEMA_REF
    elif fault == "role":
        value["configuration_role"] = "CASE_AUTHORITY"
    elif fault == "extra-sampler":
        value["guidance_scale"] = 5
    else:
        value["command_sha256"] = "sha256:" + "0" * 64
    with pytest.raises(ValidationError):
        LocalImageSdxlValidationComparisonCommand.model_validate(
            value if fault == "hash" else _seal(value)
        )


@pytest.mark.parametrize(
    "fault", ["missing", "hash", "stale", "noncanonical", "dimensions", "unknown-selection"]
)
def test_dangling_stale_or_tampered_case_fails_before_pixels(tmp_path, monkeypatch, fault):
    command, reader, events = _fixture(tmp_path, monkeypatch)
    pin = command.crop_sources[0].crop_set
    if fault == "missing":
        del reader.records[pin]
    elif fault in {"hash", "noncanonical"}:
        raw = reader.records[pin]
        reader.records[pin] = b" " + raw if fault == "noncanonical" else raw + b"bad"
        if fault == "noncanonical":
            value = command.model_dump(mode="json")
            value["crop_sources"][0]["crop_set"]["sha256"] = _sha(reader.records[pin])
            for entry in value["cases"]:
                entry["source_set_sha256"] = value["crop_sources"][0]["crop_set"]["sha256"]
            reader.records[
                ImageEvaluationArtifactMember.model_validate(value["crop_sources"][0]["crop_set"])
            ] = reader.records[pin]
            command = LocalImageSdxlValidationComparisonCommand.model_validate(_seal(value))
    else:
        value = command.model_dump(mode="json")
        if fault == "stale":
            value["crop_sources"][0]["crop_set"]["artifact_revision_id"] = "rev_" + "e" * 32
        elif fault == "unknown-selection":
            value["cases"][0]["selection_id"] = "imgsourcecrop_" + "e" * 32
        else:
            case = value["cases"][0]["case"]
            case["reference_width_px"] = 63
            case["case_id"] = (
                "imgsdxlcase_"
                + content_sha256(
                    {
                        key: item
                        for key, item in case.items()
                        if key not in {"case_id", "staged_member_path"}
                    }
                )[7:39]
            )
            case["staged_member_path"] = "inputs/" + case["case_id"] + ".png"
            value["cases"].sort(key=lambda entry: entry["case"]["case_id"])
        command = LocalImageSdxlValidationComparisonCommand.model_validate(_seal(value))
    with pytest.raises((ValueError, KeyError, ControlArtifactResolutionError)):
        admission.prepare_sdxl_validation_inputs(object(), command)
    assert "SELECTED_BINARIES" not in events


def _result(command, sources, count=24, status="SUCCEEDED"):
    spatial = sources.configuration.sources.spatial_result
    traces = [
        dict(
            case_id=entry.case.case_id,
            source_sha256=entry.case.reference_image.sha256,
            conditioning_sha256=content_sha256({"canny": entry.case.case_id}),
            initialization_rgb_sha256=content_sha256({"rgb": entry.case.case_id}),
            width_px=832,
            height_px=512,
        )
        for entry in command.cases
    ]
    by_case = {row["case_id"]: row for row in traces}
    outputs = []
    for arm in ("BASE", "LORA"):
        for entry in command.cases:
            case_id = entry.case.case_id
            filename = f"{case_id}-{command.seed:010d}.png"
            outputs.append(
                dict(
                    arm=arm,
                    case_id=case_id,
                    seed=command.seed,
                    reference_sha256=entry.case.reference_image.sha256,
                    conditioning_sha256=by_case[case_id]["conditioning_sha256"],
                    member_path=f"outputs/{arm.lower()}/final/{filename}",
                    raw_member_path=f"outputs/{arm.lower()}/raw/{filename}",
                    sha256="sha256:" + "1" * 64,
                    raw_sha256="sha256:" + "2" * 64,
                    size_bytes=128,
                    raw_size_bytes=128,
                    width_px=800,
                    height_px=500,
                    duration_ms=100,
                    peak_gpu_memory_bytes=spatial.runtime.peak_gpu_memory_bytes,
                )
            )
    value = dict(
        schema_version="local-image-sdxl-validation-comparison-result/1.0",
        run_id=command.run_id,
        command_sha256=command.command_sha256,
        configuration_command_sha256=sources.configuration.command.command_sha256,
        case_relation="RESERVED_VALIDATION_NOT_TRAIN_OR_HOLDOUT",
        native_fit_policy="NATIVE_FIT_800X500_CENTER_832X512_OPENCV_CANNY/1.0",
        quality_acceptance="NOT_REVIEWED",
        activation_policy="FORBIDDEN",
        training_steps=0,
        holdout_binary_reads=0,
        status=status,
        error_code=None if status == "SUCCEEDED" else "SDXL_PROBE_EXEC_FAILED",
        runtime=spatial.runtime.model_dump(mode="json"),
        inputs=traces,
        outputs=outputs[:count],
        started_at=command.created_at.isoformat().replace("+00:00", "Z"),
        completed_at=(command.created_at + timedelta(seconds=3)).isoformat().replace("+00:00", "Z"),
        duration_ms=3000,
    )
    return LocalImageSdxlValidationComparisonResult.model_validate(
        {**value, "result_sha256": content_sha256(value)}
    )


@pytest.mark.parametrize("count", [0, 1, 12, 13, 23, 24])
def test_exact_failed_prefix_and_full_success_are_distinct(tmp_path, monkeypatch, count):
    command, _reader, _events = _fixture(tmp_path, monkeypatch)
    admitted = admission.resolve_sdxl_validation_metadata(object(), command)
    result = _result(
        command, admitted.sources, count=count, status="SUCCEEDED" if count == 24 else "FAILED"
    )
    validate_contract("sdxl-validation-comparison-result", result.model_dump(mode="json"))
    validate_sdxl_validation_result(command, admitted.sources, result)
    if count < 24:
        forged = _result(command, admitted.sources, count=count)
        with pytest.raises(ValueError, match="coverage"):
            validate_sdxl_validation_result(command, admitted.sources, forged)


@pytest.mark.parametrize(
    "fault", ["conditioning", "reference", "seed", "run", "configuration", "budget", "skip-prefix"]
)
def test_result_cannot_reinterpret_input_or_failure(tmp_path, monkeypatch, fault):
    command, _reader, _events = _fixture(tmp_path, monkeypatch)
    admitted = admission.resolve_sdxl_validation_metadata(object(), command)
    value = _result(command, admitted.sources).model_dump(mode="json")
    if fault in {"conditioning", "reference", "seed"}:
        field = fault + "_sha256" if fault != "seed" else "seed"
        value["outputs"][0][field] = 7 if fault == "seed" else "sha256:" + "e" * 64
        if fault == "seed":
            row = value["outputs"][0]
            name = f"{row['case_id']}-{row['seed']:010d}.png"
            row["member_path"] = "outputs/base/final/" + name
            row["raw_member_path"] = "outputs/base/raw/" + name
    elif fault == "run":
        value["run_id"] = "imgsdxlvalcmprun_" + "e" * 32
    elif fault == "configuration":
        value["configuration_command_sha256"] = "sha256:" + "e" * 64
    elif fault == "skip-prefix":
        value["outputs"].pop(0)
        value.update(status="FAILED", error_code="SDXL_PROBE_EXEC_FAILED")
    else:
        value["duration_ms"] = command.budget.maximum_duration_ms + 1
    value["result_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "result_sha256"}
    )
    result = LocalImageSdxlValidationComparisonResult.model_validate(value)
    with pytest.raises(ValueError):
        validate_sdxl_validation_result(command, admitted.sources, result)


def test_schema_resources_publication_and_original_contracts_unchanged(tmp_path, monkeypatch):
    command, _reader, _events = _fixture(tmp_path, monkeypatch)
    validate_contract("sdxl-validation-comparison-command", command.model_dump(mode="json"))
    root = Path(__file__).resolve().parents[2]
    for name in ("sdxl-validation-comparison-command", "sdxl-validation-comparison-result"):
        schema = load_schema(name)
        Draft202012Validator.check_schema(schema)
        path = SCHEMA_FILES[name]
        raw = (root / "schemas/image-provider" / path).read_bytes()
        assert (
            raw
            == (root / "packages/image_contracts/eom_image_contracts/schemas" / path).read_bytes()
        )
        assert _sha(raw) == SCHEMA_SHA256[name]
        for component in ("image_trainer", "image_provider"):
            assert path in (root / "scripts" / component / "build_release.sh").read_text()
    publisher = LocalImageTrainingControlArtifactPublisher(
        _Publisher(), source_commit=command.source_commit
    )
    first = publisher.commit_sdxl_validation_comparison_command(command)
    assert first == publisher.commit_sdxl_validation_comparison_command(command)
    assert publisher.publisher.arguments["idempotency_key"].endswith(command.command_sha256[7:])
    assert first.sha256 == _sha(content_json_bytes(command.model_dump(mode="json")))


def test_handoff_derived_metadata_cannot_be_replaced(tmp_path, monkeypatch):
    command, _reader, _events = _fixture(tmp_path, monkeypatch)
    admitted = admission.resolve_sdxl_validation_metadata(object(), command)
    source = admitted.sources.crop_sources[0]
    wrong_pin = source.pin.model_copy(
        update={"crop_set": source.pin.crop_set.model_copy(update={"sha256": "sha256:" + "e" * 64})}
    )
    forged = replace(
        admitted, sources=replace(admitted.sources, crop_sources=(replace(source, pin=wrong_pin),))
    )
    with pytest.raises(ValueError, match="HANDOFF"):
        admission.sdxl_validation_metadata_hashes(forged)
    with pytest.raises(ValueError, match="hash"):
        parse_sdxl_validation_crop_source(source.pin, review_raw=b"{}", crop_set_raw=b"{}")
