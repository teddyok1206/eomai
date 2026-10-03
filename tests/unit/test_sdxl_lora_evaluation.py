from __future__ import annotations

import json
import os
import sys
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_image_contracts import (
    ImageEvaluationArtifactMember,
    LocalImageSdxlLoraEvaluationCommand,
    LocalImageSdxlLoraEvaluationResult,
    LocalImageSdxlLoraMicroResult,
    content_json_bytes,
    content_sha256,
    validate_sdxl_lora_evaluation_result,
)
from eom_image_provider import sdxl_lineart_probe as generation
from eom_image_provider import sdxl_lora_evaluation as worker
from eom_image_provider import sdxl_lora_material as material
from eom_image_provider.provider import ProviderError
from eom_orchestrator import sdxl_lora_evaluation_inputs as admission
from eom_orchestrator import sdxl_probe_inputs as sources
from eom_orchestrator import sdxl_probe_workspace as handoff
from eom_orchestrator.control_artifact_resolution import ControlArtifactResolutionError
from eom_orchestrator.local_image_training_control_artifacts import (
    LocalImageTrainingControlArtifactPublisher,
)

from tests.unit.test_local_image_training_control_artifacts import _Publisher
from tests.unit.test_local_image_training_runner import _valid_safetensors
from tests.unit.test_sdxl_lineart_probe import FakeBackend
from tests.unit.test_sdxl_lora_evaluation_contracts import _seal
from tests.unit.test_sdxl_lora_micro_contracts import _reseal_result, _result_value, _seal_adapter
from tests.unit.test_sdxl_micro_inputs import _micro_fixture
from tests.unit.test_sdxl_probe_inputs import _fixture as _probe_fixture
from tests.unit.test_sdxl_probe_inputs import _Reader, _sha
from tests.unit.test_sdxl_probe_workspace import _operator


def _evaluation_fixture():
    training, records = _micro_fixture()
    baseline, _, _ = _probe_fixture()
    config = (
        content_json_bytes(
            {
                "base_model_name_or_path": "PINNED_LOCAL_MODEL_REVISION",
                "bias": "none",
                "inference_mode": True,
                "lora_alpha": 8,
                "peft_type": "LORA",
                "r": 8,
                "target_modules": ["to_k", "to_out.0", "to_q", "to_v"],
                "task_type": None,
            }
        )
        + b"\n"
    )
    payloads = {"adapter_config.json": config, "adapter_model.safetensors": _valid_safetensors()}
    result = _result_value(training)
    result["adapter_manifest"]["files"] = [
        {"relative_path": name, "size_bytes": len(raw), "sha256": _sha(raw)}
        for name, raw in sorted(payloads.items())
    ]
    result["adapter_manifest"] = _seal_adapter(result["adapter_manifest"])
    result = LocalImageSdxlLoraMicroResult.model_validate(_reseal_result(result))
    manifest = result.adapter_manifest
    assert manifest is not None

    def metadata(model, family, identity):
        raw = content_json_bytes(model.model_dump(mode="json"))
        pointer = ImageEvaluationArtifactMember(
            artifact_id="artifact_" + identity * 32,
            artifact_revision_id="rev_" + identity * 32,
            member_path="manifests/" + family + ".json",
            schema_ref="eom://schemas/image-provider/local-image-" + family + "/1.0",
            media_type="application/json",
            sha256=_sha(raw),
        )
        records[pointer] = raw
        return pointer.model_dump(mode="json")

    value = _seal(
        {
            "schema_version": "local-image-sdxl-lora-evaluation-command/1.0",
            "created_at": "2026-10-03T21:10:00Z",
            "source_commit": "a" * 40,
            "purpose": "EVALUATION_ONLY_MATCHED_SDXL_LORA",
            "activation_policy": "FORBIDDEN",
            "evaluation": {
                "baseline_command": metadata(baseline, "sdxl-lineart-probe-command", "6"),
                "training_command": metadata(training, "sdxl-lora-micro-command", "7"),
                "training_result": metadata(result, "sdxl-lora-micro-result", "8"),
                "adapter_manifest": metadata(manifest, "sdxl-lora-micro-adapter-manifest", "8"),
                "adapter_id": manifest.adapter_id,
                "adapter_revision_id": manifest.adapter_revision_id,
                "adapter_manifest_sha256": manifest.manifest_sha256,
                "adapter_strength": 1.0,
            },
        }
    )
    command = LocalImageSdxlLoraEvaluationCommand.model_validate(value)
    for file in manifest.files:
        pointer = ImageEvaluationArtifactMember(
            artifact_id=command.evaluation.training_result.artifact_id,
            artifact_revision_id=command.evaluation.training_result.artifact_revision_id,
            member_path="adapter/" + file.relative_path,
            schema_ref="eom://schemas/image-provider/local-image-lora-adapter-file/1.0",
            media_type="application/json"
            if file.relative_path.endswith(".json")
            else "application/octet-stream",
            sha256=file.sha256,
        )
        records[pointer] = payloads[file.relative_path]
    return command, records


