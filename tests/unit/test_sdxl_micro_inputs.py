from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from eom_image_contracts import (
    ImageEvaluationArtifactMember,
    LocalImageSdxlLoraMicroCommand,
    content_json_bytes,
)
from eom_orchestrator import sdxl_micro_inputs as admission
from eom_orchestrator import sdxl_probe_inputs as sources
from eom_orchestrator import sdxl_probe_workspace as handoff
from eom_orchestrator.local_image_training_control_artifacts import (
    SDXL_MICRO_COMMAND_ARTIFACT_TYPE,
    LocalImageTrainingControlArtifactPublisher,
)

from tests.unit.test_local_image_training_control_artifacts import _Publisher
from tests.unit.test_sdxl_lora_micro_contracts import _command_value, _seal_command
from tests.unit.test_sdxl_probe_inputs import _fixture, _png, _Reader, _sha
from tests.unit.test_sdxl_probe_workspace import _operator


def _micro_fixture(*, source_fault=None, suffix=b""):
    _, policy, records = _fixture(fault=source_fault, historical_suffix=suffix)
    crop_pointer = ImageEvaluationArtifactMember.model_validate(policy["crop_set"])
    crops = json.loads(records[crop_pointer])
    value, _ = _command_value()
    value["crop_set"] = policy["crop_set"]
    value["crop_set_semantic_sha256"] = crops["crop_set_sha256"]
    value["training_authorization"] = crops["training_authorization"]
    value["training_samples"] = [
        {
            "sample_id": member["sample_id"],
            "source_image": {
                **policy["crop_set"],
                "member_path": member["member_path"],
                "schema_ref": "eom://schemas/image-provider/local-image-science-visual-crop/1.0",
                "media_type": "image/png",
                "sha256": member["sha256"],
            },
            "source_width_px": member["width_px"],
            "source_height_px": member["height_px"],
            "source_caption_en": member["caption_en"],
            "source_caption_sha256": member["caption_sha256"],
            "redaction_boxes": [],
        }
        for member in crops["members"]
        if member["partition"] == "TRAIN"
    ]
    for partition, field in (
        ("VALIDATION", "validation_sample_ids"),
        ("HOLDOUT", "holdout_sample_ids"),
    ):
        value[field] = [
            member["sample_id"] for member in crops["members"] if member["partition"] == partition
        ]
    pngs = {_sha(_png(index)): _png(index) for index in range(24)}
    for sample in value["training_samples"]:
        pointer = ImageEvaluationArtifactMember.model_validate(sample["source_image"])
        records[pointer] = pngs[pointer.sha256]
    return LocalImageSdxlLoraMicroCommand.model_validate(_seal_command(value)), records


def _prepared(monkeypatch):
    command, records = _micro_fixture()
    reader = _Reader(records)
    monkeypatch.setattr(admission, "resolve_control_artifact_member", reader)
    monkeypatch.setattr(sources, "resolve_control_artifact_member", reader)
    return admission.prepare_sdxl_micro_inputs(object(), command), reader


def test_micro_admission_pins_exact_16_train_inputs_and_no_reserved_pixels(monkeypatch):
    prepared, reader = _prepared(monkeypatch)
    assert len(prepared.files) == 19
    assert len([pointer for pointer in reader.calls if pointer.media_type == "image/png"]) == 16
    assert len(reader.calls) == len(set(reader.calls))
    assert [member.member_path for member in prepared.files] == sorted(
        member.member_path for member in prepared.files
    )
    for sample in prepared.command.training_samples:
        assert sample.staged_member_path in {member.member_path for member in prepared.files}
    assert all(
        sample_id not in str([member.member_path for member in prepared.files])
        for sample_id in (
            *prepared.command.validation_sample_ids,
            *prepared.command.holdout_sample_ids,
        )
    )


