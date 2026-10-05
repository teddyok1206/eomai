"""Synthetic native targets protect source/canvas/recipe boundaries, not model quality."""

from __future__ import annotations

import copy
import hashlib
import io
from pathlib import Path

import pytest
from eom_image_contracts import (
    ImageEvaluationBoundingBox,
    content_json_bytes,
    content_sha256,
    load_schema,
    validate_contract,
)
from eom_image_contracts.sdxl_native_training_targets import (
    NATIVE_TARGET_CANVASES,
    SDXL_NATIVE_TARGET_COMMAND_SCHEMA_REF,
    LocalImageSdxlNativeTrainingTargetCommand,
    LocalImageSdxlNativeTrainingTargetResult,
    parse_sdxl_native_training_target_sources,
    validate_sdxl_native_training_target_result,
)
from eom_image_contracts.sdxl_source_training_targets import SdxlPreparedSourceTrainingTarget
from eom_image_contracts.sdxl_training_targets import sdxl_reviewed_target_placement
from eom_image_contracts.source_pdf_crops import SOURCE_PDF_CROP_SET_SCHEMA_REF
from eom_image_contracts.validation import SCHEMA_SHA256
from eom_image_trainer import cli
from eom_image_trainer import sdxl_training_target_runner as runner
from eom_orchestrator import sdxl_training_target_inputs as admission
from eom_orchestrator.local_image_training_control_artifacts import (
    LocalImageTrainingControlArtifactPublisher,
)
from jsonschema.exceptions import ValidationError as SchemaValidationError
from PIL import Image, ImageDraw
from PIL import __version__ as pillow_version
from pydantic import ValidationError

from tests.unit.test_local_image_training_control_artifacts import _Publisher
from tests.unit.test_science_source_page_crops import _fixture_review
from tests.unit.test_science_source_pdf_crops import _command, _pointer, _seal_set, _set
from tests.unit.test_sdxl_micro_runner import _write
from tests.unit.test_sdxl_training_targets import _seal