def _prepare(monkeypatch):
    command, records = _evaluation_fixture()
    reader = _Reader(records)
    monkeypatch.setattr(admission, "resolve_control_artifact_member", reader)
    monkeypatch.setattr(sources, "resolve_control_artifact_member", reader)
    prepared = admission.prepare_sdxl_lora_evaluation_inputs(object(), command)
    return prepared, reader


def test_admission_pins_baseline_training_and_adapter_once_without_reserved_pixels(monkeypatch):
    prepared, reader = _prepare(monkeypatch)
    assert len(prepared.files) == len(prepared.baseline.cases) + 8
    assert max(Counter(reader.calls).values()) == 1
    assert sum(pointer.media_type == "image/png" for pointer in reader.calls) == len(
        prepared.baseline.cases
    )
    assert all(_sha(file.payload) == file.sha256 for file in prepared.files)
    assert prepared.files[0].payload == content_json_bytes(prepared.command.model_dump(mode="json"))


@pytest.mark.parametrize("fault", ["missing", "hash", "wrong_manifest", "crop_revision"])
def test_admission_failure_precedes_any_png_or_weight_materialization(monkeypatch, fault):
    command, records = _evaluation_fixture()
    if fault in {"missing", "hash"}:
        pointer = command.evaluation.training_result
        if fault == "missing":
            del records[pointer]
        else:
            records[pointer] += b"corrupt"
    else:
        value = command.model_dump(mode="json")
        value["evaluation"]["adapter_manifest_sha256"] = "sha256:" + "f" * 64
        if fault == "crop_revision":
            pointer = command.evaluation.training_command
            training = json.loads(records[pointer])
            training["crop_set"]["sha256"] = "sha256:" + "f" * 64
            from tests.unit.test_sdxl_lora_micro_contracts import _seal_command

            records[pointer] = content_json_bytes(_seal_command(training))
            # Keep pointer byte hash stale: resolution must fail, not infer a latest command.
        command = LocalImageSdxlLoraEvaluationCommand.model_validate(_seal(value))
    reader = _Reader(records)
    monkeypatch.setattr(admission, "resolve_control_artifact_member", reader)
    monkeypatch.setattr(sources, "resolve_control_artifact_member", reader)
    with pytest.raises((ValueError, ControlArtifactResolutionError)):
        admission.prepare_sdxl_lora_evaluation_inputs(object(), command)
    assert not any(pointer.media_type != "application/json" for pointer in reader.calls)


def test_exclusive_handoff_uses_fixed_unit_and_pinned_bytes(monkeypatch, tmp_path):
    prepared, _ = _prepare(monkeypatch)
    root, owner, ownership = _operator(monkeypatch, tmp_path)
    staged = handoff.stage_sdxl_lora_evaluation_inputs(
        prepared, workspace_parent=root, worker=owner
    )
    assert (
        staged.systemd_unit
        == "eom-image-sdxl-lora-evaluation@" + prepared.command.run_id + ".service"
    )
    assert ownership[-1] == (staged.workspace, owner.uid, owner.gid)
    for file in prepared.files:
        assert (staged.workspace / file.member_path).read_bytes() == file.payload
    with pytest.raises(handoff.SdxlProbeHandoffError, match="WORKSPACE_EXISTS"):
        handoff.stage_sdxl_lora_evaluation_inputs(prepared, workspace_parent=root, worker=owner)


def test_evaluation_command_publication_uses_existing_idempotent_owner():
    command, _ = _evaluation_fixture()
    publisher = LocalImageTrainingControlArtifactPublisher.__new__(
        LocalImageTrainingControlArtifactPublisher
    )
    publisher.publisher = _Publisher()
    publisher.source_commit = "a" * 40
    pointer = publisher.commit_sdxl_lora_evaluation_command(command)
    assert pointer.schema_ref.endswith("local-image-sdxl-lora-evaluation-command/1.0")
    assert publisher.publisher.arguments["idempotency_key"].endswith(command.command_sha256[7:])


