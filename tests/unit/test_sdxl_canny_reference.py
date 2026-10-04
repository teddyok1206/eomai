"""Successor admission, exact source initialization and side-effect-free replay."""

from __future__ import annotations

import copy
import hashlib
import io
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from eom_image_contracts.models import (
    ImageEvaluationArtifactMember,
    content_json_bytes,
    content_sha256,
)
from eom_image_contracts.sdxl_canny_reference import (
    LocalImageSdxlCannyReferenceCommand,
    LocalImageSdxlCannyReferenceResult,
    SdxlCannyReferenceInitialization,
    validate_sdxl_canny_reference_result,
)
from eom_image_contracts.validation import SCHEMA_FILES, SCHEMA_SHA256
from eom_image_provider import sdxl_canny_reference as worker
from eom_image_provider.provider import ProviderError
from eom_image_provider.sdxl_canny_pixels import sdxl_canny_source_canvas
from eom_image_provider.sdxl_comparison_command import load_sdxl_comparison_command
from eom_orchestrator import sdxl_canny_comparison_inputs as previous
from eom_orchestrator import sdxl_canny_reference_inputs as admission
from eom_orchestrator import sdxl_probe_workspace as handoff
from eom_orchestrator.local_image_training_control_artifacts import (
    LocalImageTrainingControlArtifactPublisher,
)
from PIL import Image

from tests.unit.test_local_image_training_control_artifacts import _Publisher
from tests.unit.test_sdxl_canny_comparison import _run as _previous_run
from tests.unit.test_sdxl_canny_comparison import _stage as _previous_stage
from tests.unit.test_sdxl_learned_comparison import _Backend as FakeBackend
from tests.unit.test_sdxl_micro_runner import _write
from tests.unit.test_sdxl_probe_workspace import _operator