def _sha(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _fixture(tmp_path, monkeypatch, canvas="SQUARE_1024"):
    review, lineage, _ = _fixture_review(monkeypatch, count=3)
    native_command = _command(review)
    crop_set, _ = _set(native_command, review)
    crop_value = crop_set.model_dump(mode="json")
    pixels = {}
    for index, member in enumerate(crop_value["members"]):
        image = Image.new("RGB", (member["width_px"], member["height_px"]), "white")
        drawing = ImageDraw.Draw(image)
        drawing.rectangle((70 + index * 20, 60, 900, 1010), outline="black", width=6)
        drawing.ellipse(
            (110 + index * 80, 150, 650, 680), fill=40 + index * 50, outline="black", width=4
        )
        stream = io.BytesIO()
        image.save(stream, format="PNG", compress_level=9)
        raw = stream.getvalue()
        pixels[member["selection_id"]] = raw
        member["sha256"], member["size_bytes"] = _sha(raw), len(raw)
    crop_set = _seal_set(crop_value)
    crop_raw = content_json_bytes(crop_set.model_dump(mode="json"))
    crop_pointer = _pointer(
        crop_raw, SOURCE_PDF_CROP_SET_SCHEMA_REF, "science-source-pdf-crop-set", index=20
    )
    decisions = [
        {
            "sample_id": member.selection_id,
            "disposition": "PREPARE",
            "framing_box": {"left": 0, "top": 0, "right": 10000, "bottom": 10000},
            "redaction_boxes": [],
            "expression": "RESTRAINED_TONE",
            "canvas": canvas if index == 0 else "LANDSCAPE_1024X768",
            "reviewed_caption_en": f"A complete synthetic object {index} with restrained tones",
        }
        if index < 2
        else {
            "sample_id": member.selection_id,
            "disposition": "DEFER",
            "reason": "SOURCE_RESOLUTION_LIMITED",
        }
        for index, member in enumerate(crop_set.members)
    ]
    command = LocalImageSdxlNativeTrainingTargetCommand.model_validate(
        _seal(
            {
                "schema_version": "local-image-sdxl-training-target-command/1.2",
                "created_at": "2026-10-04T17:00:00Z",
                "created_by": "fixture.operator",
                "source_commit": "c" * 40,
                "source_crop_set": crop_pointer.model_dump(mode="json"),
                "training_authorization": review.training_authorization.model_dump(mode="json"),
                "decisions": decisions,
                "policy": "REVIEWED_NATIVE_GRAY_RATIONAL_FIT_MARGIN32_NO_MASK/1.0",
                "maximum_upscale_milli": 1500,
                "pillow_version": pillow_version,
                "purpose": "CPU_ONLY_TRAIN_TARGET_CANDIDATES",
                "activation_policy": "FORBIDDEN",
            }
        )
    )
    documents = {
        "inputs/source-crop-set.json": crop_raw,
        "inputs/native-crop-command.json": content_json_bytes(
            native_command.model_dump(mode="json")
        ),
        "inputs/source-review.json": content_json_bytes(review.model_dump(mode="json")),
        "inputs/authorization.json": lineage.authorization_payload,
    }
    root = tmp_path / command.run_id
    root.mkdir(mode=0o700)
    _write(root / "command.json", content_json_bytes(command.model_dump(mode="json")))
    for path, raw in documents.items():
        _write(root / path, raw)
    for decision in command.decisions:
        if decision.disposition == "PREPARE":
            _write(
                root / ("inputs/source-crops/" + decision.sample_id + ".png"),
                pixels[decision.sample_id],
            )
    return root, command, documents, crop_set, native_command, review, pixels


def _sources(command, documents):
    return parse_sdxl_native_training_target_sources(
        command,
        crop_set_payload=documents["inputs/source-crop-set.json"],
        source_command_payload=documents["inputs/native-crop-command.json"],
        review_payload=documents["inputs/source-review.json"],
        authorization_payload=documents["inputs/authorization.json"],
    )


@pytest.mark.parametrize("canvas", list(NATIVE_TARGET_CANVASES))
def test_native_canvas_roundtrip_recipe_and_receipt_only_replay(tmp_path, monkeypatch, canvas):
    root, command, documents, _, _, _, _ = _fixture(tmp_path, monkeypatch, canvas)
    sources = _sources(command, documents)
    result = runner.run_sdxl_training_target_command(workspace=root, command=command)
    validate_sdxl_native_training_target_result(command, sources, result)
    assert result.status == "SUCCEEDED" and len(result.prepared_targets) == 2
    assert (
        result.state == "UNREVIEWED_TRAIN_TARGET_CANDIDATES"
        and result.activation_policy == "FORBIDDEN"
    )
    assert len(result.deferred_sample_ids) == 1
    for decision, target in zip(command.decisions, result.prepared_targets, strict=False):
        with Image.open(root / target.member_path) as image:
            assert image.size == NATIVE_TARGET_CANVASES[decision.canvas] and image.mode == "RGB"
            assert image.getpixel((0, 0)) == (255, 255, 255)
            assert (
                image.getchannel("R").tobytes()
                == image.getchannel("G").tobytes()
                == image.getchannel("B").tobytes()
            )
        assert decision.reviewed_caption_en in target.training_caption_en
    repo = Path(__file__).resolve().parents[2]
    for family, model in (("command", command), ("result", result)):
        name = "sdxl-training-target-" + family + "-v3"
        validate_contract(name, model.model_dump(mode="json"))
        assert (
            type(model).model_validate_json(content_json_bytes(model.model_dump(mode="json")))
            == model
        )
        filename = "local-image-sdxl-training-target-" + family + "-v3.schema.json"
        raw = (repo / "schemas/image-provider" / filename).read_bytes()
        assert _sha(raw) == SCHEMA_SHA256[name]
        assert (
            raw
            == (
                repo / "packages/image_contracts/eom_image_contracts/schemas" / filename
            ).read_bytes()
        )
        assert filename in (repo / "scripts/image_trainer/build_release.sh").read_text()
        assert load_schema(name)["$schema"].endswith("2020-12/schema")
    before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    monkeypatch.setattr(
        runner,
        "materialize_reviewed_sdxl_target",
        lambda *_a, **_k: pytest.fail("replay transformed"),
    )
    assert runner.run_sdxl_training_target_command(workspace=root, command=command) == result
    assert before == {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}


@pytest.mark.parametrize(
    "fault", ["old_set", "mask", "canvas", "caption", "scale", "duplicate", "all_deferred", "hash"]
)
def test_native_command_rejects_unsupported_or_hidden_recipe_changes(tmp_path, monkeypatch, fault):
    _, command, _, _, _, _, _ = _fixture(tmp_path, monkeypatch)
    value = command.model_dump(mode="json")
    if fault == "old_set":
        value["source_crop_set"]["schema_ref"] = (
            "eom://schemas/image-provider/local-image-science-source-page-crop-set/1.1"
        )
    elif fault == "mask":
        value["decisions"][0]["redaction_boxes"] = [
            {"left": 0, "top": 0, "right": 100, "bottom": 100}
        ]
    elif fault == "canvas":
        value["decisions"][0]["canvas"] = "ANY_IMAGE_SIZE"
    elif fault == "caption":
        value["decisions"][0]["reviewed_caption_en"] = (
            " " + value["decisions"][0]["reviewed_caption_en"]
        )
    elif fault == "scale":
        value["maximum_upscale_milli"] = 4000
    elif fault == "duplicate":
        value["decisions"][1] = copy.deepcopy(value["decisions"][0])
    elif fault == "all_deferred":
        value["decisions"] = [
            {"sample_id": d["sample_id"], "disposition": "DEFER", "reason": "REFERENCE_ONLY"}
            for d in value["decisions"]
        ]
    else:
        value["command_sha256"] = "sha256:" + "f" * 64
    with pytest.raises(ValidationError):
        LocalImageSdxlNativeTrainingTargetCommand.model_validate(
            _seal(value) if fault != "hash" else value
        )


@pytest.mark.parametrize(
    "fault", ["native_hash", "set_newline", "review_hash", "auth_hash", "coverage", "time"]
)
def test_native_sources_require_exact_frozen_lineage(tmp_path, monkeypatch, fault):
    _, command, documents, _, _, _, _ = _fixture(tmp_path, monkeypatch)
    value = command.model_dump(mode="json")
    if fault == "coverage":
        value["decisions"].pop()
    elif fault == "time":
        value["created_at"] = "2026-10-04T15:00:00Z"
    elif fault == "set_newline":
        documents["inputs/source-crop-set.json"] += b"\n"
        value["source_crop_set"]["sha256"] = _sha(documents["inputs/source-crop-set.json"])
    else:
        path = {
            "native_hash": "inputs/native-crop-command.json",
            "review_hash": "inputs/source-review.json",
            "auth_hash": "inputs/authorization.json",
        }[fault]
        documents[path] += b" "
    command = LocalImageSdxlNativeTrainingTargetCommand.model_validate(_seal(value))
    with pytest.raises(ValueError):
        _sources(command, documents)


def test_admission_resolves_only_prepare_pngs_after_full_metadata(tmp_path, monkeypatch):
    _, command, documents, _, native, _, pixels = _fixture(tmp_path, monkeypatch)
    calls = []

    def metadata(_engine, pointer, *, maximum_bytes):
        calls.append(("metadata", pointer.member_path))
        path = {
            "manifests/science-source-pdf-crop-set.json": "inputs/source-crop-set.json",
            "manifests/science-source-pdf-crop-command.json": "inputs/native-crop-command.json",
            "manifests/science-source-page-crop-review.json": "inputs/source-review.json",
            "manifests/science-corpus-training-authorization.json": "inputs/authorization.json",
        }[pointer.member_path]
        assert len(documents[path]) <= maximum_bytes
        return documents[path]

    def provenance(_engine, source_command):
        assert source_command == native
        calls.append(("provenance", source_command.command_id))

    def images(_engine, reads):
        assert calls[-1][0] == "provenance"
        assert len(reads) == 2
        assert all(
            r.pointer.media_type == "image/png"
            and r.pointer.artifact_revision_id == command.source_crop_set.artifact_revision_id
            for r in reads
        )
        calls.append(("images", len(reads)))
        return tuple(pixels[Path(r.pointer.member_path).stem] for r in reads)

    monkeypatch.setattr(admission, "resolve_control_artifact_member", metadata)
    monkeypatch.setattr(admission, "prepare_source_pdf_crop_reads", provenance)
    monkeypatch.setattr(admission, "resolve_control_artifact_members", images)
    prepared = admission.prepare_sdxl_training_target_inputs(object(), command)
    assert len(prepared.files) == 7
    hashes = admission.sdxl_training_target_input_hashes(command, prepared.sources)
    assert hashes == {member.member_path: member.sha256 for member in prepared.files}
    assert not any(command.decisions[-1].sample_id in file.member_path for file in prepared.files)
    assert [c[0] for c in calls] == ["metadata"] * 4 + ["provenance", "images"]


def test_corrupted_metadata_never_reads_pngs(tmp_path, monkeypatch):
    _, command, _documents, _, _, _, _ = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(admission, "resolve_control_artifact_member", lambda *_a, **_k: b"{}")
    monkeypatch.setattr(
        admission,
        "resolve_control_artifact_members",
        lambda *_a, **_k: pytest.fail("media read before metadata"),
    )
    with pytest.raises(ValueError):
        admission.prepare_sdxl_training_target_inputs(object(), command)


def test_native_worker_failure_has_terminal_no_retry_receipt(tmp_path, monkeypatch):
    root, command, documents, _, _, _, _ = _fixture(tmp_path, monkeypatch)
    sources = _sources(command, documents)
    monkeypatch.setattr(
        runner,
        "materialize_reviewed_sdxl_target",
        lambda *_a, **_k: (_ for _ in ()).throw(ValueError("synthetic failure")),
    )
    failed = runner.run_sdxl_training_target_command(workspace=root, command=command)
    assert failed.status == "FAILED" and failed.error_code == "SDXL_TARGET_PREPARATION_FAILED"
    validate_sdxl_native_training_target_result(command, sources, failed)
    monkeypatch.setattr(
        runner,
        "materialize_reviewed_sdxl_target",
        lambda *_a, **_k: pytest.fail("failed work retried"),
    )
    assert runner.run_sdxl_training_target_command(workspace=root, command=command) == failed


def test_native_cli_uses_existing_cpu_only_dispatch(tmp_path, monkeypatch):
    root, command, _, _, _, _, _ = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, "_lock_gpu", lambda *_a, **_k: pytest.fail("CPU acquired GPU lock"))
    monkeypatch.setattr(
        "sys.argv",
        [
            "eom-local-image-trainer",
            "prepare-sdxl-targets",
            "--command",
            str(root / "command.json"),
            "--workspace",
            str(root),
        ],
    )
    cli.main()
    result = LocalImageSdxlNativeTrainingTargetResult.model_validate_json(
        (root / "result.json").read_bytes()
    )
    assert result.status == "SUCCEEDED" and result.run_id == command.run_id