class _Backend(FakeBackend):
    def __init__(self, *, fault=None):
        super().__init__(fault=fault)
        self.generated_inputs = []

    @contextmanager
    def open(self, stack, *, style_adapter=None):
        assert style_adapter is not None and style_adapter.strength == 1.0
        self.opens += 1
        yield self

    def generate(self, **kwargs):
        self.generated_inputs.append(kwargs)
        return super().generate(**kwargs)


def _stage(monkeypatch, tmp_path):
    prepared, _ = _prepare(monkeypatch)
    tmp_path.chmod(0o700)
    for file in prepared.files:
        path = tmp_path / file.member_path
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.write_bytes(file.payload)
        path.chmod(0o600)
    original = material.read_staged_member

    def read(root, relative, **kwargs):
        assert kwargs.pop("expected_owner_uid") == 0
        return original(root, relative, expected_owner_uid=os.geteuid(), **kwargs)

    monkeypatch.setattr(material, "read_staged_member", read)
    monkeypatch.setattr(generation, "resolve_sdxl_stack", lambda *a, **k: object())
    return prepared


@pytest.mark.parametrize("fault", [None, "second", "unexpected"])
def test_worker_preserves_original_inputs_and_seals_additive_terminal_receipt(
    monkeypatch, tmp_path, fault
):
    prepared = _stage(monkeypatch, tmp_path)
    backend = _Backend(fault=fault)
    result = worker.run_sdxl_lora_evaluation(
        command=prepared.command, workspace=tmp_path, model_store_root=tmp_path, backend=backend
    )
    assert result.status == ("SUCCEEDED" if fault is None else "FAILED")
    assert result.baseline_command_sha256 == prepared.baseline.command_sha256
    validate_sdxl_lora_evaluation_result(prepared.command, prepared.baseline, result)
    calls = backend.calls
    expected = [(case, seed) for case in prepared.baseline.cases for seed in case.seeds]
    for generated, (case, seed) in zip(backend.generated_inputs, expected, strict=fault is None):
        assert generated["prompt"] == case.prompt_en
        assert generated["negative_prompt"] == case.negative_prompt_en
        assert generated["seed"] == seed
        assert generated["command"] == prepared.baseline
    again = worker.run_sdxl_lora_evaluation(
        command=prepared.command, workspace=tmp_path, model_store_root=tmp_path, backend=backend
    )
    assert again == result and backend.calls == calls and backend.opens == 1
    assert (
        worker.load_sdxl_lora_evaluation_command(tmp_path, tmp_path / "command.json")
        == prepared.command
    )


@pytest.mark.parametrize(
    "member",
    [
        "inputs/adapter/adapter_model.safetensors",
        "result.json",
        "outputs/final",
        "outputs/raw",
        "outputs/conditioning",
    ],
)
def test_replay_corruption_cannot_generate_another_output(monkeypatch, tmp_path, member):
    prepared = _stage(monkeypatch, tmp_path)
    backend = _Backend()
    worker.run_sdxl_lora_evaluation(
        command=prepared.command, workspace=tmp_path, model_store_root=tmp_path, backend=backend
    )
    path = tmp_path / member
    if path.is_dir():
        path = next(path.iterdir())
    path.write_bytes(path.read_bytes() + b"corrupt")
    calls = backend.calls
    with pytest.raises(ProviderError):
        worker.run_sdxl_lora_evaluation(
            command=prepared.command, workspace=tmp_path, model_store_root=tmp_path, backend=backend
        )
    assert backend.calls == calls


def test_unreceipted_output_is_never_replayed(monkeypatch, tmp_path):
    prepared = _stage(monkeypatch, tmp_path)
    (tmp_path / "outputs").mkdir(mode=0o700)
    backend = _Backend()
    with pytest.raises(ProviderError, match="SDXL_PROBE_OUTPUT_INVALID"):
        worker.run_sdxl_lora_evaluation(
            command=prepared.command, workspace=tmp_path, model_store_root=tmp_path, backend=backend
        )
    assert backend.calls == backend.opens == 0


