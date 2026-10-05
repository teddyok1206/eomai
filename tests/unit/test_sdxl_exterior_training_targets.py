"""Reviewed exterior recipes preserve originals and never infer scientific geometry."""

from __future__ import annotations

import copy
import io
from pathlib import Path

import pytest
from eom_image_contracts import content_json_bytes, validate_contract
from eom_image_contracts.sdxl_native_training_targets import (
    NATIVE_TARGET_CANVASES,
    SDXL_EXTERIOR_TARGET_COMMAND_SCHEMA_REF,
    LocalImageSdxlExteriorTrainingTargetCommand,
    LocalImageSdxlNativeTrainingTargetCommand,
    SdxlExteriorPrepareTargetDecision,
    native_training_target_protocol,
    validate_sdxl_native_training_target_result,
)
from eom_image_contracts.source_pdf_crops import SOURCE_PDF_CROP_SET_SCHEMA_REF
from eom_image_contracts.validation import SCHEMA_SHA256
from eom_image_trainer import sdxl_training_target_runner as runner
from eom_image_trainer.exterior_annotation_pixels import (
    ExteriorAnnotationError,
    remove_reviewed_exterior_annotations,
)
from eom_orchestrator import sdxl_training_target_inputs as admission
from eom_orchestrator.local_image_training_control_artifacts import (
    LocalImageTrainingControlArtifactPublisher,
)
from jsonschema.exceptions import ValidationError as SchemaValidationError
from PIL import Image, ImageDraw
from pydantic import ValidationError

from tests.unit.test_local_image_training_control_artifacts import _Publisher
from tests.unit.test_science_source_pdf_crops import _pointer, _seal_set
from tests.unit.test_sdxl_micro_runner import _write
from tests.unit.test_sdxl_native_training_targets import _fixture, _sha, _sources
from tests.unit.test_sdxl_training_targets import _seal


def _decision():
    return SdxlExteriorPrepareTargetDecision.model_validate(
        {
            "sample_id": "imgsourcecrop_" + "a" * 32,
            "disposition": "PREPARE",
            "framing_box": {"left": 0, "top": 0, "right": 10000, "bottom": 10000},
            "redaction_boxes": [{"left": 8000, "top": 1000, "right": 9000, "bottom": 2000}],
            "protected_subject_boxes": [{"left": 1000, "top": 3000, "right": 7000, "bottom": 9000}],
            "annotation_policy": "REVIEWED_EXTERIOR_ONLY_PROTECTED_RING3_WHITE250/1.0",
            "expression": "CLEAN_CONTOUR",
            "canvas": "SQUARE_1024",
            "reviewed_caption_en": "A complete synthetic object on white",
        }
    )


