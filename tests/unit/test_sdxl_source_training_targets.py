"""CPU successor fixtures prove source/recipe isolation, not training or image quality."""

from __future__ import annotations

import copy
import hashlib
from pathlib import Path

import pytest
from eom_image_contracts import (
    SCHEMA_SHA256,
    SOURCE_PAGE_CROP_SET_SCHEMA_REF,
    SOURCE_PAGE_CROP_SET_V2_SCHEMA_REF,
    ImageEvaluationArtifactMember,
    LocalImageScienceSourcePageCropSet,
    LocalImageScienceSourcePageCropSetV2,
    content_json_bytes,
    content_sha256,
    load_schema,
    validate_contract,
)
from eom_image_contracts.sdxl_source_training_targets import (
    LocalImageSdxlSourceTrainingTargetCommand,
    LocalImageSdxlSourceTrainingTargetResult,
    parse_sdxl_source_training_target_sources,
    sdxl_source_target_id,
    validate_sdxl_source_training_target_result,
)
from eom_image_trainer import cli
from eom_image_trainer import sdxl_training_target_runner as runner
from eom_image_trainer.crop_processing import png_bytes
from eom_orchestrator import sdxl_training_target_inputs as admission
from eom_orchestrator.local_image_training_control_artifacts import (
    LocalImageTrainingControlArtifactPublisher,
)
from jsonschema import Draft202012Validator
from PIL import Image, ImageDraw
from PIL import __version__ as pillow_version
from pydantic import ValidationError

from tests.unit.test_local_image_training_control_artifacts import _Publisher
from tests.unit.test_science_source_page_crop_expansion import (
    _reader as _expanded_reader,
)
from tests.unit.test_science_source_page_crop_expansion import (
    _review as _expanded_review,
)
from tests.unit.test_science_source_page_crop_expansion import expanded  # noqa: F401
from tests.unit.test_science_source_page_crops import _crop_set, _fixture_review, _seal_review
from tests.unit.test_sdxl_micro_runner import _write
from tests.unit.test_sdxl_training_targets import _seal


