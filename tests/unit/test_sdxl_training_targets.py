"""CPU fixtures prove preparation invariants, not generated illustration quality."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_image_contracts import (
    SCHEMA_SHA256,
    LocalImageSdxlTrainingTargetCommand,
    LocalImageSdxlTrainingTargetResult,
    SdxlPrepareTargetDecision,
    content_json_bytes,
    content_sha256,
    load_schema,
    parse_sdxl_training_target_sources,
    sdxl_target_caption,
    sdxl_target_placement,
    validate_contract,
    validate_sdxl_training_target_result,
)
from eom_image_trainer import cli
from eom_image_trainer import sdxl_training_target_runner as runner
from eom_image_trainer.crop_processing import (
    decode_png,
    materialize_reviewed_sdxl_target,
    materialize_training_crop,
    png_bytes,
)
from eom_orchestrator import sdxl_probe_workspace as handoff
from eom_orchestrator import sdxl_training_target_inputs as admission
from eom_orchestrator.local_image_training_control_artifacts import (
    LocalImageTrainingControlArtifactPublisher,
)
from eom_orchestrator.sdxl_probe_inputs import SdxlProbeInputMember
from jsonschema import Draft202012Validator
from PIL import Image
from PIL import __version__ as pillow_version
from pydantic import ValidationError

from tests.unit.test_local_image_training_control_artifacts import _Publisher
from tests.unit.test_sdxl_lora_micro_contracts import _result_value
from tests.unit.test_sdxl_micro_runner import _stage, _write
from tests.unit.test_sdxl_probe_workspace import _operator


def _sha(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _seal(value):
    value["run_id"] = (
        "imgsdxltargetpreprun_"
        + content_sha256(
            {key: item for key, item in value.items() if key not in {"run_id", "command_sha256"}}
        )[7:39]
    )
    value["command_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "command_sha256"}
    )
    return value


def _fixture(tmp_path, *, suffix=b""):
    old_root, original = _stage(tmp_path, suffix=suffix)
    old_raw = content_json_bytes(original.model_dump(mode="json")) + suffix
    result_raw = content_json_bytes(_result_value(original)) + suffix
    metadata = {
        "training-command": old_raw,
        "training-result": result_raw,
        "crop-set": (old_root / "inputs/crop-set.json").read_bytes(),
        "authorization": (old_root / "inputs/authorization.json").read_bytes(),
    }
    pointers = []
    for name, raw, char in (("command", old_raw, "c"), ("result", result_raw, "d")):
        pointers.append(
            {
                "artifact_id": "artifact_" + char * 32,
                "artifact_revision_id": "rev_" + char * 32,
                "member_path": "manifests/sdxl-lora-micro-" + name + ".json",
                "schema_ref": "eom://schemas/image-provider/local-image-sdxl-lora-micro-"
                + name
                + "/1.0",
                "media_type": "application/json",
                "sha256": _sha(raw),
            }
        )
    decisions = []
    for index, sample in enumerate(original.training_samples):
        if index < 3:
            decisions.append(
                {
                    "sample_id": sample.sample_id,
                    "disposition": "PREPARE",
                    "framing_box": {"left": 0, "top": 0, "right": 10000, "bottom": 10000},
                    "redaction_boxes": [{"left": 0, "top": 0, "right": 2000, "bottom": 2000}],
                    "expression": ("CLEAN_CONTOUR", "RESTRAINED_TONE", "FINE_HATCHING")[index],
                }
            )
        else:
            decisions.append(
                {
                    "sample_id": sample.sample_id,
                    "disposition": "DEFER",
                    "reason": "SCIENTIFIC_GEOMETRY_NATIVE",
                }
            )
    command = LocalImageSdxlTrainingTargetCommand.model_validate(
        _seal(
            {
                "schema_version": "local-image-sdxl-training-target-command/1.0",
                "created_at": "2026-10-04T00:00:00Z",
                "created_by": "test",
                "source_commit": "e" * 40,
                "original_training_command": pointers[0],
                "original_training_result": pointers[1],
                "decisions": decisions,
                "policy": "REVIEWED_GRAY_MASK_RATIONAL_FIT_768X512_MARGIN32/1.0",
                "maximum_upscale_milli": 2500,
                "pillow_version": pillow_version,
                "purpose": "CPU_ONLY_TRAIN_TARGET_CANDIDATES",
                "activation_policy": "FORBIDDEN",
            }
        )
    )
    root = tmp_path / command.run_id
    root.mkdir(mode=0o700)
    _write(root / "command.json", content_json_bytes(command.model_dump(mode="json")))
    for name, raw in metadata.items():
        _write(root / ("inputs/" + name + ".json"), raw)
    for sample in original.training_samples[:3]:
        _write(
            root / sample.staged_member_path, (old_root / sample.staged_member_path).read_bytes()
        )
    return root, command, original, metadata


def _sources(command, metadata):
    return parse_sdxl_training_target_sources(
        command,
        **{
            "training_command_payload": metadata["training-command"],
            "training_result_payload": metadata["training-result"],
            "crop_set_payload": metadata["crop-set"],
            "authorization_payload": metadata["authorization"],
        },
    )


def _run(root, command):
    return runner.run_sdxl_training_target_command(workspace=root, command=command)


@pytest.mark.parametrize("suffix", [b"", b"\n"])
def test_schema_resources_source_snapshot_and_success_replay(tmp_path, monkeypatch, suffix):
    root, command, original, metadata = _fixture(tmp_path, suffix=suffix)
    sources = _sources(command, metadata)
    assert sources.training_command == original
    result = _run(root, command)
    validate_sdxl_training_target_result(command, sources, result)
    assert result.status == "SUCCEEDED" and result.activation_policy == "FORBIDDEN"
    assert len(result.prepared_targets) == 3 and len(result.deferred_sample_ids) == 13
    repo = Path(__file__).resolve().parents[2]
    for family, value in (("command", command), ("result", result)):
        name = "sdxl-training-target-" + family
        Draft202012Validator.check_schema(load_schema(name))
        validate_contract(name, value.model_dump(mode="json"))
        filename = "local-image-sdxl-training-target-" + family + "-v1.schema.json"
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
        image = decode_png((root / target.member_path).read_bytes())
        assert image.size == (768, 512) and image.mode == "RGB"
        assert image.getpixel(
            (target.placement.offset_x_px + 4, target.placement.offset_y_px + 4)
        ) == (255, 255, 255)
        assert target.placement.resized_width_px == 240
        assert target.training_caption_en.startswith("eom exam line art, ")
        assert target.training_caption_en.endswith("plain white background")
    monkeypatch.setattr(
        runner,
        "materialize_reviewed_sdxl_target",
        lambda *args, **kwargs: pytest.fail("replay transformed pixels"),
    )
    assert _run(root, command) == result


@pytest.mark.parametrize(
    "fault",
    [
        "activation",
        "over_scale",
        "duplicate",
        "order",
        "outside_mask",
        "defer_recipe",
        "all_deferred",
        "hash",
        "wrong_pointer",
    ],
)
def test_invalid_command_denies_unsafe_or_implicit_preparation(tmp_path, fault):
    _, command, _, _ = _fixture(tmp_path)
    value = command.model_dump(mode="json")
    if fault == "activation":
        value["activation_policy"] = "ALLOWED"
    elif fault == "over_scale":
        value["maximum_upscale_milli"] = 4001
    elif fault == "duplicate":
        value["decisions"][1] = copy.deepcopy(value["decisions"][0])
    elif fault == "order":
        value["decisions"].reverse()
    elif fault == "outside_mask":
        value["decisions"][0]["framing_box"]["left"] = 3000
    elif fault == "defer_recipe":
        value["decisions"][3]["expression"] = "CLEAN_CONTOUR"
    elif fault == "all_deferred":
        value["decisions"] = [
            {
                "sample_id": decision["sample_id"],
                "disposition": "DEFER",
                "reason": "SOURCE_PART_MISSING",
            }
            for decision in value["decisions"]
        ]
    elif fault == "wrong_pointer":
        value["original_training_result"]["member_path"] = "manifests/other.json"
    _seal(value)
    if fault == "hash":
        value["command_sha256"] = "sha256:" + "f" * 64
    with pytest.raises(ValidationError):
        LocalImageSdxlTrainingTargetCommand.model_validate(value)


@pytest.mark.parametrize(
    "fault", ["hash", "noncanonical", "unknown_target", "reserved_target", "parent_failed"]
)
def test_source_admission_denies_unknown_or_non_successful_lineage(tmp_path, fault):
    _, command, original, metadata = _fixture(tmp_path)
    value = command.model_dump(mode="json")
    if fault == "hash":
        metadata["training-result"] += b" "
    elif fault == "noncanonical":
        metadata["training-result"] += b" "
        value["original_training_result"]["sha256"] = _sha(metadata["training-result"])
    elif fault in {"unknown_target", "reserved_target"}:
        value["decisions"][0]["sample_id"] = (
            "imgscivislineartcrop_" + "0" * 32
            if fault == "unknown_target"
            else original.validation_sample_ids[0]
        )
        value["decisions"].sort(key=lambda decision: decision["sample_id"])
    else:
        parent = json.loads(metadata["training-result"])
        parent.update(
            status="FAILED", error_code="IMAGE_TRAINING_EXEC_FAILED", adapter_manifest=None
        )
        parent["result_sha256"] = content_sha256(
            {key: item for key, item in parent.items() if key != "result_sha256"}
        )
        metadata["training-result"] = content_json_bytes(parent)
        value["original_training_result"]["sha256"] = _sha(metadata["training-result"])
    command = LocalImageSdxlTrainingTargetCommand.model_validate(_seal(value))
    with pytest.raises(ValueError):
        _sources(command, metadata)


def test_exact_rational_upscale_limits_and_legacy_preparation_unchanged(tmp_path):
    _, command, original, _ = _fixture(tmp_path)
    sample = original.training_samples[0]
    decision = command.decisions[0]
    assert isinstance(decision, SdxlPrepareTargetDecision)
    placement = sdxl_target_placement(sample, decision, maximum_upscale_milli=4000)
    assert (placement.resized_width_px, placement.resized_height_px) == (384, 384)
    source = Image.new("RGB", (96, 96), "white")
    source.putpixel((50, 50), (0, 0, 0))
    old = materialize_training_crop(source, crop_box=decision.framing_box)
    assert old.getpixel((386, 258)) == (0, 0, 0)  # The original no-upscale policy is preserved.
    new = materialize_reviewed_sdxl_target(source, decision=decision, placement=placement)
    assert new.size == old.size
    other = original.training_samples[1]
    with pytest.raises(ValueError, match="source mismatch"):
        sdxl_target_caption(other, decision)


@pytest.mark.parametrize("fault", ["missing", "hash", "symlink", "empty", "alpha"])
def test_failure_preserves_verified_execution_prefix_not_reserved_inputs(tmp_path, fault):
    root, command, original, _ = _fixture(tmp_path)
    bad = root / original.training_samples[1].staged_member_path
    if fault == "missing":
        bad.unlink()
    elif fault == "symlink":
        bad.unlink()
        bad.symlink_to(root / original.training_samples[0].staged_member_path)
    elif fault == "alpha":
        # Direct decoder rejection isolates mode validation, not hash validation.
        with pytest.raises(runner.SdxlTrainingTargetError):
            runner._decode(png_bytes(Image.new("RGBA", (96, 96), "white")), size=(96, 96))
        bad.write_bytes(b"corrupted")
    elif fault == "empty":
        bad.write_bytes(b"")
    else:
        bad.write_bytes(b"corrupted")
    result = _run(root, command)
    assert result.status == "FAILED" and result.error_code == "SDXL_TARGET_SOURCE_INVALID"
    assert tuple(target.sample_id for target in result.prepared_targets) == (
        original.training_samples[0].sample_id,
    )
    assert len(result.deferred_sample_ids) == 13
    assert _run(root, command) == result


def test_actual_runtime_drift_fails_before_any_pixel_transform(tmp_path, monkeypatch):
    root, command, _, _ = _fixture(tmp_path)
    monkeypatch.setattr(runner, "pillow_version", "1.2.3")
    result = _run(root, command)
    assert result.error_code == "SDXL_TARGET_RUNTIME_MISMATCH"
    assert result.pillow_version == "1.2.3" and not result.prepared_targets
    assert not (root / "targets").exists()
    assert _run(root, command) == result


@pytest.mark.parametrize(
    "fault",
    [
        "missing_output",
        "hash",
        "extra_output",
        "noncanonical_receipt",
        "incomplete_coverage",
        "unreceipted",
    ],
)
def test_terminal_replay_fail_closed(tmp_path, fault):
    root, command, _, _ = _fixture(tmp_path)
    result = _run(root, command)
    first = root / result.prepared_targets[0].member_path
    if fault == "missing_output":
        first.unlink()
    elif fault == "hash":
        first.write_bytes(b"corrupt")
    elif fault == "extra_output":
        _write(root / "targets/extra.png", b"unreceipted")
    elif fault == "unreceipted":
        (root / "result.json").unlink()
    elif fault == "noncanonical_receipt":
        (root / "result.json").write_bytes((root / "result.json").read_bytes() + b"\n")
    else:
        value = result.model_dump(mode="json")
        value["prepared_targets"].pop()
        value["result_sha256"] = content_sha256(
            {key: item for key, item in value.items() if key != "result_sha256"}
        )
        (root / "result.json").write_bytes(content_json_bytes(value))
    with pytest.raises(runner.SdxlTrainingTargetError, match="OUTPUT_INVALID"):
        _run(root, command)


def test_masks_cannot_erase_entire_target(tmp_path):
    _, command, original, _ = _fixture(tmp_path)
    value = command.decisions[0].model_dump(mode="json")
    value["redaction_boxes"] = [value["framing_box"]]
    decision = SdxlPrepareTargetDecision.model_validate(value)
    sample = original.training_samples[0]
    placement = sdxl_target_placement(sample, decision, maximum_upscale_milli=2500)
    from eom_image_trainer.crop_processing import CropProcessingError

    with pytest.raises(CropProcessingError, match="SOURCE_INVALID"):
        materialize_reviewed_sdxl_target(
            Image.new("RGB", (96, 96), "black"), decision=decision, placement=placement
        )


def test_orchestrator_batches_only_prepared_train_pixels_after_lineage(tmp_path, monkeypatch):
    root, command, original, metadata = _fixture(tmp_path)
    lineage = SimpleNamespace(
        crop_set_payload=metadata["crop-set"], authorization_payload=metadata["authorization"]
    )
    calls = []

    def read(engine, pointer, **kwargs):
        return (
            metadata["training-command"]
            if pointer == command.original_training_command
            else metadata["training-result"]
        )

    def resolve(engine, **kwargs):
        calls.append("lineage")
        return lineage

    def batch(engine, reads):
        calls.append("batch")
        assert len(reads) == 3
        assert tuple(read.pointer.sha256 for read in reads) == tuple(
            sample.source_image.sha256 for sample in original.training_samples[:3]
        )
        return tuple(
            (root / sample.staged_member_path).read_bytes()
            for sample in original.training_samples[:3]
        )

    monkeypatch.setattr(admission, "resolve_control_artifact_member", read)
    monkeypatch.setattr(admission, "resolve_sdxl_training_sources", resolve)
    monkeypatch.setattr(admission, "resolve_control_artifact_members", batch)
    prepared = admission.prepare_sdxl_training_target_inputs(object(), command)
    assert calls == ["lineage", "batch"] and len(prepared.files) == 8
    assert {
        file.member_path: file.sha256 for file in prepared.files
    } == admission.sdxl_training_target_input_hashes(command, prepared.sources)
    metadata["training-result"] += b" "
    with pytest.raises(ValueError):
        admission.prepare_sdxl_training_target_inputs(object(), command)
    assert calls == ["lineage", "batch", "lineage"]


def test_cli_cpu_operation_never_takes_gpu_lock(tmp_path, monkeypatch):
    root, _, _, _ = _fixture(tmp_path)
    monkeypatch.setattr(
        cli, "_lock_gpu", lambda *args: pytest.fail("CPU preparation used GPU lock")
    )
    monkeypatch.setattr(
        sys,
        "argv",
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
    assert (
        LocalImageSdxlTrainingTargetResult.model_validate_json(
            (root / "result.json").read_bytes()
        ).status
        == "SUCCEEDED"
    )


def test_cpu_systemd_unit_has_no_model_gpu_network_or_nas_access():
    repo = Path(__file__).resolve().parents[2]
    unit = (repo / "infra/systemd/eom-image-sdxl-training-targets@.service").read_text()
    for boundary in (
        "PrivateDevices=true",
        "PrivateNetwork=true",
        "ProtectHome=true",
        "InaccessiblePaths=/mnt/nas",
        "InaccessiblePaths=/srv/eom/models/image",
        "InaccessiblePaths=/etc/eom",
        "Restart=no",
        "MemoryMax=2G",
        "TimeoutStartSec=120",
    ):
        assert boundary in unit
    assert (
        "DeviceAllow=" not in unit and "--gpu-lock" not in unit and "--model-store-root" not in unit
    )
    assert "PYTHONPATH=" not in unit


def test_loader_checks_command_path_and_workspace_identity(tmp_path):
    root, command, _, _ = _fixture(tmp_path)
    with pytest.raises(runner.SdxlTrainingTargetError):
        runner.load_sdxl_training_target_command(root, root / "inputs/training-command.json")
    wrong = root.parent / "wrong-id"
    root.rename(wrong)
    with pytest.raises(runner.SdxlTrainingTargetError):
        _run(wrong, command)


def test_command_publication_pins_semantic_idempotency_and_raw_artifact_hash(tmp_path):
    _, command, _, _ = _fixture(tmp_path)
    publisher = _Publisher()
    adapter = LocalImageTrainingControlArtifactPublisher(
        publisher, source_commit=command.source_commit
    )
    pin = adapter.commit_sdxl_training_target_command(command)
    raw = content_json_bytes(command.model_dump(mode="json"))
    assert pin.sha256 == _sha(raw) and pin.sha256 != command.command_sha256
    assert (
        publisher.arguments["idempotency_key"]
        == "local-image-sdxl-training-target-command:" + command.command_sha256[7:]
    )
    assert pin.member_path == "manifests/sdxl-training-target-command.json"
    assert publisher.arguments["payload"] == raw


def test_target_handoff_is_exclusive_and_fixed_cpu_dispatch(tmp_path, monkeypatch):
    root, command, _, metadata = _fixture(tmp_path)
    sources = _sources(command, metadata)
    files = tuple(
        SdxlProbeInputMember(
            str(path.relative_to(root)), _sha(path.read_bytes()), path.read_bytes()
        )
        for path in sorted(root.rglob("*"))
        if path.is_file()
    )
    prepared = admission.PreparedSdxlTrainingTargetInputs(command, sources, files)
    parent, worker, _ = _operator(monkeypatch, tmp_path)
    staged = handoff.stage_sdxl_training_target_inputs(
        prepared, workspace_parent=parent, worker=worker
    )
    assert staged.systemd_unit == "eom-image-sdxl-training-targets@" + command.run_id + ".service"
    assert len(tuple(staged.workspace.rglob("*.png"))) == 3
    with pytest.raises(handoff.SdxlProbeHandoffError, match="WORKSPACE_EXISTS"):
        handoff.stage_sdxl_training_target_inputs(prepared, workspace_parent=parent, worker=worker)
    calls = []
    monkeypatch.setattr(handoff.subprocess, "run", lambda args, **kwargs: calls.append(args))
    from dataclasses import replace

    live = replace(staged, workspace=Path("/srv/eom/image-training-workspaces") / command.run_id)
    handoff.dispatch_sdxl_training_targets(live)
    assert calls == [["systemctl", "start", "--no-block", live.systemd_unit]]
    with pytest.raises(handoff.SdxlProbeHandoffError, match="DISPATCH_INVALID"):
        handoff.dispatch_sdxl_training_targets(
            replace(
                live, systemd_unit="eom-image-sdxl-lora-micro-probe@" + command.run_id + ".service"
            )
        )


def test_schema_and_pydantic_both_reject_unknown_target_error(tmp_path):
    root, command, _, _ = _fixture(tmp_path)
    value = _run(root, command).model_dump(mode="json")
    value.update(status="FAILED", error_code="SDXL_TARGET_UNDECLARED_ERROR")
    value["result_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "result_sha256"}
    )
    from jsonschema.exceptions import ValidationError as SchemaError

    with pytest.raises(SchemaError):
        validate_contract("sdxl-training-target-result", value)
    with pytest.raises(ValidationError):
        LocalImageSdxlTrainingTargetResult.model_validate(value)
