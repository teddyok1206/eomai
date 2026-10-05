"""Synthetic native geometry gates; no real model/GPU or quality acceptance."""

from __future__ import annotations

import io
import json
import os
import sys
from contextlib import contextmanager
from types import SimpleNamespace

import numpy as np
import pytest
from eom_image_contracts import (
    LocalImageRuntime,
    content_json_bytes,
    content_sha256,
    text_sha256,
    validate_contract,
)
from eom_image_contracts.sdxl_evaluation_codec import (
    parse_sdxl_evaluation_command,
    parse_sdxl_evaluation_result,
)
from eom_image_contracts.sdxl_native_geometry import (
    LocalImageSdxlNativeGeometryCommand,
    SdxlNativeGeometryNumerics,
    geometry_dimensions,
    validate_sdxl_native_geometry_result,
)
from eom_image_provider import cli
from eom_image_provider import sdxl_lora_material as material
from eom_image_provider import sdxl_native_geometry as worker
from eom_image_provider.provider import GeneratedBackground, ProviderError
from eom_image_provider.sdxl_lineart_backend import SdxlLineartSession
from eom_orchestrator import sdxl_probe_workspace as handoff
from jsonschema.exceptions import ValidationError as SchemaError
from PIL import Image
from pydantic import ValidationError

from tests.unit.test_sdxl_lora_evaluation_contracts import _seal
from tests.unit.test_sdxl_native_evaluation import _fixture, _payloads, _prepare
from tests.unit.test_sdxl_probe_workspace import _operator


def _geometry_fixture():
    old, records = _fixture()
    sources = worker.parse_sdxl_native_evaluation_sources(old, **_payloads(old, records))
    value = old.model_dump(mode="json")
    value.update(
        schema_version="local-image-sdxl-lora-evaluation-command/1.3",
        case_relation="ADMITTED_NATIVE_TRAIN_GEOMETRY_DIAGNOSTIC_NOT_HOLDOUT",
        conditioning_policy="SYNTHETIC_BLACK_T2I_ZERO_NO_INITIALIZER/1.0",
        cases=[
            {
                "sample_id": s.sample_id,
                "native_canvas": s.canvas,
                "training_caption_sha256": s.training_caption_sha256,
            }
            for s in sources.training_command.training_samples[:2]
        ],
        negative_prompt_sha256=text_sha256(sources.baseline.cases[0].negative_prompt_en),
        numerics=SdxlNativeGeometryNumerics().model_dump(mode="json"),
        budget={
            "maximum_generations": 8,
            "maximum_duration_ms": 60000,
            "maximum_peak_gpu_memory_bytes": 1024**3,
        },
    )
    return LocalImageSdxlNativeGeometryCommand.model_validate(_seal(value)), records, sources


def test_closed_schema_dispatch_and_old_family_rejection(monkeypatch):
    command, records, sources = _geometry_fixture()
    assert parse_sdxl_evaluation_command(command.model_dump(mode="json")) == command
    for old in (
        "sdxl-lora-evaluation-command",
        "sdxl-lora-evaluation-command-v2",
        "sdxl-lora-evaluation-command-v3",
    ):
        with pytest.raises(SchemaError):
            validate_contract(old, command.model_dump(mode="json"))
    prepared, reader = _prepare(monkeypatch, command, records)
    assert len(prepared.files) == 7
    assert not any(pointer.media_type == "image/png" for pointer in reader.calls)
    assert not any(file.member_path.endswith(".png") for file in prepared.files)
    assert prepared.manifest == sources.manifest