def _sha(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _seal_set(value):
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
    return value


def _fixture(tmp_path, monkeypatch, *, review=None, auth_raw=None, suffix=b""):
    if review is None:
        review, lineage, _reader = _fixture_review(monkeypatch, count=3)
        auth_raw = lineage.authorization_payload
    crop_value = (
        _crop_set(review).model_dump(mode="json")
        if review.schema_version.endswith("/1.0")
        else {
            "schema_version": "local-image-science-source-page-crop-set/1.1",
            "crop_set_id": "imgsourcecropset_"
            + content_sha256({"selection_ids": tuple(s.selection_id for s in review.selections)})[
                7:39
            ],
            "created_at": "2026-10-04T08:01:00Z",
            "review": {
                "artifact_id": "artifact_" + "1" * 32,
                "artifact_revision_id": "rev_" + "2" * 32,
                "member_path": "manifests/science-source-page-crop-review.json",
                "schema_ref": "eom://schemas/image-provider/local-image-science-source-page-crop-review/1.1",
                "media_type": "application/json",
                "sha256": _sha(content_json_bytes(review.model_dump(mode="json"))),
            },
            "pillow_version": pillow_version,
            "members": [],
            "state": "REVIEWED_SOURCE_DERIVATIVES",
            "activation_policy": "FORBIDDEN",
        }
    )
    members = []
    pixel_payloads = {}
    for index, selection in enumerate(review.selections):
        width, height = (
            selection.pixel_box[2] - selection.pixel_box[0],
            selection.pixel_box[3] - selection.pixel_box[1],
        )
        image = Image.new("RGB", (width, height), "white")
        drawing = ImageDraw.Draw(image)
        drawing.rectangle((25 + index, 25, width - 25, height - 25), outline="black", width=2)
        drawing.line((35 + index, 35, width // 2, height // 2), fill="black", width=2)
        raw = png_bytes(image)
        pixel_payloads[selection.selection_id] = raw
        members.append(
            {
                "selection_id": selection.selection_id,
                "member_path": "crops/" + selection.selection_id + ".png",
                "sha256": _sha(raw),
                "size_bytes": len(raw),
                "width_px": width,
                "height_px": height,
                "perceptual_hash": f"{index:016x}",
            }
        )
    crop_value["members"] = members
    crop_set = (
        LocalImageScienceSourcePageCropSet
        if review.schema_version.endswith("/1.0")
        else LocalImageScienceSourcePageCropSetV2
    ).model_validate(_seal_set(crop_value))
    crop_raw = content_json_bytes(crop_set.model_dump(mode="json")) + suffix
    pointer = ImageEvaluationArtifactMember(
        artifact_id="artifact_" + "5" * 32,
        artifact_revision_id="rev_" + "6" * 32,
        member_path="manifests/science-source-page-crop-set.json",
        schema_ref=SOURCE_PAGE_CROP_SET_SCHEMA_REF
        if review.schema_version.endswith("/1.0")
        else SOURCE_PAGE_CROP_SET_V2_SCHEMA_REF,
        media_type="application/json",
        sha256=_sha(crop_raw),
    )
    decisions = [
        {
            "sample_id": selection.selection_id,
            "disposition": "PREPARE",
            "framing_box": {"left": 0, "top": 0, "right": 10000, "bottom": 10000},
            "redaction_boxes": [{"left": 0, "top": 0, "right": 400, "bottom": 400}],
            "expression": selection.expression,
        }
        if index < 2
        else {
            "sample_id": selection.selection_id,
            "disposition": "DEFER",
            "reason": "REFERENCE_ONLY",
        }
        for index, selection in enumerate(review.selections)
    ]
    command = LocalImageSdxlSourceTrainingTargetCommand.model_validate(
        _seal(
            {
                "schema_version": "local-image-sdxl-training-target-command/1.1",
                "created_at": "2026-10-04T08:02:00Z",
                "created_by": "fixture.operator",
                "source_commit": "c" * 40,
                "source_crop_set": pointer.model_dump(mode="json"),
                "training_authorization": review.training_authorization.model_dump(mode="json"),
                "decisions": decisions,
                "policy": "REVIEWED_GRAY_MASK_RATIONAL_FIT_768X512_MARGIN32/1.0",
                "maximum_upscale_milli": 1500,
                "pillow_version": pillow_version,
                "purpose": "CPU_ONLY_TRAIN_TARGET_CANDIDATES",
                "activation_policy": "FORBIDDEN",
            }
        )
    )
    root = tmp_path / command.run_id
    root.mkdir(mode=0o700)
    docs = {
        "inputs/source-crop-set.json": crop_raw,
        "inputs/source-review.json": content_json_bytes(review.model_dump(mode="json")),
        "inputs/authorization.json": auth_raw,
    }
    _write(root / "command.json", content_json_bytes(command.model_dump(mode="json")))
    for path, raw in docs.items():
        _write(root / path, raw)
    for decision in command.decisions:
        if decision.disposition == "PREPARE":
            _write(
                root / ("inputs/source-crops/" + decision.sample_id + ".png"),
                pixel_payloads[decision.sample_id],
            )
    return root, command, docs, crop_set, review, pixel_payloads


def _sources(command, docs):
    return parse_sdxl_source_training_target_sources(
        command,
        crop_set_payload=docs["inputs/source-crop-set.json"],
        review_payload=docs["inputs/source-review.json"],
        authorization_payload=docs["inputs/authorization.json"],
    )


@pytest.mark.parametrize("suffix", [b"", b"\n"])
def test_successor_schema_result_and_receipt_only_replay(tmp_path, monkeypatch, suffix):
    root, command, docs, _, _, _ = _fixture(tmp_path, monkeypatch, suffix=suffix)
    sources = _sources(command, docs)
    result = runner.run_sdxl_training_target_command(workspace=root, command=command)
    validate_sdxl_source_training_target_result(command, sources, result)
    assert result.status == "SUCCEEDED" and len(result.prepared_targets) == 2
    assert len(result.deferred_sample_ids) == 1 and result.activation_policy == "FORBIDDEN"
    assert result.source_snapshot_sha256 == sources.snapshot_sha256
    assert all(target.sample_id.startswith("imgsourcecrop_") for target in result.prepared_targets)
    repo = Path(__file__).resolve().parents[2]
    for family, model in (("command", command), ("result", result)):
        name = "sdxl-training-target-" + family + "-v2"
        Draft202012Validator.check_schema(load_schema(name))
        validate_contract(name, model.model_dump(mode="json"))
        filename = "local-image-sdxl-training-target-" + family + "-v2.schema.json"
        raw = (repo / "schemas/image-provider" / filename).read_bytes()
        assert (
            raw
            == (
                repo / "packages/image_contracts/eom_image_contracts/schemas" / filename
            ).read_bytes()
        )
        assert _sha(raw) == SCHEMA_SHA256[name]
        assert filename in (repo / "scripts/image_trainer/build_release.sh").read_text()
    for target in result.prepared_targets:
        with Image.open(root / target.member_path) as image:
            assert image.mode == "RGB" and image.size == (768, 512)
            assert image.getpixel((0, 0)) == (255, 255, 255)
    monkeypatch.setattr(
        runner,
        "materialize_reviewed_sdxl_target",
        lambda *a, **kw: pytest.fail("replay changed pixels"),
    )
    assert runner.run_sdxl_training_target_command(workspace=root, command=command) == result


@pytest.mark.parametrize(
    "fault",
    [
        "old_id",
        "old_pointer",
        "duplicate",
        "reordered",
        "all_deferred",
        "mask_outside",
        "hash",
        "activation",
    ],
)
def test_invalid_successor_commands_do_not_relabel_historical_inputs(tmp_path, monkeypatch, fault):
    _, command, _, _, _, _ = _fixture(tmp_path, monkeypatch)
    value = command.model_dump(mode="json")
    if fault == "old_id":
        value["decisions"][0]["sample_id"] = "imgscivislineartcrop_" + "a" * 32
    elif fault == "old_pointer":
        value["source_crop_set"]["schema_ref"] = (
            "eom://schemas/image-provider/local-image-science-object-line-art-crop-set/1.0"
        )
    elif fault == "duplicate":
        value["decisions"][1] = copy.deepcopy(value["decisions"][0])
    elif fault == "reordered":
        value["decisions"].reverse()
    elif fault == "all_deferred":
        value["decisions"] = [
            {"sample_id": d["sample_id"], "disposition": "DEFER", "reason": "REFERENCE_ONLY"}
            for d in value["decisions"]
        ]
    elif fault == "mask_outside":
        value["decisions"][0]["framing_box"]["left"] = 500
    elif fault == "hash":
        value["command_sha256"] = "sha256:" + "0" * 64
    elif fault == "activation":
        value["activation_policy"] = "ALLOWED"
    if fault != "hash":
        _seal(value)
    with pytest.raises(ValidationError):
        LocalImageSdxlSourceTrainingTargetCommand.model_validate(value)


@pytest.mark.parametrize(
    "path",
    ["inputs/source-crop-set.json", "inputs/source-review.json", "inputs/authorization.json"],
)
def test_metadata_corruption_fails_before_pixels(tmp_path, monkeypatch, path):
    root, command, docs, _, _, _ = _fixture(tmp_path, monkeypatch)
    (root / path).write_bytes(docs[path] + b" ")
    monkeypatch.setattr(
        runner, "_decode", lambda *a, **kw: pytest.fail("pixels read before admission")
    )
    with pytest.raises(runner.SdxlTrainingTargetError, match="SDXL_TARGET_INPUT_INVALID"):
        runner.run_sdxl_training_target_command(workspace=root, command=command)
    assert not (root / "targets").exists()


@pytest.mark.parametrize("partition", ["VALIDATION", "HOLDOUT"])
def test_rehashed_non_train_source_is_rejected_even_when_deferred(tmp_path, monkeypatch, partition):
    _, command, docs, crop_set, review, _ = _fixture(tmp_path, monkeypatch)
    value = review.model_dump(mode="json")
    value["selections"][-1]["partition"] = partition
    altered = type(review).model_validate(_seal_review(value))
    raw = content_json_bytes(altered.model_dump(mode="json"))
    crop_value = crop_set.model_dump(mode="json")
    crop_value["review"]["sha256"] = _sha(raw)
    crop_raw = content_json_bytes(
        type(crop_set).model_validate(_seal_set(crop_value)).model_dump(mode="json")
    )
    command_value = command.model_dump(mode="json")
    command_value["source_crop_set"]["sha256"] = _sha(crop_raw)
    modified = LocalImageSdxlSourceTrainingTargetCommand.model_validate(_seal(command_value))
    with pytest.raises(ValueError, match="TRAIN coverage"):
        _sources(
            modified,
            {**docs, "inputs/source-crop-set.json": crop_raw, "inputs/source-review.json": raw},
        )


def test_root_admission_resolves_full_original_lineage_then_batches_selected_only(
    tmp_path, monkeypatch
):
    _, command, docs, crop_set, _, pixels = _fixture(tmp_path, monkeypatch)
    calls = []
    by_pointer = {
        command.source_crop_set: docs["inputs/source-crop-set.json"],
        crop_set.review: docs["inputs/source-review.json"],
        command.training_authorization: docs["inputs/authorization.json"],
    }
    monkeypatch.setattr(
        admission,
        "resolve_control_artifact_member",
        lambda engine, pointer, **kw: by_pointer[pointer],
    )
    actual_lineage = admission.prepare_source_page_crop_reads

    def lineage(*args):
        calls.append("lineage")
        return actual_lineage(*args)

    def batch(engine, reads):
        calls.append("pixels")
        assert len(reads) == 2
        assert all(
            read.pointer.artifact_revision_id == command.source_crop_set.artifact_revision_id
            for read in reads
        )
        return tuple(pixels[member.selection_id] for member in crop_set.members[:2])

    monkeypatch.setattr(admission, "prepare_source_page_crop_reads", lineage)
    monkeypatch.setattr(admission, "resolve_control_artifact_members", batch)
    prepared = admission.prepare_sdxl_training_target_inputs(object(), command)
    assert calls == ["lineage", "pixels"] and len(prepared.files) == 6
    assert {
        file.member_path: file.sha256 for file in prepared.files
    } == admission.sdxl_training_target_input_hashes(command, prepared.sources)
    assert all("training-result" not in file.member_path for file in prepared.files)


def test_supplemental_crop_set_reuses_closed_full_provenance_and_same_cpu_runner(
    tmp_path,
    monkeypatch,
    expanded,  # noqa: F811 - imported pytest fixture
):
    review = _expanded_review(expanded)
    _records, metadata_calls = _expanded_reader(monkeypatch, expanded, review)
    root, command, docs, crop_set, _, pixels = _fixture(
        tmp_path,
        monkeypatch,
        review=review,
        auth_raw=content_json_bytes(expanded.authorization.model_dump(mode="json")),
    )
    by_pointer = {
        command.source_crop_set: docs["inputs/source-crop-set.json"],
        crop_set.review: docs["inputs/source-review.json"],
        command.training_authorization: docs["inputs/authorization.json"],
    }
    monkeypatch.setattr(
        admission,
        "resolve_control_artifact_member",
        lambda engine, pointer, **kw: by_pointer[pointer],
    )

    def batch(engine, reads):
        assert len(metadata_calls) == 1 and len(metadata_calls[0]) == 7
        return tuple(pixels[member.selection_id] for member in crop_set.members)

    monkeypatch.setattr(admission, "resolve_control_artifact_members", batch)
    prepared = admission.prepare_sdxl_training_target_inputs(object(), command)
    assert len(prepared.files) == 5
    result = runner.run_sdxl_training_target_command(workspace=root, command=command)
    assert result.status == "SUCCEEDED" and len(result.prepared_targets) == 1


@pytest.mark.parametrize("fault", ["missing", "hash", "empty"])
def test_failure_prefix_and_deferred_inputs_are_not_processed(tmp_path, monkeypatch, fault):
    root, command, _, _, _, _ = _fixture(tmp_path, monkeypatch)
    path = root / ("inputs/source-crops/" + command.decisions[1].sample_id + ".png")
    if fault == "missing":
        path.unlink()
    elif fault == "hash":
        path.write_bytes(path.read_bytes() + b"corrupt")
    else:
        path.write_bytes(b"")
    result = runner.run_sdxl_training_target_command(workspace=root, command=command)
    assert result.status == "FAILED" and result.error_code == "SDXL_TARGET_SOURCE_INVALID"
    assert len(result.prepared_targets) == 1 and len(result.deferred_sample_ids) == 1
    assert not (root / ("inputs/source-crops/" + result.deferred_sample_ids[0] + ".png")).exists()


def test_runtime_drift_has_zero_transforms_and_target_caption_is_revision_not_source_identity(
    tmp_path, monkeypatch
):
    root, command, docs, _, _, _ = _fixture(tmp_path, monkeypatch)
    sources = _sources(command, docs)
    sample = sources.samples[0]
    logical = sdxl_source_target_id(command, sample, command.decisions[0])
    assert logical.startswith("imgsdxltarget_")
    monkeypatch.setattr(runner, "pillow_version", "0.0.0")
    monkeypatch.setattr(
        runner,
        "materialize_reviewed_sdxl_target",
        lambda *a, **kw: pytest.fail("runtime drift transformed pixels"),
    )
    result = runner.run_sdxl_training_target_command(workspace=root, command=command)
    assert result.error_code == "SDXL_TARGET_RUNTIME_MISMATCH" and not result.prepared_targets


@pytest.mark.parametrize(
    "fault", ["file_hash", "foreign_file", "receipt_hash", "snapshot", "wrong_version"]
)
def test_successor_replay_rejects_corruption_and_foreign_lineage(tmp_path, monkeypatch, fault):
    root, command, _, _, _, _ = _fixture(tmp_path, monkeypatch)
    result = runner.run_sdxl_training_target_command(workspace=root, command=command)
    if fault == "file_hash":
        (root / result.prepared_targets[0].member_path).write_bytes(b"bad")
    elif fault == "foreign_file":
        _write(root / "targets/unknown.png", b"bad")
    else:
        value = result.model_dump(mode="json")
        if fault == "receipt_hash":
            value["result_sha256"] = "sha256:" + "0" * 64
        elif fault == "snapshot":
            value["source_snapshot_sha256"] = "sha256:" + "0" * 64
        else:
            value["schema_version"] = "local-image-sdxl-training-target-result/1.0"
        if fault != "receipt_hash":
            value["result_sha256"] = content_sha256(
                {k: v for k, v in value.items() if k != "result_sha256"}
            )
        (root / "result.json").write_bytes(content_json_bytes(value))
    with pytest.raises(runner.SdxlTrainingTargetError, match="SDXL_TARGET_OUTPUT_INVALID"):
        runner.run_sdxl_training_target_command(workspace=root, command=command)


def test_successor_cli_keeps_cpu_only_dispatch(tmp_path, monkeypatch):
    root, command, _, _, _, _ = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, "_lock_gpu", lambda *a, **kw: pytest.fail("CPU acquired GPU lock"))
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
    result = LocalImageSdxlSourceTrainingTargetResult.model_validate_json(
        (root / "result.json").read_bytes()
    )
    assert result.status == "SUCCEEDED" and result.run_id == command.run_id


def test_successor_command_publication_retains_semantic_idempotency_and_raw_hash(
    tmp_path, monkeypatch
):
    _, command, _, _, _, _ = _fixture(tmp_path, monkeypatch)
    publisher = _Publisher()
    pin = LocalImageTrainingControlArtifactPublisher(
        publisher, source_commit=command.source_commit
    ).commit_sdxl_training_target_command(command)
    assert pin.schema_ref.endswith("sdxl-training-target-command/1.1")
    assert pin.sha256 == _sha(content_json_bytes(command.model_dump(mode="json")))
    assert pin.sha256 != command.command_sha256
    assert (
        publisher.arguments["idempotency_key"]
        == "local-image-sdxl-training-target-command:" + command.command_sha256[7:]
    )


@pytest.mark.parametrize("fault", ["missing_decision", "foreign_decision", "future_source"])
def test_rehashed_command_cannot_claim_wrong_snapshot(tmp_path, monkeypatch, fault):
    _, command, docs, _, _, _ = _fixture(tmp_path, monkeypatch)
    value = command.model_dump(mode="json")
    if fault == "missing_decision":
        value["decisions"] = value["decisions"][:1]
    elif fault == "foreign_decision":
        value["decisions"][0]["sample_id"] = "imgsourcecrop_" + "0" * 32
        value["decisions"].sort(key=lambda d: d["sample_id"])
    else:
        value["created_at"] = "2026-10-03T00:00:00Z"
    modified = LocalImageSdxlSourceTrainingTargetCommand.model_validate(_seal(value))
    with pytest.raises(ValueError, match="TRAIN coverage"):
        _sources(modified, docs)