def test_native_duplicate_output_keeps_valid_failed_prefix(tmp_path, monkeypatch):
    root, command, documents, _, _, _, _ = _fixture(tmp_path, monkeypatch)
    original = runner.materialize_reviewed_sdxl_target
    first_payload = None

    def duplicate(source, **kwargs):
        nonlocal first_payload
        output = original(source, **kwargs)
        if first_payload is None:
            first_payload = runner.png_bytes(output)
        return output

    original_encoder = runner.png_bytes
    monkeypatch.setattr(runner, "materialize_reviewed_sdxl_target", duplicate)
    monkeypatch.setattr(runner, "png_bytes", lambda image: first_payload or original_encoder(image))
    result = runner.run_sdxl_training_target_command(workspace=root, command=command)
    assert result.status == "FAILED" and result.error_code == "SDXL_TARGET_SOURCE_INVALID"
    assert len(result.prepared_targets) == 1
    validate_sdxl_native_training_target_result(command, _sources(command, documents), result)
    assert len(tuple((root / "targets").iterdir())) == 1


@pytest.mark.parametrize("fault", ["file_hash", "foreign_file", "receipt_hash", "wrong_version"])
def test_native_terminal_replay_rejects_corruption(tmp_path, monkeypatch, fault):
    root, command, _, _, _, _, _ = _fixture(tmp_path, monkeypatch)
    result = runner.run_sdxl_training_target_command(workspace=root, command=command)
    if fault == "file_hash":
        _write(root / result.prepared_targets[0].member_path, b"bad")
    elif fault == "foreign_file":
        _write(root / "targets/unknown.png", b"bad")
    else:
        value = result.model_dump(mode="json")
        if fault == "receipt_hash":
            value["result_sha256"] = "sha256:" + "0" * 64
        else:
            value["schema_version"] = "local-image-sdxl-training-target-result/1.1"
            value["result_sha256"] = content_sha256(
                {key: item for key, item in value.items() if key != "result_sha256"}
            )
        _write(root / "result.json", content_json_bytes(value))
    monkeypatch.setattr(
        runner,
        "materialize_reviewed_sdxl_target",
        lambda *_a, **_k: pytest.fail("invalid receipt was redispatched"),
    )
    with pytest.raises(runner.SdxlTrainingTargetError, match="SDXL_TARGET_OUTPUT_INVALID"):
        runner.run_sdxl_training_target_command(workspace=root, command=command)