@pytest.mark.parametrize(
    "fault",
    ["sample", "caption", "canvas", "negative", "duplicates", "budget", "scale", "conditioning"],
)
def test_case_policy_mismatch_precedes_binary_admission(monkeypatch, fault):
    command, records, _ = _geometry_fixture()
    value = command.model_dump(mode="json")
    if fault == "sample":
        value["cases"][0]["sample_id"] = "imgsourcecrop_" + "f" * 32
    elif fault == "caption":
        value["cases"][0]["training_caption_sha256"] = "sha256:" + "f" * 64
    elif fault == "canvas":
        value["cases"][0]["native_canvas"] = "PORTRAIT_768X1024"
    elif fault == "negative":
        value["negative_prompt_sha256"] = "sha256:" + "f" * 64
    elif fault == "duplicates":
        value["cases"][1] = value["cases"][0]
    elif fault == "budget":
        value["budget"]["maximum_generations"] = 4
    elif fault == "scale":
        value["numerics"]["adapter_conditioning_scale"] = 0.8
    else:
        value["conditioning_policy"] = "FIT_GRAYSCALE_INVERT_832X512/1.0"
    with pytest.raises((ValueError, ValidationError, SchemaError)):
        invalid = LocalImageSdxlNativeGeometryCommand.model_validate(_seal(value))
        _prepare(monkeypatch, invalid, records)


def _stage(monkeypatch, tmp_path):
    command, records, sources = _geometry_fixture()
    prepared, _ = _prepare(monkeypatch, command, records)
    tmp_path.chmod(0o700)
    for file in prepared.files:
        path = tmp_path / file.member_path
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.write_bytes(file.payload)
        path.chmod(0o600)
    original_read, original_verify = material.read_staged_member, worker.verify_staged_member

    def read(root, path, **kwargs):
        assert kwargs.pop("expected_owner_uid") == 0
        return original_read(root, path, expected_owner_uid=os.geteuid(), **kwargs)

    def verify(root, path, **kwargs):
        assert kwargs.pop("expected_owner_uid") == 0
        return original_verify(root, path, expected_owner_uid=os.geteuid(), **kwargs)

    monkeypatch.setattr(material, "read_staged_member", read)
    monkeypatch.setattr(worker, "verify_staged_member", verify)
    monkeypatch.setattr(worker, "resolve_sdxl_stack", lambda *a, **k: object())

    @contextmanager
    def lease(*args):
        yield

    monkeypatch.setattr(worker, "acquire_gpu_lease", lease)
    return prepared, sources


class _Backend:
    def __init__(self, sources, fault=None):
        self.sources, self.fault, self.calls, self.arms = sources, fault, [], []

    @contextmanager
    def open(self, stack, *, style_adapter=None):
        self.arms.append("BASE" if style_adapter is None else "LORA")
        yield self

    def generate_geometry(self, **kwargs):
        self.calls.append(kwargs)
        if self.fault == "second" and len(self.calls) == 2:
            raise ProviderError("SDXL_PROBE_OOM")
        if self.fault == "unknown":
            raise RuntimeError("unexpected backend")
        dims = geometry_dimensions(kwargs["canvas"])
        image = Image.new("RGB", dims if self.fault != "shape" else (32, 32), "white")
        stream = io.BytesIO()
        image.save(stream, format="PNG")
        deps = self.sources.training_command.dependencies
        runtime = LocalImageRuntime(
            python_version=deps.python_version,
            torch_version=deps.torch_version,
            diffusers_version=deps.diffusers_version,
            transformers_version=deps.transformers_version,
            cuda_version="12.8",
            gpu_name="synthetic GPU",
            compute_capability="12.0",
            peak_gpu_memory_bytes=2 * 1024**3 if self.fault == "memory" else 1024,
        )
        return GeneratedBackground(png_bytes=stream.getvalue(), runtime=runtime)