def _exterior_fixture(tmp_path, monkeypatch, canvas="SQUARE_1024", *, nonwhite_ring=False):
    _, old, documents, crop_set, *_rest, pixels = _fixture(tmp_path, monkeypatch, canvas)
    crop_value = crop_set.model_dump(mode="json")
    prepared = {d.sample_id for d in old.decisions if d.disposition == "PREPARE"}
    for member in crop_value["members"]:
        if member["selection_id"] not in prepared:
            continue
        image = Image.open(io.BytesIO(pixels[member["selection_id"]])).convert("RGB")
        ImageDraw.Draw(image).rectangle(
            (
                image.width * 94 // 100,
                image.height * 2 // 100,
                image.width * 96 // 100,
                image.height * 3 // 100,
            ),
            fill="black",
        )
        if nonwhite_ring:
            image.putpixel((image.width * 9250 // 10000 - 1, image.height * 2 // 100), (0, 0, 0))
        stream = io.BytesIO()
        image.save(stream, format="PNG", compress_level=9)
        raw = stream.getvalue()
        pixels[member["selection_id"]] = raw
        member["sha256"], member["size_bytes"] = _sha(raw), len(raw)
    crop_set = _seal_set(crop_value)
    raw = content_json_bytes(crop_set.model_dump(mode="json"))
    documents["inputs/source-crop-set.json"] = raw
    value = old.model_dump(mode="json")
    value.update(
        schema_version="local-image-sdxl-training-target-command/1.3",
        policy="REVIEWED_NATIVE_EXTERIOR_WHITE_RING3_FIT_MARGIN32/1.0",
        source_crop_set=_pointer(
            raw, SOURCE_PDF_CROP_SET_SCHEMA_REF, "science-source-pdf-crop-set", index=20
        ).model_dump(mode="json"),
    )
    for decision in value["decisions"]:
        if decision["disposition"] != "PREPARE":
            continue
        decision.update(
            redaction_boxes=[{"left": 9250, "top": 80, "right": 9800, "bottom": 420}],
            protected_subject_boxes=[{"left": 500, "top": 400, "right": 9000, "bottom": 9800}],
            annotation_policy="REVIEWED_EXTERIOR_ONLY_PROTECTED_RING3_WHITE250/1.0",
        )
    command = LocalImageSdxlExteriorTrainingTargetCommand.model_validate(_seal(value))
    root = tmp_path / command.run_id
    root.mkdir(mode=0o700)
    _write(root / "command.json", content_json_bytes(command.model_dump(mode="json")))
    for path, raw in documents.items():
        _write(root / path, raw)
    for sid in prepared:
        _write(root / ("inputs/source-crops/" + sid + ".png"), pixels[sid])
    return root, command, documents


@pytest.mark.parametrize("mode", ["RGB", "L"])
def test_exact_pixels_outside_masks_and_original_unchanged(mode):
    source = Image.new(mode, (100, 100), "white")
    ImageDraw.Draw(source).rectangle((80, 10, 89, 19), fill="black")
    ImageDraw.Draw(source).ellipse((15, 35, 65, 85), outline="black", width=2)
    original = source.tobytes()
    derivative = remove_reviewed_exterior_annotations(source, _decision())
    assert derivative is not source and source.tobytes() == original
    for y in range(100):
        for x in range(100):
            expected = (255, 255, 255) if mode == "RGB" else 255
            assert derivative.getpixel((x, y)) == (
                expected if 80 <= x < 90 and 10 <= y < 20 else source.getpixel((x, y))
            )


@pytest.mark.parametrize("fault", ["leader", "gray_ring", "protected_pixel_contact"])
def test_pixel_guards_reject_without_changing_source(fault):
    source = Image.new("RGB", (100, 100), "white")
    decision = _decision()
    if fault == "leader":
        ImageDraw.Draw(source).line((70, 15, 85, 15), fill="black")
        code = "CLEARANCE_NOT_WHITE"
    elif fault == "gray_ring":
        source.putpixel((79, 15), (249, 249, 249))
        code = "CLEARANCE_NOT_WHITE"
    else:
        value = decision.model_dump(mode="json")
        value["protected_subject_boxes"] = [
            {"left": 6000, "top": 1000, "right": 7900, "bottom": 2000}
        ]
        decision = SdxlExteriorPrepareTargetDecision.model_validate(value)
        code = "PROTECTED_CONTACT"
    original = source.tobytes()
    with pytest.raises(ExteriorAnnotationError, match=code):
        remove_reviewed_exterior_annotations(source, decision)
    assert source.tobytes() == original


@pytest.mark.parametrize("fault", ["overlap", "outside_frame", "duplicate", "empty"])
def test_recipe_requires_explicit_valid_subject_protection(fault):
    value = _decision().model_dump(mode="json")
    if fault == "overlap":
        value["protected_subject_boxes"] = copy.deepcopy(value["redaction_boxes"])
    elif fault == "outside_frame":
        value["framing_box"]["left"] = 2000
    elif fault == "duplicate":
        value["protected_subject_boxes"] *= 2
    else:
        value["protected_subject_boxes"] = []
    with pytest.raises(ValidationError):
        SdxlExteriorPrepareTargetDecision.model_validate(value)


@pytest.mark.parametrize("canvas", list(NATIVE_TARGET_CANVASES))
def test_exterior_worker_binding_three_canvases_and_no_write_replay(tmp_path, monkeypatch, canvas):
    root, command, documents = _exterior_fixture(tmp_path, monkeypatch, canvas)
    protocol = native_training_target_protocol(command.schema_version)
    assert protocol.command_model is LocalImageSdxlExteriorTrainingTargetCommand
    validate_contract(protocol.command_contract, command.model_dump(mode="json"))
    assert runner._command((root / "command.json").read_bytes()) == command
    sources = _sources(command, documents)
    before_inputs = {p: p.read_bytes() for p in (root / "inputs").rglob("*") if p.is_file()}
    result = runner.run_sdxl_training_target_command(workspace=root, command=command)
    assert result.status == "SUCCEEDED" and len(result.prepared_targets) == 2
    assert result.schema_version == "local-image-sdxl-training-target-result/1.3"
    validate_contract(protocol.result_contract, result.model_dump(mode="json"))
    validate_sdxl_native_training_target_result(command, sources, result)
    assert before_inputs == {p: p.read_bytes() for p in before_inputs}
    assert result.activation_policy == "FORBIDDEN"
    assert result.prepared_targets[0].width_px == NATIVE_TARGET_CANVASES[canvas][0]
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    monkeypatch.setattr(
        runner,
        "materialize_reviewed_sdxl_target",
        lambda *_a, **_kw: pytest.fail("replay transformed"),
    )
    assert runner.run_sdxl_training_target_command(workspace=root, command=command) == result
    assert before == {p: p.read_bytes() for p in before}


def test_old_contract_cannot_admit_exterior_recipe_and_resource_bytes_are_pinned(
    tmp_path, monkeypatch
):
    _, command, _ = _exterior_fixture(tmp_path, monkeypatch)
    with pytest.raises(ValidationError):
        LocalImageSdxlNativeTrainingTargetCommand.model_validate(command.model_dump(mode="json"))
    with pytest.raises(SchemaValidationError):
        validate_contract("sdxl-training-target-command-v3", command.model_dump(mode="json"))
    assert command.source_crop_set.schema_ref != SDXL_EXTERIOR_TARGET_COMMAND_SCHEMA_REF
    repo = Path(__file__).resolve().parents[2]
    for family in ("command", "result"):
        name = "sdxl-training-target-" + family + "-v4"
        filename = "local-image-" + name + ".schema.json"
        raw = (repo / "schemas/image-provider" / filename).read_bytes()
        assert _sha(raw) == SCHEMA_SHA256[name]
        assert (
            raw
            == (
                repo / "packages/image_contracts/eom_image_contracts/schemas" / filename
            ).read_bytes()
        )
        assert filename in (repo / "scripts/image_trainer/build_release.sh").read_text()


def test_exterior_nonwhite_clearance_is_terminal_and_not_repaired(tmp_path, monkeypatch):
    root, command, documents = _exterior_fixture(tmp_path, monkeypatch, nonwhite_ring=True)
    result = runner.run_sdxl_training_target_command(workspace=root, command=command)
    assert result.status == "FAILED" and result.error_code == "SDXL_TARGET_SOURCE_INVALID"
    assert not result.prepared_targets
    validate_sdxl_native_training_target_result(command, _sources(command, documents), result)
    monkeypatch.setattr(
        runner,
        "materialize_reviewed_sdxl_target",
        lambda *_a, **_kw: pytest.fail("failed recipe retried"),
    )
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert runner.run_sdxl_training_target_command(workspace=root, command=command) == result
    assert before == {p: p.read_bytes() for p in before}


def test_exterior_admission_and_publication_use_existing_metadata_boundary(tmp_path, monkeypatch):
    root, command, documents = _exterior_fixture(tmp_path, monkeypatch)
    calls = []
    members = {
        "manifests/science-source-pdf-crop-set.json": "inputs/source-crop-set.json",
        "manifests/science-source-pdf-crop-command.json": "inputs/native-crop-command.json",
        "manifests/science-source-page-crop-review.json": "inputs/source-review.json",
        "manifests/science-corpus-training-authorization.json": "inputs/authorization.json",
    }

    def metadata(_engine, pointer, *, maximum_bytes):
        assert "png" not in calls
        calls.append("metadata")
        raw = documents[members[pointer.member_path]]
        assert len(raw) <= maximum_bytes
        return raw

    def provenance(*_a, **_kw):
        assert calls == ["metadata"] * 4
        calls.append("provenance")

    def pixels(_engine, reads):
        assert calls[-1] == "provenance" and len(reads) == 2
        calls.append("png")
        return tuple(
            (root / ("inputs/source-crops/" + Path(r.pointer.member_path).name)).read_bytes()
            for r in reads
        )

    monkeypatch.setattr(admission, "resolve_control_artifact_member", metadata)
    monkeypatch.setattr(admission, "prepare_source_pdf_crop_reads", provenance)
    monkeypatch.setattr(admission, "resolve_control_artifact_members", pixels)
    prepared = admission.prepare_sdxl_training_target_inputs(object(), command)
    assert len(prepared.files) == 7
    assert calls == ["metadata"] * 4 + ["provenance", "png"]
    publisher = _Publisher()
    owner = LocalImageTrainingControlArtifactPublisher(
        publisher, source_commit=command.source_commit
    )
    pointer = owner.commit_sdxl_training_target_command(command)
    assert pointer.schema_ref == SDXL_EXTERIOR_TARGET_COMMAND_SCHEMA_REF
    assert publisher.arguments["payload"] == content_json_bytes(command.model_dump(mode="json"))


def test_exterior_corrupted_metadata_is_rejected_before_media(tmp_path, monkeypatch):
    _, command, _ = _exterior_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(admission, "resolve_control_artifact_member", lambda *_a, **_kw: b"{}")
    monkeypatch.setattr(
        admission,
        "resolve_control_artifact_members",
        lambda *_a, **_kw: pytest.fail("read PNG early"),
    )
    with pytest.raises(ValueError):
        admission.prepare_sdxl_training_target_inputs(object(), command)