@pytest.mark.parametrize("fault", ["missing_png", "corrupt_png", "unreceipted", "runtime"])
def test_native_input_failure_is_terminal_and_not_silently_repaired(tmp_path, monkeypatch, fault):
    root, command, documents, _, _, _, _ = _fixture(tmp_path, monkeypatch)
    if fault == "unreceipted":
        (root / "targets").mkdir(mode=0o700)
        with pytest.raises(runner.SdxlTrainingTargetError, match="OUTPUT_INVALID"):
            runner.run_sdxl_training_target_command(workspace=root, command=command)
        assert not (root / "result.json").exists()
        return
    if fault == "runtime":
        monkeypatch.setattr(runner, "pillow_version", "0.0.0")
        expected = "SDXL_TARGET_RUNTIME_MISMATCH"
    else:
        source = root / ("inputs/source-crops/" + command.decisions[0].sample_id + ".png")
        if fault == "missing_png":
            source.unlink()
        else:
            _write(source, b"corrupt")
        expected = "SDXL_TARGET_SOURCE_INVALID"
    result = runner.run_sdxl_training_target_command(workspace=root, command=command)
    assert (
        result.status == "FAILED" and result.error_code == expected and not result.prepared_targets
    )
    validate_sdxl_native_training_target_result(command, _sources(command, documents), result)
    monkeypatch.setattr(
        runner,
        "materialize_reviewed_sdxl_target",
        lambda *_a, **_k: pytest.fail("failed result retried"),
    )
    assert runner.run_sdxl_training_target_command(workspace=root, command=command) == result