@pytest.mark.parametrize(
    "fault", ["old_result", "crop_geometry", "oversized", "revision", "dimensions"]
)
def test_invalid_declaration_fails_before_any_training_png(monkeypatch, fault):
    command, records = _micro_fixture(
        source_fault=fault if fault in {"old_result", "crop_geometry", "oversized"} else None
    )
    if fault in {"revision", "dimensions"}:
        value = command.model_dump(mode="json")
        if fault == "revision":
            value["training_samples"][-1]["source_image"]["artifact_revision_id"] = (
                "rev_" + "f" * 32
            )
            with pytest.raises(ValueError, match="does not bind crop revision"):
                LocalImageSdxlLoraMicroCommand.model_validate(_seal_command(value))
            return
        else:
            value["training_samples"][-1]["source_width_px"] += 1
        command = LocalImageSdxlLoraMicroCommand.model_validate(_seal_command(value))
    reader = _Reader(records)
    monkeypatch.setattr(admission, "resolve_control_artifact_member", reader)
    monkeypatch.setattr(sources, "resolve_control_artifact_member", reader)
    with pytest.raises((admission.SdxlMicroAdmissionError, sources.SdxlProbeAdmissionError)):
        admission.prepare_sdxl_micro_inputs(object(), command)
    assert all(pointer.media_type != "image/png" for pointer in reader.calls)


def test_micro_handoff_reuses_exclusive_readonly_staging_and_preserves_existing(
    monkeypatch, tmp_path
):
    prepared, _ = _prepared(monkeypatch)
    root, worker, ownership = _operator(monkeypatch, tmp_path)
    staged = handoff.stage_sdxl_micro_inputs(prepared, workspace_parent=root, worker=worker)
    assert staged.systemd_unit == (
        f"eom-image-sdxl-lora-micro-probe@{prepared.command.training_run_id}.service"
    )
    assert ownership[-1] == (staged.workspace, worker.uid, worker.gid)
    for member in prepared.files:
        assert (staged.workspace / member.member_path).read_bytes() == member.payload
    with pytest.raises(handoff.SdxlProbeHandoffError, match="WORKSPACE_EXISTS"):
        handoff.stage_sdxl_micro_inputs(prepared, workspace_parent=root, worker=worker)


def test_bad_training_member_fails_before_any_workspace(monkeypatch, tmp_path):
    prepared, _ = _prepared(monkeypatch)
    root, worker, _ = _operator(monkeypatch, tmp_path)
    with pytest.raises(handoff.SdxlProbeHandoffError, match="MEMBERS_INVALID"):
        handoff.stage_sdxl_micro_inputs(
            replace(prepared, files=prepared.files[:-1]), workspace_parent=root, worker=worker
        )
    assert list(root.iterdir()) == []


def test_micro_dispatch_cannot_use_inference_workspace_or_other_unit(monkeypatch):
    monkeypatch.setattr(handoff.os, "geteuid", lambda: 0)
    run = "imgsdxlmicrotrainrun_" + "a" * 32
    staged = handoff.StagedSdxlProbe(
        Path("/srv/eom/image-training-workspaces") / run,
        f"eom-image-sdxl-lora-micro-probe@{run}.service",
        "sha256:" + "b" * 64,
    )
    calls = []
    monkeypatch.setattr(handoff.subprocess, "run", lambda *args, **kw: calls.append(args))
    handoff.dispatch_sdxl_micro_probe(staged)
    with pytest.raises(handoff.SdxlProbeHandoffError, match="DISPATCH_INVALID"):
        handoff.dispatch_sdxl_micro_probe(replace(staged, workspace=Path("/tmp") / run))
    assert len(calls) == 1


def test_micro_command_publication_uses_existing_idempotent_owner():
    command, _ = _micro_fixture()
    publisher = _Publisher()
    service = LocalImageTrainingControlArtifactPublisher(publisher, source_commit="c" * 40)
    pointer = service.commit_sdxl_micro_command(command)
    assert pointer.sha256 == _sha(content_json_bytes(command.model_dump(mode="json")))
    assert publisher.arguments["artifact_type"] == SDXL_MICRO_COMMAND_ARTIFACT_TYPE
    identity = publisher.arguments["idempotency_key"]
    assert command.command_sha256.removeprefix("sha256:") in str(identity)
    service.commit_sdxl_micro_command(command)
    assert publisher.arguments["idempotency_key"] == identity