def _sha(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _seal(value):
    value = copy.deepcopy(value)
    value.pop("run_id", None)
    value.pop("command_sha256", None)
    value["run_id"] = "imgsdxlcannyrefrun_" + content_sha256(value)[7:39]
    value["command_sha256"] = content_sha256(value)
    return value


def _fixture(tmp_path, monkeypatch):
    old, old_root, reader, leases = _previous_stage(tmp_path, monkeypatch)
    result = _previous_run(old, old_root, FakeBackend())
    assert result.status == "SUCCEEDED"
    leases.clear()

    def pin(model, family, identity):
        raw = content_json_bytes(model.model_dump(mode="json"))
        pointer = ImageEvaluationArtifactMember(
            artifact_id="artifact_" + identity * 32,
            artifact_revision_id="rev_" + identity * 32,
            member_path="manifests/" + family + ".json",
            schema_ref="eom://schemas/image-provider/local-image-" + family + "/1.0",
            media_type="application/json",
            sha256=_sha(raw),
        )
        reader.records[pointer] = raw
        return pointer

    steps = old.sources.targets.lora.baseline.inference_steps
    initialization = SdxlCannyReferenceInitialization(
        scheduler_steps=steps, effective_denoising_steps=int(steps * 0.35)
    )
    command = LocalImageSdxlCannyReferenceCommand.model_validate(
        _seal(
            dict(
                schema_version="local-image-sdxl-canny-reference-command/1.0",
                source_commit="a" * 40,
                created_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                purpose="EVALUATION_ONLY_MATCHED_CANNY_SOURCE_INITIALIZATION",
                activation_policy="FORBIDDEN",
                spatial_command=pin(old.command, "sdxl-canny-comparison-command", "7").model_dump(
                    mode="json"
                ),
                spatial_result=pin(result, "sdxl-canny-comparison-result", "8").model_dump(
                    mode="json"
                ),
                initialization=initialization.model_dump(mode="json"),
                budget=old.command.budget.model_dump(mode="json"),
            )
        )
    )
    admitted = previous.ResolvedSdxlCannyComparisonMetadata(
        old.command,
        old.sources,
        old.source_metadata,
        tuple(
            file
            for file in old.files
            if not file.member_path.endswith(".png")
            and not file.member_path.startswith("inputs/adapter/")
        ),
    )
    trace = []

    def lineage(engine, checked):
        assert checked == old.command
        trace.append("LINEAGE")
        return admitted

    monkeypatch.setattr(admission, "resolve_sdxl_canny_comparison_metadata", lineage)
    monkeypatch.setattr(admission, "resolve_control_artifact_member", reader)

    def batch(engine, reads):
        assert trace[0] == "LINEAGE"
        trace.append("PIXELS")
        return tuple(
            reader(engine, read.pointer, maximum_bytes=read.maximum_bytes) for read in reads
        )

    monkeypatch.setattr(previous, "resolve_control_artifact_members", batch)
    monkeypatch.setattr(admission, "resolve_control_artifact_members", batch)
    for entry in old.sources.parent.cases:
        reader.records[entry.case.reference_image] = (
            tmp_path / "worker" / entry.case.staged_member_path
        ).read_bytes()
    return command, reader, trace, leases


def _stage(tmp_path, monkeypatch):
    command, reader, trace, leases = _fixture(tmp_path, monkeypatch)
    prepared = admission.prepare_sdxl_canny_reference_inputs(object(), command)
    assert trace == ["LINEAGE", "PIXELS", "PIXELS"]
    root = tmp_path / "reference"
    root.mkdir(mode=0o700)
    for file in prepared.files:
        _write(root / file.member_path, file.payload)
    monkeypatch.setattr(worker, "resolve_sdxl_stack", lambda *a, **k: object())
    monkeypatch.setattr(worker, "resolve_sdxl_canny_controller", lambda *a, **k: object())
    monkeypatch.setattr(worker.metadata, "version", lambda name: "11.3.0")
    return prepared, root, reader, leases


def _run(prepared, root, backend):
    return worker.run_sdxl_canny_reference(
        command=prepared.command,
        workspace=root,
        model_store_root=root / "models",
        gpu_lock=root / "gpu.lock",
        backend_factory=lambda *a: backend,
    )


@pytest.mark.parametrize("fault", [None, "second", "oom", "unexpected"])
def test_pinned_initializers_one_lease_and_transform_model_free_replay(
    tmp_path, monkeypatch, fault
):
    prepared, root, _, leases = _stage(tmp_path, monkeypatch)
    backend = FakeBackend(fault)
    result = _run(prepared, root, backend)
    assert result.status == ("SUCCEEDED" if fault is None else "FAILED")
    assert leases == ["ENTER", "EXIT"]
    validate_sdxl_canny_reference_result(prepared.command, prepared.sources, result)
    assert load_sdxl_comparison_command(root, root / "command.json") == prepared.command
    assert admission.sdxl_canny_reference_input_hashes(prepared) == {
        file.member_path: file.sha256 for file in prepared.files
    }
    cases = {
        entry.case.case_id: entry.case for entry in prepared.sources.spatial_sources.parent.cases
    }
    for trace in result.inputs:
        canvas = sdxl_canny_source_canvas(
            (root / cases[trace.case_id].staged_member_path).read_bytes(),
            policy=prepared.sources.spatial_sources.preparation.policy,
        ).convert("RGB")
        assert trace.initialization_rgb_sha256 == _sha(canvas.tobytes())
        assert canvas.getpixel((0, 0)) == (255, 255, 255)
    for name in (
        "resolve_sdxl_stack",
        "resolve_sdxl_canny_controller",
        "load_sdxl_lora_material",
        "sdxl_canny_source_canvas",
        "create_sdxl_pair_directories",
        "write_staged_member",
    ):
        monkeypatch.setattr(
            worker, name, lambda *a, **k: pytest.fail("terminal replay had a side effect")
        )
    before = {
        path: (path.stat().st_mtime_ns, path.read_bytes())
        for path in root.rglob("*")
        if path.is_file()
    }
    assert _run(prepared, root, FakeBackend()) == result
    assert leases == ["ENTER", "EXIT"]
    assert all(
        (path.stat().st_mtime_ns, path.read_bytes()) == stamp for path, stamp in before.items()
    )


@pytest.mark.parametrize(
    "fault", ["strength", "steps", "policy", "activation", "prompt", "quota", "hash"]
)
def test_command_cannot_change_undeclared_factors(tmp_path, monkeypatch, fault):
    command, _, _, _ = _fixture(tmp_path, monkeypatch)
    value = command.model_dump(mode="json")
    if fault == "strength":
        value["initialization"]["denoising_strength"] = 0.5
    elif fault == "steps":
        value["initialization"]["effective_denoising_steps"] = 99
    elif fault == "policy":
        value["initialization"]["policy"] = "WHITEN_OUTPUT"
    elif fault == "activation":
        value["activation_policy"] = "ALLOWED"
    elif fault == "prompt":
        value["prompt"] = "not frozen"
    elif fault == "quota":
        value["budget"]["maximum_outputs"] = 12
    else:
        value["command_sha256"] = "sha256:" + "0" * 64
    if fault != "hash":
        value = _seal(value)
    with pytest.raises(ValueError):
        LocalImageSdxlCannyReferenceCommand.model_validate(value)


@pytest.mark.parametrize("fault", ["missing", "hash", "canonical", "time"])
def test_bad_predecessor_stops_before_binary_materialization(tmp_path, monkeypatch, fault):
    command, reader, trace, _ = _fixture(tmp_path, monkeypatch)
    pin = command.spatial_result
    if fault == "missing":
        del reader.records[pin]
    elif fault == "hash":
        reader.records[pin] += b" "
    elif fault == "canonical":
        raw = json.dumps(json.loads(reader.records[pin]), indent=2).encode()
        new = pin.model_copy(update={"sha256": _sha(raw)})
        reader.records[new] = raw
        value = command.model_dump(mode="json")
        value["spatial_result"] = new.model_dump(mode="json")
        command = LocalImageSdxlCannyReferenceCommand.model_validate(_seal(value))
    else:
        value = command.model_dump(mode="json")
        value["created_at"] = "2020-01-01T00:00:00Z"
        command = LocalImageSdxlCannyReferenceCommand.model_validate(_seal(value))
    with pytest.raises((ValueError, KeyError, RuntimeError)):
        admission.prepare_sdxl_canny_reference_inputs(object(), command)
    assert "PIXELS" not in trace


@pytest.mark.parametrize(
    "fault", ["source", "control", "output", "extra", "partial", "noncanonical"]
)
def test_input_output_tampering_rejects_before_model(tmp_path, monkeypatch, fault):
    prepared, root, _, _ = _stage(tmp_path, monkeypatch)
    result = _run(prepared, root, FakeBackend())
    first = result.inputs[0].case_id
    if fault == "source":
        (root / "inputs" / (first + ".png")).write_bytes(b"bad")
    elif fault == "control":
        (root / "inputs/canny" / (first + ".png")).write_bytes(b"bad")
    elif fault == "output":
        (root / result.outputs[0].member_path).write_bytes(b"bad")
    elif fault == "extra":
        _write(root / "outputs/extra.png", b"extra")
    elif fault == "partial":
        (root / "result.json").unlink()
    else:
        (root / "result.json").write_bytes(
            json.dumps(result.model_dump(mode="json"), indent=2).encode()
        )
    monkeypatch.setattr(
        worker, "resolve_sdxl_stack", lambda *a, **k: pytest.fail("tamper reached model")
    )
    with pytest.raises(ProviderError):
        _run(prepared, root, FakeBackend())


@pytest.mark.parametrize("fault", ["source", "control", "prefix", "quality", "budget"])
def test_result_does_not_invent_provenance_or_quality(tmp_path, monkeypatch, fault):
    prepared, root, _, _ = _stage(tmp_path, monkeypatch)
    value = _run(prepared, root, FakeBackend()).model_dump(mode="json")
    if fault == "source":
        value["inputs"][0]["source_sha256"] = "sha256:" + "0" * 64
    elif fault == "control":
        value["outputs"][0]["conditioning_sha256"] = "sha256:" + "0" * 64
    elif fault == "prefix":
        value["outputs"].reverse()
    elif fault == "quality":
        value["quality_acceptance"] = "PASS"
    else:
        value["duration_ms"] = prepared.command.budget.maximum_duration_ms + 1
    value["result_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "result_sha256"}
    )
    with pytest.raises(ValueError):
        result = LocalImageSdxlCannyReferenceResult.model_validate(value)
        validate_sdxl_canny_reference_result(prepared.command, prepared.sources, result)


def test_initializer_uses_the_same_canvas_as_canny(tmp_path, monkeypatch):
    prepared, root, _, _ = _stage(tmp_path, monkeypatch)
    case = prepared.sources.spatial_sources.parent.cases[0].case
    source = (root / case.staged_member_path).read_bytes()
    seen = []
    from eom_image_provider.sdxl_canny_pixels import canny_conditioning_png

    def extractor(gray, *, width, height, policy):
        seen.append(gray)
        return b"\xff" + b"\x00" * (width * height - 1)

    canny_conditioning_png(
        source, policy=prepared.sources.spatial_sources.preparation.policy, extractor=extractor
    )
    canvas = sdxl_canny_source_canvas(
        source, policy=prepared.sources.spatial_sources.preparation.policy
    )
    assert seen == [canvas.tobytes()]
    assert Image.open(io.BytesIO(source)).size == (768, 512)


def test_exclusive_handoff_and_command_publication(tmp_path, monkeypatch):
    prepared, _, _, _ = _stage(tmp_path, monkeypatch)
    parent, owner, _ = _operator(monkeypatch, tmp_path)
    staged = handoff.stage_sdxl_canny_reference_inputs(
        prepared, workspace_parent=parent, worker=owner
    )
    assert (
        staged.systemd_unit
        == "eom-image-sdxl-learned-comparison@" + prepared.command.run_id + ".service"
    )
    with pytest.raises(handoff.SdxlProbeHandoffError, match="WORKSPACE_EXISTS"):
        handoff.stage_sdxl_canny_reference_inputs(prepared, workspace_parent=parent, worker=owner)
    publisher = LocalImageTrainingControlArtifactPublisher(
        _Publisher(), source_commit=prepared.command.source_commit
    )
    pin = publisher.commit_sdxl_canny_reference_command(prepared.command)
    assert pin.sha256 == _sha(content_json_bytes(prepared.command.model_dump(mode="json")))


def test_actual_effective_timesteps_and_unknown_reference_fail_closed(monkeypatch):
    from types import SimpleNamespace

    from eom_image_contracts.sdxl_canny_comparison import SdxlCannyControlParameters
    from eom_image_contracts.sdxl_lineart_probe import LocalImageSdxlLineartProbeCommand
    from eom_image_provider import sdxl_canny_reference_backend as reference_backend

    from tests.unit.test_sdxl_lineart_probe import _command, _png

    source = _png(size=(768, 512))
    inputs = {
        _sha(source): reference_backend.SdxlCannyReferencePixels(
            bytes([255]) * (832 * 512 * 3), _png(size=(832, 512))
        )
    }
    session = reference_backend.SdxlCannyReferenceSession(
        SimpleNamespace(num_timesteps=8),
        object(),
        SdxlCannyControlParameters(),
        SdxlCannyReferenceInitialization(scheduler_steps=20, effective_denoising_steps=7),
        inputs,
    )
    calls = []

    def generate(*args, **kwargs):
        calls.append(kwargs)
        return object()

    monkeypatch.setattr(reference_backend, "generate_sdxl_canny_background", generate)
    arguments = dict(
        prompt="line art",
        negative_prompt="color",
        seed=104729,
        command=LocalImageSdxlLineartProbeCommand.model_validate(_command()),
    )
    with pytest.raises(ProviderError, match="SDXL_PROBE_INPUT_INVALID"):
        session.generate(conditioning=b"not the pinned source", **arguments)
    assert not calls
    with pytest.raises(ProviderError, match="SDXL_PROBE_MODEL_INVALID"):
        session.generate(conditioning=source, **arguments)
    assert len(calls) == 1
    assert calls[0]["image_arguments"]["strength"] == 0.35


def test_successor_schema_closure_preserves_old_schema_bytes():
    root = Path(__file__).resolve().parents[2]
    for name in (
        "sdxl-canny-reference-command",
        "sdxl-canny-reference-result",
        "sdxl-canny-comparison-command",
        "sdxl-canny-comparison-result",
    ):
        raw = (root / "schemas/image-provider" / SCHEMA_FILES[name]).read_bytes()
        assert _sha(raw) == SCHEMA_SHA256[name]
        assert (
            raw
            == (
                root / "packages/image_contracts/eom_image_contracts/schemas" / SCHEMA_FILES[name]
            ).read_bytes()
        )
