"""Native adapter consumer preserves released diagnostics and metadata-first I/O."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_image_contracts import ImageEvaluationArtifactMember, content_json_bytes, validate_contract
from eom_image_contracts.sdxl_evaluation_codec import (
    parse_sdxl_evaluation_command,
    parse_sdxl_evaluation_result,
)
from eom_image_contracts.sdxl_lora_evaluation import parse_sdxl_lora_evaluation_sources
from eom_image_contracts.sdxl_native_evaluation import (
    LocalImageSdxlNativeEvaluationCommand,
    parse_sdxl_native_evaluation_sources,
)
from eom_image_contracts.sdxl_native_lora import (
    LocalImageSdxlNativeLoraCommand,
    LocalImageSdxlNativeLoraResult,
)
from eom_image_contracts.validation import SCHEMA_FILES, SCHEMA_SHA256, load_schema
from eom_image_provider import sdxl_lineart_probe as generation
from eom_image_provider import sdxl_lora_evaluation as worker
from eom_image_provider import sdxl_lora_material as material
from eom_image_provider.provider import ProviderError
from eom_orchestrator import sdxl_lora_evaluation_inputs as admission
from eom_orchestrator import sdxl_probe_inputs as baseline_sources
from eom_orchestrator import sdxl_probe_workspace as handoff
from eom_orchestrator.control_artifact_resolution import ControlArtifactResolutionError
from eom_orchestrator.local_image_training_control_artifacts import (
    LocalImageTrainingControlArtifactPublisher,
)
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import ValidationError

from tests.unit.test_local_image_training_control_artifacts import _Publisher
from tests.unit.test_sdxl_lora_evaluation import _Backend, _evaluation_fixture
from tests.unit.test_sdxl_lora_evaluation_contracts import _seal
from tests.unit.test_sdxl_micro_runner import _write
from tests.unit.test_sdxl_native_lora_contracts import _command_value, _result_value, _seal_result
from tests.unit.test_sdxl_probe_inputs import _Reader, _sha
from tests.unit.test_sdxl_probe_workspace import _operator


def _fixture():
    original, records = _evaluation_fixture()
    old_result = json.loads(records[original.evaluation.training_result])
    adapter_files = old_result["adapter_manifest"]["files"]
    weights = {
        p.member_path: raw for p, raw in records.items() if p.member_path.startswith("adapter/")
    }
    training = LocalImageSdxlNativeLoraCommand.model_validate(_command_value())
    result_value = _result_value(training)
    result_value["adapter_manifest"]["files"] = adapter_files
    result = LocalImageSdxlNativeLoraResult.model_validate(_seal_result(result_value))
    manifest = result.adapter_manifest
    value = original.model_dump(mode="json")
    value.update(
        schema_version="local-image-sdxl-lora-evaluation-command/1.2",
        case_relation="LEGACY_TRAIN_REFERENCE_DIAGNOSTIC_NOT_HOLDOUT",
    )
    pin = value["evaluation"]
    for field, model, family, identity in (
        ("training_command", training, "command", "b"),
        ("training_result", result, "result", "c"),
        ("adapter_manifest", manifest, "adapter-manifest", "c"),
    ):
        raw = content_json_bytes(model.model_dump(mode="json"))
        pointer = ImageEvaluationArtifactMember(
            artifact_id="artifact_" + identity * 32,
            artifact_revision_id="rev_" + identity * 32,
            member_path="manifests/sdxl-native-lora-" + family + ".json",
            schema_ref="eom://schemas/image-provider/local-image-sdxl-native-lora-"
            + family
            + "/1.0",
            media_type="application/json",
            sha256=_sha(raw),
        )
        records[pointer] = raw
        pin[field] = pointer.model_dump(mode="json")
    pin.update(
        adapter_id=manifest.adapter_id,
        adapter_revision_id=manifest.adapter_revision_id,
        adapter_manifest_sha256=manifest.manifest_sha256,
    )
    for file in manifest.files:
        pointer = ImageEvaluationArtifactMember(
            **{k: pin["training_result"][k] for k in ("artifact_id", "artifact_revision_id")},
            member_path="adapter/" + file.relative_path,
            schema_ref="eom://schemas/image-provider/local-image-lora-adapter-file/1.0",
            media_type="application/json"
            if file.relative_path.endswith(".json")
            else "application/octet-stream",
            sha256=file.sha256,
        )
        records[pointer] = weights[pointer.member_path]
    return LocalImageSdxlNativeEvaluationCommand.model_validate(_seal(value)), records


def _payloads(command, records):
    pin = command.evaluation
    return {
        "baseline_payload": records[pin.baseline_command],
        "training_command_payload": records[pin.training_command],
        "training_result_payload": records[pin.training_result],
        "manifest_payload": records[pin.adapter_manifest],
    }


def _prepare(monkeypatch, command=None, records=None, *, fault=None):
    if command is None:
        command, records = _fixture()
    reader = _Reader(records)
    monkeypatch.setattr(admission, "resolve_control_artifact_member", reader)
    monkeypatch.setattr(baseline_sources, "resolve_control_artifact_member", reader)
    calls = []
    baseline = parse_sdxl_native_evaluation_sources(command, **_payloads(command, records)).baseline
    basis = baseline_sources.resolve_sdxl_probe_sources(object(), baseline).policy.crop_set
    reader.calls.clear()

    def admit(engine, training):
        calls.append(training)
        assert not any(p.media_type != "application/json" for p in reader.calls)
        if fault == "lineage":
            raise ValueError("missing frozen native source")
        actual_basis = basis
        if fault == "basis":
            actual_basis = basis.model_copy(update={"sha256": "sha256:" + "0" * 64})
        return SimpleNamespace(
            sources=SimpleNamespace(
                batches=(
                    SimpleNamespace(
                        sources=SimpleNamespace(review=SimpleNamespace(basis_crop_set=actual_basis))
                    ),
                )
            )
        )

    monkeypatch.setattr(admission, "resolve_sdxl_native_lora_sources", admit)
    prepared = admission.prepare_sdxl_lora_evaluation_inputs(object(), command)
    assert len(calls) == 1 and isinstance(calls[0], LocalImageSdxlNativeLoraCommand)
    return prepared, reader


def test_successor_is_explicit_and_predecessor_schemas_remain_identical():
    command, records = _fixture()
    assert parse_sdxl_evaluation_command(command.model_dump(mode="json")) == command
    sources = parse_sdxl_native_evaluation_sources(command, **_payloads(command, records))
    assert sources.manifest == sources.training_result.adapter_manifest
    with pytest.raises(ValueError, match="another training family"):
        parse_sdxl_lora_evaluation_sources(command, **_payloads(command, records))
    for contract in ("sdxl-lora-evaluation-command", "sdxl-lora-evaluation-command-v2"):
        with pytest.raises(SchemaError):
            validate_contract(contract, command.model_dump(mode="json"))
    known = {
        "sdxl-lora-evaluation-command": (
            "b56392e5e8d92c01311d454ba92c79f4b107e61723abc69667fed6298c279dd2"
        ),
        "sdxl-lora-evaluation-result": (
            "d72b98f3723758ea492c98c0b8014e66c987958016a32b8b59ed902f0f6664ca"
        ),
        "sdxl-lora-evaluation-command-v2": (
            "83d6868d8dadd03f551c5d034c28c071414f2b55936fe6e37f424e3f4b180767"
        ),
        "sdxl-lora-evaluation-result-v2": (
            "259b3cd7b7b69c342d00a42a77426601132442742f80c45bcd3eb32ba703e43b"
        ),
    }
    root = Path(__file__).resolve().parents[2]
    for name in (*known, "sdxl-lora-evaluation-command-v3", "sdxl-lora-evaluation-result-v3"):
        load_schema(name)
        raw = (root / "schemas/image-provider" / SCHEMA_FILES[name]).read_bytes()
        packaged = (
            root / "packages/image_contracts/eom_image_contracts/schemas" / SCHEMA_FILES[name]
        )
        assert raw == packaged.read_bytes()
        assert "sha256:" + hashlib.sha256(raw).hexdigest() == SCHEMA_SHA256[name]
        if name in known:
            assert SCHEMA_SHA256[name] == "sha256:" + known[name]


@pytest.mark.parametrize(
    "fault", ["old_training", "stale_revision", "hash", "holdout", "activation"]
)
def test_pin_and_meaning_cannot_be_silently_upgraded(fault):
    command, _ = _fixture()
    value = command.model_dump(mode="json")
    if fault == "old_training":
        value["evaluation"]["training_command"]["schema_ref"] = (
            "eom://schemas/image-provider/local-image-sdxl-lora-micro-command/1.0"
        )
    elif fault == "stale_revision":
        value["evaluation"]["adapter_manifest"]["artifact_revision_id"] = "rev_" + "0" * 32
    elif fault == "holdout":
        value["case_relation"] = "HOLDOUT_PASS"
    elif fault == "activation":
        value["activation_policy"] = "ALLOWED"
    else:
        value["command_sha256"] = "sha256:" + "0" * 64
    if fault != "hash":
        _seal(value)
    with pytest.raises((ValidationError, SchemaError)):
        parse_sdxl_evaluation_command(value)


@pytest.mark.parametrize(
    "fault", ["hash", "noncanonical", "manifest", "early", "wrong_model", "failed_training"]
)
def test_metadata_fails_before_adapter_read(fault):
    command, records = _fixture()
    value = command.model_dump(mode="json")
    payloads = _payloads(command, records)
    if fault == "hash":
        payloads["training_result_payload"] += b" "
    elif fault == "noncanonical":
        raw = json.dumps(json.loads(payloads["training_result_payload"]), indent=2).encode()
        payloads["training_result_payload"] = raw
        value["evaluation"]["training_result"]["sha256"] = _sha(raw)
    elif fault == "manifest":
        value["evaluation"]["adapter_revision_id"] = "imgadapterrev_" + "0" * 32
    elif fault == "early":
        value["created_at"] = "2026-10-03T00:00:00Z"
    elif fault == "failed_training":
        result = json.loads(payloads["training_result_payload"])
        result.update(
            status="FAILED", error_code="IMAGE_TRAINING_EXEC_FAILED", adapter_manifest=None
        )
        raw = content_json_bytes(_seal_result(result))
        payloads["training_result_payload"] = raw
        value["evaluation"]["training_result"]["sha256"] = _sha(raw)
    else:
        from eom_image_contracts import content_sha256

        baseline = json.loads(payloads["baseline_payload"])
        baseline["model"]["model_revision_id"] = "imgmodelrev_" + "f" * 32
        baseline["command_sha256"] = content_sha256(
            {k: v for k, v in baseline.items() if k != "command_sha256"}
        )
        payloads["baseline_payload"] = content_json_bytes(baseline)
        value["evaluation"]["baseline_command"]["sha256"] = _sha(payloads["baseline_payload"])
    command = LocalImageSdxlNativeEvaluationCommand.model_validate(_seal(value))
    with pytest.raises(ValueError):
        parse_sdxl_native_evaluation_sources(command, **payloads)


@pytest.mark.parametrize("value", [[], None, {"schema_version": []}, {"schema_version": "unknown"}])
def test_closed_dispatch_rejects_malformed_and_unknown_schema(value):
    for parser in (parse_sdxl_evaluation_command, parse_sdxl_evaluation_result):
        with pytest.raises(ValueError, match="FAMILY_INVALID"):
            parser(value)


def test_metadata_first_admission_stages_no_native_training_pngs(monkeypatch):
    prepared, reader = _prepare(monkeypatch)
    assert sum(p.media_type == "image/png" for p in reader.calls) == len(prepared.baseline.cases)
    assert not any(f.member_path.startswith("inputs/targets/") for f in prepared.files)
    assert len(prepared.files) == len(prepared.baseline.cases) + 8
    assert all(_sha(f.payload) == f.sha256 for f in prepared.files)


@pytest.mark.parametrize("fault", ["lineage", "basis"])
def test_canonical_lineage_or_frozen_basis_mismatch_prevents_media(monkeypatch, fault):
    with pytest.raises(ValueError, match=r"missing frozen|CROP_REVISION_MISMATCH"):
        _prepare(monkeypatch, fault=fault)


def test_missing_metadata_prevents_pixels_and_weights(monkeypatch):
    command, records = _fixture()
    del records[command.evaluation.training_result]
    reader = _Reader(records)
    monkeypatch.setattr(admission, "resolve_control_artifact_member", reader)
    with pytest.raises(ControlArtifactResolutionError):
        admission.prepare_sdxl_lora_evaluation_inputs(object(), command)
    assert all(p.media_type == "application/json" for p in reader.calls)


def test_existing_handoff_and_idempotent_command_publisher(monkeypatch, tmp_path):
    prepared, _ = _prepare(monkeypatch)
    root, owner, _ = _operator(monkeypatch, tmp_path)
    staged = handoff.stage_sdxl_lora_evaluation_inputs(
        prepared, workspace_parent=root, worker=owner
    )
    assert (
        staged.systemd_unit
        == "eom-image-sdxl-lora-evaluation@" + prepared.command.run_id + ".service"
    )
    with pytest.raises(handoff.SdxlProbeHandoffError, match="WORKSPACE_EXISTS"):
        handoff.stage_sdxl_lora_evaluation_inputs(prepared, workspace_parent=root, worker=owner)
    publisher = LocalImageTrainingControlArtifactPublisher.__new__(
        LocalImageTrainingControlArtifactPublisher
    )
    publisher.publisher, publisher.source_commit = _Publisher(), "a" * 40
    one = publisher.commit_sdxl_lora_evaluation_command(prepared.command)
    two = publisher.commit_sdxl_lora_evaluation_command(prepared.command)
    assert one == two and one.schema_ref.endswith("/1.2")
    assert publisher.publisher.arguments["idempotency_key"].endswith(
        prepared.command.command_sha256[7:]
    )


@pytest.mark.parametrize("fault", [None, "second", "unexpected"])
def test_worker_preserves_baseline_and_replays_without_model(monkeypatch, tmp_path, fault):
    prepared, _ = _prepare(monkeypatch)
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
    backend = _Backend(fault=fault)
    command = worker.load_sdxl_lora_evaluation_command(workspace, workspace / "command.json")
    assert command == prepared.command
    result = worker.run_sdxl_lora_evaluation(
        command=command, workspace=workspace, model_store_root=workspace, backend=backend
    )
    assert result.status == ("SUCCEEDED" if fault is None else "FAILED")
    assert result.schema_version.endswith("/1.2")
    expected_pairs = [(c, s) for c in prepared.baseline.cases for s in c.seeds]
    for generated, (case, seed) in zip(
        backend.generated_inputs,
        expected_pairs[: len(backend.generated_inputs)],
        strict=True,
    ):
        assert (generated["prompt"], generated["negative_prompt"], generated["seed"]) == (
            case.prompt_en,
            case.negative_prompt_en,
            seed,
        )
    calls = backend.calls

    def forbidden(*a, **kw):
        raise AssertionError("terminal replay must not load model or generate")

    monkeypatch.setattr(worker, "generate_sdxl_probe_evidence", forbidden)
    assert (
        worker.run_sdxl_lora_evaluation(
            command=command, workspace=workspace, model_store_root=workspace, backend=backend
        )
        == result
    )
    assert backend.calls == calls
    corrupted_member = result.outputs[0].member_path if result.outputs else "result.json"
    _write(workspace / corrupted_member, b"corrupt")
    with pytest.raises(ProviderError):
        worker.run_sdxl_lora_evaluation(
            command=command, workspace=workspace, model_store_root=workspace, backend=backend
        )
    assert backend.calls == calls