@pytest.mark.parametrize("fault", ["model", "command", "strength", "coverage", "peak", "budget"])
def test_result_cannot_claim_a_different_experiment_or_incomplete_success(
    monkeypatch, tmp_path, fault
):
    prepared = _stage(monkeypatch, tmp_path)
    result = worker.run_sdxl_lora_evaluation(
        command=prepared.command, workspace=tmp_path, model_store_root=tmp_path, backend=_Backend()
    )
    value = result.model_dump(mode="json")
    if fault == "model":
        value["model"]["model_revision_id"] = "imgmodelrev_" + "d" * 32
    elif fault == "command":
        value["command_sha256"] = "sha256:" + "d" * 64
    elif fault == "strength":
        value["evaluation"]["adapter_strength"] = 0.5
    elif fault == "coverage":
        value["outputs"].pop()
        value["runtime"]["peak_gpu_memory_bytes"] = max(
            item["peak_gpu_memory_bytes"] for item in value["outputs"]
        )
    elif fault == "peak":
        value["runtime"]["peak_gpu_memory_bytes"] += 1
    else:
        value["duration_ms"] = prepared.baseline.budget.maximum_duration_ms + 1
    value["result_sha256"] = content_sha256(
        {k: v for k, v in value.items() if k != "result_sha256"}
    )
    with pytest.raises(ValueError):
        altered = LocalImageSdxlLoraEvaluationResult.model_validate(value)
        validate_sdxl_lora_evaluation_result(prepared.command, prepared.baseline, altered)


@pytest.mark.parametrize("fault", [None, "missing", "extra", "shape", "nan", "decode"])
def test_numerical_adapter_load_requires_exact_finite_rank8_unet_targets(monkeypatch, fault):
    def tensor(shape, finite=True):
        return SimpleNamespace(
            shape=shape,
            is_floating_point=lambda: True,
            isfinite=lambda: SimpleNamespace(all=lambda: SimpleNamespace(item=lambda: finite)),
        )

    state = {
        "block.to_q.lora_A.weight": tensor((8, 64)),
        "block.to_q.lora_B.weight": tensor((32, 8)),
    }
    if fault == "missing":
        state.pop("block.to_q.lora_A.weight")
    elif fault == "extra":
        state["other.weight"] = tensor((8, 64))
    elif fault == "shape":
        state["block.to_q.lora_A.weight"] = tensor((4, 64))
    elif fault == "nan":
        state["block.to_q.lora_A.weight"] = tensor((8, 64), False)

    def load(raw):
        if fault == "decode":
            raise ValueError("invalid safetensors")
        return state

    monkeypatch.setitem(sys.modules, "safetensors.torch", SimpleNamespace(load=load))
    calls = []
    unet = SimpleNamespace(
        named_modules=lambda: [
            ("block.to_q", SimpleNamespace(weight=SimpleNamespace(shape=(32, 64))))
        ],
        load_lora_adapter=lambda state, **kwargs: calls.append(("load", kwargs)),
        set_adapters=lambda name, **kwargs: calls.append(("set", kwargs)),
    )
    command, records = _evaluation_fixture()
    manifest = LocalImageSdxlLoraMicroResult.model_validate_json(
        records[command.evaluation.training_result]
    ).adapter_manifest
    adapter = material.SdxlLoraAdapterMaterial(manifest, b"weights", 0.75)
    if fault:
        with pytest.raises(ProviderError, match="SDXL_PROBE_MODEL_INVALID"):
            material.apply_sdxl_lora(unet, adapter)
        assert not calls
    else:
        material.apply_sdxl_lora(unet, adapter)
        assert calls[0][1]["prefix"] is None and calls[0][1]["local_files_only"] is True
        assert calls[0][1]["metadata"]["lora_alpha"] == 8
        assert calls[1] == ("set", {"weights": 0.75})


def test_optional_unit_does_not_change_operating_inference_environment():
    root = Path(__file__).resolve().parents[2]
    unit = (root / "infra/systemd/eom-image-sdxl-lora-evaluation@.service").read_text()
    for expected in (
        "User=eom-image",
        "Group=eom-image",
        "PrivateNetwork=true",
        "NoNewPrivileges=true",
        "InaccessiblePaths=/mnt/nas",
        "InaccessiblePaths=/home/eom/EOM",
        "InaccessiblePaths=/root/.codex",
        "ProtectSystem=strict",
        "DevicePolicy=closed",
        "Restart=no",
        "TimeoutStartSec=1830",
        "Environment=HF_HUB_OFFLINE=1",
        "Environment=TRANSFORMERS_OFFLINE=1",
        "--gpu-lock /var/lib/eom-image/gpu0.lock",
        "/srv/eom/conda/envs/eom-image-trainer/bin/eom-local-image",
    ):
        assert expected in unit
    assert "PYTHONPATH" not in unit and "sudo" not in unit
