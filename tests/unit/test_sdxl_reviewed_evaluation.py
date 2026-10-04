"""Successor diagnostic fixtures preserve old meaning and never imply holdout quality."""

from __future__ import annotations

import copy
import os
from datetime import UTC, datetime

import pytest
from eom_image_contracts import ImageEvaluationArtifactMember, content_json_bytes, validate_contract
from eom_image_contracts.sdxl_reviewed_evaluation import LocalImageSdxlReviewedEvaluationCommand
from eom_image_contracts.sdxl_reviewed_micro import parse_sdxl_reviewed_micro_sources
from eom_image_provider import sdxl_lineart_probe as generation
from eom_image_provider import sdxl_lora_evaluation as worker
from eom_image_provider import sdxl_lora_material as material
from eom_image_provider.provider import ProviderError
from eom_orchestrator import sdxl_lora_evaluation_inputs as admission
from eom_orchestrator import sdxl_probe_inputs as baseline_sources
from eom_orchestrator.local_image_training_control_artifacts import (
    LocalImageTrainingControlArtifactPublisher,
)
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import ValidationError

from tests.unit.test_local_image_training_control_artifacts import _Publisher
from tests.unit.test_sdxl_lora_evaluation import _Backend, _evaluation_fixture
from tests.unit.test_sdxl_lora_evaluation_contracts import _seal
from tests.unit.test_sdxl_micro_runner import _write
from tests.unit.test_sdxl_probe_inputs import _Reader, _sha
from tests.unit.test_sdxl_reviewed_micro import _Backend as TrainingBackend
from tests.unit.test_sdxl_reviewed_micro import _prepared_fixture, _run