@pytest.mark.parametrize("fault", ["caption", "canvas", "source_hash", "target_missing"])
def test_native_receipt_tampering_cannot_relabel_a_result(tmp_path, monkeypatch, fault):
    root, command, documents, _, _, _, _ = _fixture(tmp_path, monkeypatch)
    result = runner.run_sdxl_training_target_command(workspace=root, command=command)
    value = result.model_dump(mode="json")
    if fault == "target_missing":
        value["prepared_targets"].pop()
    else:
        target = value["prepared_targets"][0]
        if fault == "caption":
            target["training_caption_en"] = "A different unreviewed drawing and caption"
            target["training_caption_sha256"] = _sha(target["training_caption_en"].encode())
        elif fault == "canvas":
            target["width_px"] = 768
        else:
            target["source_crop_sha256"] = "sha256:" + "f" * 64
        target["target_revision_id"] = (
            "imgsdxltargetrev_"
            + content_sha256(
                {
                    "target_id": target["target_id"],
                    "sha256": target["sha256"],
                    "training_caption_sha256": target["training_caption_sha256"],
                    "placement": target["placement"],
                }
            )[7:39]
        )
    value["result_sha256"] = content_sha256(
        {k: v for k, v in value.items() if k != "result_sha256"}
    )
    with pytest.raises(ValueError):
        tampered = LocalImageSdxlNativeTrainingTargetResult.model_validate(value)
        validate_sdxl_native_training_target_result(command, _sources(command, documents), tampered)