@pytest.mark.parametrize("fault", [None, "second", "unknown", "shape", "memory"])
def test_raw_generation_and_terminal_replay_without_model_gpu_or_writes(
    monkeypatch, tmp_path, fault
):
    prepared, sources = _stage(monkeypatch, tmp_path)
    backend = _Backend(sources, fault)
    result = worker.run_sdxl_native_geometry(
        command=prepared.command,
        workspace=tmp_path,
        model_store_root=tmp_path,
        gpu_lock=tmp_path / "unused.lock",
        backend=backend,
    )
    assert result.status == ("SUCCEEDED" if fault is None else "FAILED")
    assert len(result.outputs) == (8 if fault is None else 1 if fault == "second" else 0)
    assert result.generation_calls == len(backend.calls)
    assert parse_sdxl_evaluation_result(result.model_dump(mode="json")) == result
    validate_sdxl_native_geometry_result(prepared.command, sources, result)
    if fault is None:
        assert backend.arms == ["BASE", "LORA"]
        samples = {s.sample_id: s for s in sources.training_command.training_samples}
        for output, call in zip(result.outputs, backend.calls, strict=True):
            assert call["prompt"] == samples[output.sample_id].training_caption_en
            assert call["numerics"].adapter_conditioning_scale == 0
    before = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}

    def forbidden(*a, **k):
        raise AssertionError("terminal replay attempted side effect")

    for name in (
        "resolve_sdxl_stack",
        "acquire_gpu_lease",
        "load_sdxl_lora_material",
        "write_staged_member",
    ):
        monkeypatch.setattr(worker, name, forbidden)
    replay = worker.run_sdxl_native_geometry(
        command=prepared.command,
        workspace=tmp_path,
        model_store_root=tmp_path,
        gpu_lock=tmp_path / "unused.lock",
        backend=backend,
    )
    assert replay == result
    assert before == {
        p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()
    }


@pytest.mark.parametrize(
    "fault", ["missing", "hash", "extra", "schema", "order", "raw_geometry", "calls"]
)
def test_terminal_tampering_is_not_repaired_or_regenerated(monkeypatch, tmp_path, fault):
    prepared, sources = _stage(monkeypatch, tmp_path)
    backend = _Backend(sources)
    args = dict(
        command=prepared.command,
        workspace=tmp_path,
        model_store_root=tmp_path,
        gpu_lock=tmp_path / "unused",
        backend=backend,
    )
    result = worker.run_sdxl_native_geometry(**args)
    path = tmp_path / result.outputs[0].member_path
    if fault == "missing":
        path.unlink()
    elif fault == "hash":
        path.write_bytes(b"wrong")
    elif fault == "extra":
        (path.parent / "extra.png").write_bytes(b"wrong")
    else:
        value = result.model_dump(mode="json")
        if fault == "schema":
            value["schema_version"] = "local-image-sdxl-lora-evaluation-result/1.2"
        elif fault == "order":
            value["outputs"].reverse()
        elif fault == "raw_geometry":
            value["outputs"][0]["width_px"] = 1024
        else:
            value["generation_calls"] = 7
        value["result_sha256"] = content_sha256(
            {k: v for k, v in value.items() if k != "result_sha256"}
        )
        (tmp_path / "result.json").write_bytes(content_json_bytes(value))
    with pytest.raises(ProviderError, match="SDXL_PROBE_OUTPUT_INVALID"):
        worker.run_sdxl_native_geometry(**args)
    assert len(backend.calls) == 8


@pytest.mark.parametrize("outcome", ["SUCCEEDED", "FAILED"])
def test_shared_workspace_and_cli_replay_do_not_need_gpu_lease(
    monkeypatch, tmp_path, capsys, outcome
):
    command, records, _ = _geometry_fixture()
    prepared, _ = _prepare(monkeypatch, command, records)
    parent, identity, _ = _operator(monkeypatch, tmp_path)
    staged = handoff.stage_sdxl_lora_evaluation_inputs(
        prepared,
        workspace_parent=parent,
        worker=identity,
    )
    assert len(tuple(staged.workspace.rglob("*.png"))) == 0
    assert staged.systemd_unit.startswith("eom-image-sdxl-lora-evaluation@")
    monkeypatch.setattr(cli, "load_sdxl_lora_evaluation_command", lambda *a: command)

    def forbidden(*a, **k):
        raise AssertionError("CLI claimed GPU before replay")

    monkeypatch.setattr(cli, "acquire_gpu_lease", forbidden)
    monkeypatch.setattr(
        cli,
        "run_sdxl_native_geometry",
        lambda **kwargs: SimpleNamespace(model_dump=lambda **k: {"status": outcome}),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "eom-local-image",
            "sdxl-lora-evaluation",
            "--command",
            str(staged.workspace / "command.json"),
            "--workspace",
            str(staged.workspace),
            "--model-store-root",
            str(parent),
            "--gpu-lock",
            str(parent / "lock"),
        ],
    )
    if outcome == "FAILED":
        with pytest.raises(SystemExit) as exc:
            cli.main()
        assert exc.value.code == 1
    else:
        assert cli.main() is None
    assert json.loads(capsys.readouterr().out)["status"] == outcome