def _fixture(tmp_path, monkeypatch):
    root, training, training_metadata, _ = _prepared_fixture(tmp_path, monkeypatch)
    result = _run(monkeypatch, root, training, TrainingBackend())
    assert result.status == "SUCCEEDED"
    original, records = _evaluation_fixture()
    value = original.model_dump(mode="json")
    value["schema_version"] = "local-image-sdxl-lora-evaluation-command/1.1"
    value["case_relation"] = "LEGACY_TRAIN_REFERENCE_DIAGNOSTIC_NOT_HOLDOUT"
    value["created_at"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    pin = value["evaluation"]
    for field, model, version, identity in (
        ("training_command", training, "1.1", "b"),
        ("training_result", result, "1.1", "c"),
        ("adapter_manifest", result.adapter_manifest, "1.0", "c"),
    ):
        pointer = {
            **pin[field],
            "artifact_id": "artifact_" + identity * 32,
            "artifact_revision_id": "rev_" + identity * 32,
            "schema_ref": pin[field]["schema_ref"].rsplit("/", 1)[0] + "/" + version,
            "sha256": _sha(content_json_bytes(model.model_dump(mode="json"))),
        }
        records[ImageEvaluationArtifactMember.model_validate(pointer)] = content_json_bytes(
            model.model_dump(mode="json")
        )
        pin[field] = pointer
    manifest = result.adapter_manifest
    pin.update(
        adapter_id=manifest.adapter_id,
        adapter_revision_id=manifest.adapter_revision_id,
        adapter_manifest_sha256=manifest.manifest_sha256,
    )
    for file in manifest.files:
        pointer = ImageEvaluationArtifactMember(
            artifact_id=pin["training_result"]["artifact_id"],
            artifact_revision_id=pin["training_result"]["artifact_revision_id"],
            member_path="adapter/" + file.relative_path,
            schema_ref="eom://schemas/image-provider/local-image-lora-adapter-file/1.0",
            media_type="application/json"
            if file.relative_path.endswith(".json")
            else "application/octet-stream",
            sha256=file.sha256,
        )
        records[pointer] = (root / "adapter" / file.relative_path).read_bytes()
    return (
        LocalImageSdxlReviewedEvaluationCommand.model_validate(_seal(value)),
        records,
        training_metadata,
    )


def _prepare(tmp_path, monkeypatch, *, lineage_fault=False):
    command, records, training_metadata = _fixture(tmp_path, monkeypatch)
    reader = _Reader(records)
    monkeypatch.setattr(admission, "resolve_control_artifact_member", reader)
    monkeypatch.setattr(baseline_sources, "resolve_control_artifact_member", reader)
    calls = []

    def admit(engine, training):
        calls.append("LINEAGE")
        if lineage_fault:
            raise ValueError("intentional missing source fixture")
        parse_sdxl_reviewed_micro_sources(training, training_metadata)

    monkeypatch.setattr(admission, "resolve_sdxl_reviewed_micro_sources", admit)
    prepared = admission.prepare_sdxl_lora_evaluation_inputs(object(), command)
    assert calls == ["LINEAGE"]
    return prepared, reader


def test_successor_pins_new_training_without_copying_training_pngs(tmp_path, monkeypatch):
    prepared, reader = _prepare(tmp_path, monkeypatch)
    command = prepared.command
    validate_contract("sdxl-lora-evaluation-command-v2", command.model_dump(mode="json"))
    assert not any(file.member_path.startswith("inputs/targets/") for file in prepared.files)
    assert sum(pin.media_type == "image/png" for pin in reader.calls) == len(
        prepared.baseline.cases
    )
    assert command.case_relation == "LEGACY_TRAIN_REFERENCE_DIAGNOSTIC_NOT_HOLDOUT"
    assert len(prepared.files) == len(prepared.baseline.cases) + 8
    with pytest.raises(SchemaError):
        validate_contract("sdxl-lora-evaluation-command", command.model_dump(mode="json"))


def test_source_lineage_failure_prevents_png_and_adapter_reads(tmp_path, monkeypatch):
    command, records, _ = _fixture(tmp_path, monkeypatch)
    reader = _Reader(records)
    monkeypatch.setattr(admission, "resolve_control_artifact_member", reader)
    monkeypatch.setattr(baseline_sources, "resolve_control_artifact_member", reader)

    def fail(*a):
        raise ValueError("missing frozen source")

    monkeypatch.setattr(admission, "resolve_sdxl_reviewed_micro_sources", fail)
    with pytest.raises(ValueError, match="missing frozen"):
        admission.prepare_sdxl_lora_evaluation_inputs(object(), command)
    assert all(pin.media_type == "application/json" for pin in reader.calls)


@pytest.mark.parametrize("fault", ["old_training", "holdout_claim", "stale_manifest", "hash"])
def test_no_silent_upgrade_of_old_training_or_holdout_claim(tmp_path, monkeypatch, fault):
    command, _, _ = _fixture(tmp_path, monkeypatch)
    value = copy.deepcopy(command.model_dump(mode="json"))
    if fault == "old_training":
        value["evaluation"]["training_command"]["schema_ref"] = (
            "eom://schemas/image-provider/local-image-sdxl-lora-micro-command/1.0"
        )
    elif fault == "holdout_claim":
        value["case_relation"] = "HOLDOUT_PASS"
    elif fault == "stale_manifest":
        value["evaluation"]["adapter_manifest"]["artifact_revision_id"] = "rev_" + "0" * 32
    else:
        value["command_sha256"] = "sha256:" + "0" * 64
    if fault != "hash":
        value = _seal(value)
    with pytest.raises(ValidationError):
        LocalImageSdxlReviewedEvaluationCommand.model_validate(value)


def test_worker_fixes_inputs_and_terminal_replay_does_not_generate_again(tmp_path, monkeypatch):
    prepared, _ = _prepare(tmp_path, monkeypatch)
    workspace = tmp_path / "evaluation"
    workspace.mkdir(mode=0o700)
    for file in prepared.files:
        _write(workspace / file.member_path, file.payload)
    original_read = material.read_staged_member

    def read(root, member, **kwargs):
        assert kwargs.pop("expected_owner_uid") == 0
        return original_read(root, member, expected_owner_uid=os.geteuid(), **kwargs)

    monkeypatch.setattr(material, "read_staged_member", read)
    monkeypatch.setattr(generation, "resolve_sdxl_stack", lambda *a, **kw: object())
    backend = _Backend()
    command = worker.load_sdxl_lora_evaluation_command(workspace, workspace / "command.json")
    assert command == prepared.command
    result = worker.run_sdxl_lora_evaluation(
        command=command, workspace=workspace, model_store_root=workspace, backend=backend
    )
    assert result.status == "SUCCEEDED" and result.case_relation == command.case_relation
    validate_contract("sdxl-lora-evaluation-result-v2", result.model_dump(mode="json"))
    for generated, (case, seed) in zip(
        backend.generated_inputs,
        (
            (baseline_case, seed)
            for baseline_case in prepared.baseline.cases
            for seed in baseline_case.seeds
        ),
        strict=True,
    ):
        assert (generated["prompt"], generated["negative_prompt"], generated["seed"]) == (
            case.prompt_en,
            case.negative_prompt_en,
            seed,
        )
    calls = backend.calls
    assert (
        worker.run_sdxl_lora_evaluation(
            command=command, workspace=workspace, model_store_root=workspace, backend=backend
        )
        == result
    )
    assert backend.calls == calls
    _write(workspace / result.outputs[0].member_path, b"corrupt")
    with pytest.raises(ProviderError):
        worker.run_sdxl_lora_evaluation(
            command=command, workspace=workspace, model_store_root=workspace, backend=backend
        )
    assert backend.calls == calls


def test_publisher_uses_successor_schema_without_new_identity_on_replay(tmp_path, monkeypatch):
    command, _, _ = _fixture(tmp_path, monkeypatch)
    publisher = LocalImageTrainingControlArtifactPublisher.__new__(
        LocalImageTrainingControlArtifactPublisher
    )
    publisher.publisher, publisher.source_commit = _Publisher(), "a" * 40
    assert publisher.commit_sdxl_lora_evaluation_command(command).schema_ref.endswith("/1.1")