def test_native_source_normalization_preserves_gray_pixels_without_masks(tmp_path, monkeypatch):
    root, command, _documents, _, _, _, pixels = _fixture(
        tmp_path, monkeypatch, "PORTRAIT_768X1024"
    )
    result = runner.run_sdxl_training_target_command(workspace=root, command=command)
    target = result.prepared_targets[0]
    placement = target.placement
    with (
        Image.open(io.BytesIO(pixels[target.sample_id])) as source,
        Image.open(root / target.member_path) as image,
    ):
        expected = (
            source.crop(placement.source_pixel_box)
            .convert("L")
            .resize(
                (placement.resized_width_px, placement.resized_height_px), Image.Resampling.LANCZOS
            )
            .convert("RGB")
        )
        observed = image.crop(
            (
                placement.offset_x_px,
                placement.offset_y_px,
                placement.offset_x_px + placement.resized_width_px,
                placement.offset_y_px + placement.resized_height_px,
            )
        )
        assert observed.tobytes() == expected.tobytes()


def test_legacy_micro_cannot_accept_native_targets_by_alias(tmp_path, monkeypatch):
    root, command, _, _, _, _, _ = _fixture(tmp_path, monkeypatch)
    result = runner.run_sdxl_training_target_command(workspace=root, command=command)
    for target in result.prepared_targets:
        with pytest.raises(SchemaValidationError):
            validate_contract("sdxl-training-target-result-v2", result.model_dump(mode="json"))
        with pytest.raises(ValidationError):
            SdxlPreparedSourceTrainingTarget.model_validate(target.model_dump(mode="json"))


def test_native_command_uses_existing_control_commit_owner(tmp_path, monkeypatch):
    _, command, _, _, _, _, _ = _fixture(tmp_path, monkeypatch)
    publisher = _Publisher()
    pointer = LocalImageTrainingControlArtifactPublisher(
        publisher, source_commit="c" * 40
    ).commit_sdxl_training_target_command(command)
    assert pointer.schema_ref == SDXL_NATIVE_TARGET_COMMAND_SCHEMA_REF
    assert pointer.sha256 == _sha(content_json_bytes(command.model_dump(mode="json")))


@pytest.mark.parametrize("dimensions", [(321, 557), (1596, 430), (190, 80)])
@pytest.mark.parametrize("scale", [1000, 1500, 4000])
def test_legacy_geometry_keeps_exact_fixed_recipe(dimensions, scale):
    width, height = dimensions
    box = ImageEvaluationBoundingBox(left=250, top=100, right=9850, bottom=9400)
    left, top = box.left * width // 10000, box.top * height // 10000
    right, bottom = (box.right * width + 9999) // 10000, (box.bottom * height + 9999) // 10000
    ratios = [(704, right - left), (448, bottom - top), (scale, 1000)]
    numerator, denominator = ratios[0]
    for n, d in ratios[1:]:
        if n * denominator < numerator * d:
            numerator, denominator = n, d
    rw, rh = (right - left) * numerator // denominator, (bottom - top) * numerator // denominator
    expected = {
        "source_pixel_box": [left, top, right, bottom],
        "resized_width_px": rw,
        "resized_height_px": rh,
        "offset_x_px": (768 - rw) // 2,
        "offset_y_px": (512 - rh) // 2,
    }
    assert (
        sdxl_reviewed_target_placement(
            width=width, height=height, framing_box=box, maximum_upscale_milli=scale
        ).model_dump(mode="json")
        == expected
    )