@pytest.mark.parametrize("fault", ["metadata", "weights", "unknown_outputs"])
def test_invalid_or_unknown_handoff_never_claims_gpu(monkeypatch, tmp_path, fault):
    prepared, sources = _stage(monkeypatch, tmp_path)
    if fault == "unknown_outputs":
        (tmp_path / "outputs").mkdir(mode=0o700)
    else:
        name = (
            "inputs/baseline-command.json"
            if fault == "metadata"
            else "inputs/adapter/adapter_model.safetensors"
        )
        (tmp_path / name).write_bytes(b"tampered")

    def forbidden(*args, **kwargs):
        raise AssertionError("invalid handoff claimed GPU or model")

    monkeypatch.setattr(worker, "acquire_gpu_lease", forbidden)
    monkeypatch.setattr(worker, "resolve_sdxl_stack", forbidden)
    with pytest.raises(ProviderError):
        worker.run_sdxl_native_geometry(
            command=prepared.command,
            workspace=tmp_path,
            model_store_root=tmp_path,
            gpu_lock=tmp_path / "unused",
            backend=_Backend(sources),
        )
    assert not (tmp_path / "result.json").exists()


@pytest.mark.parametrize(
    "canvas", ["LEGACY_832X512", "SQUARE_1024", "PORTRAIT_768X1024", "LANDSCAPE_1024X768"]
)
def test_shared_numeric_backend_receives_exact_canvas_and_zero_control(monkeypatch, canvas):
    from eom_image_provider import sdxl_lineart_backend as numerical

    width, height = geometry_dimensions(canvas)
    calls = []

    def pipeline(**kwargs):
        calls.append(kwargs)
        assert kwargs["image"].getextrema() == ((0, 0), (0, 0), (0, 0))
        return SimpleNamespace(images=np.ones((1, height, width, 3), dtype=np.float32))

    class Tokenizer:
        model_max_length = 77

        def __call__(self, *a, **k):
            return {"input_ids": [0, 1]}

    pipeline.tokenizer = pipeline.tokenizer_2 = Tokenizer()
    torch = SimpleNamespace(
        Generator=lambda **k: SimpleNamespace(manual_seed=lambda s: s),
        cuda=SimpleNamespace(
            synchronize=lambda i: None,
            get_device_capability=lambda i: (12, 0),
            get_device_name=lambda i: "fixture",
            max_memory_allocated=lambda i: 1024,
            OutOfMemoryError=MemoryError,
        ),
        version=SimpleNamespace(cuda="12.8"),
        __version__="2.7.1+cu128",
    )
    monkeypatch.setattr(
        numerical.metadata, "version", lambda p: "0.35.2" if p == "diffusers" else "4.56.2"
    )
    result = SdxlLineartSession(pipeline, torch).generate_geometry(
        prompt="one object on white",
        negative_prompt="text",
        canvas=canvas,
        numerics=SdxlNativeGeometryNumerics(),
    )
    assert calls[0]["width"] == width and calls[0]["height"] == height
    assert calls[0]["adapter_conditioning_scale"] == 0 and calls[0]["num_inference_steps"] == 30
    assert calls[0]["guidance_scale"] == 7 and "strength" not in calls[0]
    with Image.open(io.BytesIO(result.png_bytes)) as image:
        assert image.size == (width, height) and image.mode == "RGB"
