from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from eom_image_contracts import content_json_bytes
from eom_orchestrator import informative_lineart_extraction_inputs as admission
from eom_orchestrator import sdxl_probe_workspace as handoff
from eom_orchestrator.local_image_training_control_artifacts import (
    LocalImageTrainingControlArtifactPublisher,
)

from tests.unit.test_informative_lineart_extraction_contracts import _command
from tests.unit.test_local_image_training_control_artifacts import _Publisher
from tests.unit.test_sdxl_probe_workspace import _operator


def _prepared(monkeypatch, *, fault=None):
    command, baseline, manifest, records = _command()
    records[command.baseline_command] = content_json_bytes(baseline.model_dump(mode="json"))
    records[command.extractor_manifest] = content_json_bytes(manifest.model_dump(mode="json"))
    if fault == "canonical":
        records[command.baseline_command] += b"\n"
    if fault == "missing":
        records[command.extractor_manifest] = b"{}"
    if fault == "lineage":
        records[baseline.prompt_policy] = b"{}"
    reads = []

    def reader(_engine, pointer, **_kwargs):
        reads.append(pointer)
        return records[pointer]

    def batch(_engine, bounded):
        reads.append(tuple(read.pointer for read in bounded))
        return tuple(records[read.pointer] for read in bounded)

    monkeypatch.setattr(admission, "resolve_control_artifact_member", reader)
    monkeypatch.setattr(
        "eom_orchestrator.sdxl_probe_inputs.resolve_control_artifact_member", reader
    )
    monkeypatch.setattr(admission, "resolve_control_artifact_members", batch)
    return command, records, reads


def test_complete_original_lineage_precedes_one_batch_png_read_and_pinned_staging(monkeypatch):
    command, records, reads = _prepared(monkeypatch)
    prepared = admission.prepare_informative_lineart_extraction_inputs(object(), command)
    assert reads[-1] == tuple(case.reference_image for case in prepared.baseline.cases)
    assert len(prepared.files) == len(command.case_ids) + 3
    assert tuple(member.member_path for member in prepared.files) == tuple(
        sorted(member.member_path for member in prepared.files)
    )
    for case in prepared.baseline.cases:
        file = next(
            member for member in prepared.files if member.member_path == case.staged_member_path
        )
        assert file.payload == records[case.reference_image]
        assert file.sha256 == case.reference_image.sha256


def test_command_publication_reuses_authoritative_publisher_and_semantic_replay_key():
    command, _, _, _ = _command()
    publisher = _Publisher()
    boundary = LocalImageTrainingControlArtifactPublisher(
        publisher, source_commit=command.source_commit
    )
    pointer = boundary.commit_informative_lineart_extraction_command(command)
    first = dict(publisher.arguments)
    assert pointer == boundary.commit_informative_lineart_extraction_command(command)
    assert first == publisher.arguments
    assert first["payload"] == content_json_bytes(command.model_dump(mode="json"))
    assert (
        first["idempotency_key"]
        == "local-image-informative-lineart-extraction-command:" + command.command_sha256[7:]
    )
    assert (
        pointer.schema_ref
        == "eom://schemas/image-provider/local-image-informative-lineart-extraction-command/1.0"
    )
    assert pointer.sha256 != command.command_sha256


@pytest.mark.parametrize("fault", ["canonical", "missing", "lineage"])
def test_invalid_metadata_prevents_any_png_materialization(monkeypatch, fault):
    command, _, reads = _prepared(monkeypatch, fault=fault)
    with pytest.raises(ValueError):
        admission.prepare_informative_lineart_extraction_inputs(object(), command)
    assert not any(isinstance(read, tuple) for read in reads)


def test_extraction_exclusive_handoff_and_exact_member_set(monkeypatch, tmp_path):
    command, _, _ = _prepared(monkeypatch)
    prepared = admission.prepare_informative_lineart_extraction_inputs(object(), command)
    root, worker, ownership = _operator(monkeypatch, tmp_path)
    staged = handoff.stage_informative_lineart_extraction_inputs(
        prepared, workspace_parent=root, worker=worker
    )
    assert (
        staged.systemd_unit == f"eom-image-informative-lineart-extraction@{command.run_id}.service"
    )
    assert ownership[-1] == (staged.workspace, worker.uid, worker.gid)
    assert all(
        (staged.workspace / file.member_path).read_bytes() == file.payload
        for file in prepared.files
    )
    with pytest.raises(handoff.SdxlProbeHandoffError, match="EXISTS"):
        handoff.stage_informative_lineart_extraction_inputs(
            prepared, workspace_parent=root, worker=worker
        )
    other = root / "other"
    other.mkdir(mode=0o3770)
    other.chmod(0o3770)
    # Validate content membership before writes, not merely the filename/run ID.
    with pytest.raises(handoff.SdxlProbeHandoffError, match="MEMBERS_INVALID"):
        handoff.stage_informative_lineart_extraction_inputs(
            replace(prepared, files=prepared.files[:-1]), workspace_parent=root, worker=worker
        )


def test_extraction_dispatch_reuses_fixed_training_workspace_boundary(monkeypatch):
    command, _, _, _ = _command()
    staged = handoff.StagedSdxlProbe(
        Path("/srv/eom/image-training-workspaces") / command.run_id,
        f"eom-image-informative-lineart-extraction@{command.run_id}.service",
        command.command_sha256,
    )
    calls = []
    monkeypatch.setattr(handoff.os, "geteuid", lambda: 0)
    monkeypatch.setattr(
        handoff.subprocess, "run", lambda args, **kwargs: calls.append((args, kwargs))
    )
    handoff.dispatch_informative_lineart_extraction(staged)
    assert calls[0][0] == ["systemctl", "start", "--no-block", staged.systemd_unit]
    with pytest.raises(handoff.SdxlProbeHandoffError, match="DISPATCH_INVALID"):
        handoff.dispatch_informative_lineart_extraction(
            replace(staged, workspace=Path("/tmp") / command.run_id)
        )
    assert len(calls) == 1
