"""Numerical lifecycle simulated without a GPU or scientific-quality claim."""

from __future__ import annotations

import os
import subprocess
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_image_contracts.models import ImageEvaluationArtifactMember, content_json_bytes
from eom_image_provider import sdxl_pair_inference as pair
from eom_image_provider import sdxl_validation_comparison as worker
from eom_image_provider.provider import ProviderError
from eom_image_provider.sdxl_canny_pixels import (
    canny_conditioning_canvas_png,
    sdxl_canny_native_source_canvas,
    sdxl_canny_source_canvas,
)
from eom_image_provider.sdxl_comparison_command import load_sdxl_comparison_command
from eom_orchestrator import sdxl_probe_workspace as handoff
from eom_orchestrator import sdxl_validation_inputs as admission

from scripts.image_trainer import sdxl_validation_publication as publication
from tests.unit.test_sdxl_learned_comparison import _Backend
from tests.unit.test_sdxl_micro_runner import _write
from tests.unit.test_sdxl_probe_workspace import _operator
from tests.unit.test_sdxl_validation_comparison import _fixture, _sha


def _stage(tmp_path, monkeypatch):
    command, _, _ = _fixture(tmp_path, monkeypatch)
    prepared = admission.prepare_sdxl_validation_inputs(object(), command)
    root = tmp_path / "validation"
    root.mkdir(mode=0o700)
    for file in prepared.files:
        _write(root / file.member_path, file.payload)
    leases = []

    class Clock:
        @staticmethod
        def now(_zone):
            # Fixture history deliberately spaces predecessor timestamps in the future.
            return datetime.now(UTC) + timedelta(seconds=10)

    monkeypatch.setattr(worker, "datetime", Clock)

    @contextmanager
    def lease(_path):
        leases.append("ENTER")
        try:
            yield
        finally:
            leases.append("EXIT")

    # Preserve recorded provenance; CPU extraction is an explicit test adapter.
    runtime = prepared.metadata.sources.configuration.sources.spatial_sources.preparation.runtime

    def canny(canvas, *, policy):
        return canny_conditioning_canvas_png(
            canvas,
            policy=policy,
            extractor=lambda gray, **kwargs: b"\xff" + b"\x00" * (len(gray) - 1),
        )

    monkeypatch.setattr(pair, "acquire_gpu_lease", lease)
    monkeypatch.setattr(worker, "resolve_sdxl_stack", lambda *a, **k: object())
    monkeypatch.setattr(worker, "resolve_sdxl_canny_controller", lambda *a, **k: object())
    monkeypatch.setattr(worker, "read_canny_runtime", lambda: runtime)
    monkeypatch.setattr(worker, "canny_conditioning_canvas_png", canny)
    monkeypatch.setattr(worker.metadata, "version", lambda name: "11.3.0")
    return prepared, root, leases


def _run(prepared, root, backend):
    return worker.run_sdxl_validation_comparison(
        command=prepared.command,
        workspace=root,
        model_store_root=root / "models",
        gpu_lock=root / "gpu.lock",
        backend_factory=lambda *args: backend,
    )


@pytest.mark.parametrize("fault", [None, "second", "oom", "unexpected"])
def test_reserved_cases_once_and_transform_model_gpu_free_replay(tmp_path, monkeypatch, fault):
    prepared, root, leases = _stage(tmp_path, monkeypatch)
    backend = _Backend(fault)
    result = _run(prepared, root, backend)
    assert result.status == ("SUCCEEDED" if fault is None else "FAILED")
    assert leases == ["ENTER", "EXIT"]
    assert load_sdxl_comparison_command(root, root / "command.json") == prepared.command
    if fault is None:
        assert len(result.outputs) == 24
        assert backend.arms == ["BASE", "LORA"]
        assert [row["conditioning"] for row in backend.received[:12]] == [
            (root / entry.case.staged_member_path).read_bytes() for entry in prepared.command.cases
        ]
        assert [row["prompt"] for row in backend.received[:12]] == [
            entry.case.prompt_en for entry in prepared.command.cases
        ]
    for trace, entry in zip(result.inputs, prepared.command.cases, strict=True):
        canvas = sdxl_canny_native_source_canvas(
            (root / entry.case.staged_member_path).read_bytes(),
            width_px=64,
            height_px=64,
        )
        assert trace.initialization_rgb_sha256 == _sha(canvas.convert("RGB").tobytes())
        assert canvas.getpixel((0, 0)) == 255

    def forbidden(*a, **k):
        raise AssertionError("terminal replay repeated a transform, model or GPU call")

    for name in (
        "resolve_sdxl_stack",
        "resolve_sdxl_canny_controller",
        "read_canny_runtime",
        "load_sdxl_lora_material",
        "sdxl_canny_native_source_canvas",
        "canny_conditioning_canvas_png",
        "run_sdxl_pair_inference",
    ):
        monkeypatch.setattr(worker, name, forbidden)
    assert _run(prepared, root, backend) == result
    assert leases == ["ENTER", "EXIT"]


@pytest.mark.parametrize("fault", ["control", "initializer", "extra", "link", "result", "raw"])
def test_bad_terminal_evidence_never_reexecutes_gpu(tmp_path, monkeypatch, fault):
    prepared, root, leases = _stage(tmp_path, monkeypatch)
    backend = _Backend()
    result = _run(prepared, root, backend)
    if fault in {"control", "initializer"}:
        directory = "conditionings" if fault == "control" else "initializers"
        target = root / directory / (result.inputs[0].case_id + ".png")
        target.write_bytes(b"broken")
    elif fault == "extra":
        _write(root / "conditionings/extra.png", b"broken")
    elif fault == "link":
        (root / "initializers/extra.png").symlink_to(root / "result.json")
    else:
        target = root / ("result.json" if fault == "result" else result.outputs[0].raw_member_path)
        target.write_bytes(b"broken")
    with pytest.raises(ProviderError, match="SDXL_PROBE_OUTPUT_INVALID"):
        _run(prepared, root, backend)
    assert leases == ["ENTER", "EXIT"] and backend.calls == 24


def test_corrupt_source_fails_before_pixel_model_output_or_gpu(tmp_path, monkeypatch):
    prepared, root, leases = _stage(tmp_path, monkeypatch)
    (root / prepared.command.cases[0].case.staged_member_path).write_bytes(b"broken")
    backend = _Backend()
    with pytest.raises(ProviderError):
        _run(prepared, root, backend)
    assert not leases and not backend.calls and not (root / "outputs").exists()


def test_native_fit_does_not_relax_released_prepared_input(tmp_path, monkeypatch):
    prepared, root, _ = _stage(tmp_path, monkeypatch)
    payload = (root / prepared.command.cases[0].case.staged_member_path).read_bytes()
    policy = prepared.metadata.sources.configuration.sources.spatial_sources.preparation.policy
    with pytest.raises(ProviderError, match="SDXL_CANNY_INPUT_INVALID"):
        sdxl_canny_source_canvas(payload, policy=policy)
    assert sdxl_canny_native_source_canvas(payload, width_px=64, height_px=64).size == (832, 512)
    with pytest.raises(ProviderError):
        sdxl_canny_native_source_canvas(payload, width_px=63, height_px=64)


def test_supported_handoff_uses_existing_fixed_template_only(tmp_path, monkeypatch):
    command, _, _ = _fixture(tmp_path, monkeypatch)
    prepared = admission.prepare_sdxl_validation_inputs(object(), command)
    parent, owner, _ = _operator(monkeypatch, tmp_path)
    staged = handoff.stage_sdxl_validation_inputs(prepared, workspace_parent=parent, worker=owner)
    assert staged.systemd_unit == "eom-image-sdxl-learned-comparison@" + command.run_id + ".service"
    with pytest.raises(handoff.SdxlProbeHandoffError, match="WORKSPACE_EXISTS"):
        handoff.stage_sdxl_validation_inputs(prepared, workspace_parent=parent, worker=owner)


@pytest.mark.parametrize(
    "fault", [None, "initializer-transform", "raw-publication", "canonical", "command"]
)
def test_publication_readmits_sources_and_exact_transforms_before_mutation(
    tmp_path, monkeypatch, fault
):
    prepared, root, _ = _stage(tmp_path, monkeypatch)
    result = _run(prepared, root, _Backend())
    events = []
    command_raw = content_json_bytes(prepared.command.model_dump(mode="json"))
    pointer = ImageEvaluationArtifactMember.model_validate(
        {
            **prepared.command.configuration_anchor.model_dump(mode="json"),
            "member_path": "manifests/sdxl-validation-comparison-command.json",
            "schema_ref": "eom://schemas/image-provider/local-image-sdxl-validation-comparison-command/1.0",
            "sha256": _sha(command_raw),
        }
    )
    monkeypatch.setattr(
        publication,
        "resolve_control_artifact_member",
        lambda *a, **k: command_raw if fault != "command" else b"broken",
    )

    def readmit(*args):
        events.append("CANONICAL_READMIT")
        if fault == "canonical":
            raise ValueError("canonical source hash mismatch")
        return prepared

    class Publisher:
        def __init__(self, engine):
            pass

        def publish(self, **kwargs):
            events.append("ARTIFACT_COMMIT")
            assert len(kwargs["members"]) == 73  # result + 24 derived + 48 raw/final
            assert not any(member.file_name.startswith("inputs/") for member in kwargs["members"])
            assert kwargs["idempotency_key"].endswith(prepared.command.command_sha256[7:])
            return kwargs

    monkeypatch.setattr(publication, "prepare_sdxl_validation_inputs", readmit)
    monkeypatch.setattr(publication, "ControlFileSetPublisher", Publisher)

    def verify(_workspace, expected):
        verified = worker.verify_sdxl_validation_transforms(_workspace)
        assert content_json_bytes(verified.model_dump(mode="json")) == expected

    monkeypatch.setattr(publication, "verify_reserved_transforms_cpu", verify)
    if fault == "initializer-transform":
        monkeypatch.setattr(
            worker,
            "sdxl_canny_native_source_canvas",
            lambda *a, **k: sdxl_canny_native_source_canvas(
                (root / prepared.command.cases[1].case.staged_member_path).read_bytes(),
                width_px=64,
                height_px=64,
            ),
        )
    if fault == "raw-publication":
        from eom_image_provider import sdxl_lineart_probe as raster

        monkeypatch.setattr(raster, "sdxl_publication", lambda *a: b"broken")

    def publish():
        return publication.publish_sdxl_validation_comparison(
            object(),
            prepared.command,
            command_pointer=pointer,
            workspace=root,
            worker_uid=os.geteuid(),
            source_commit="a" * 40,
            created_at=result.completed_at + timedelta(seconds=1),
        )

    if fault is None:
        first, second = publish(), publish()
        assert first["idempotency_key"] == second["idempotency_key"]
        assert events == ["CANONICAL_READMIT", "ARTIFACT_COMMIT"] * 2
        assert result.status == "SUCCEEDED"
    else:
        with pytest.raises((ValueError, ProviderError)):
            publish()
        assert events == ([] if fault == "command" else ["CANONICAL_READMIT"])


def test_future_command_rejected_before_any_transform_or_gpu(tmp_path, monkeypatch):
    prepared, root, leases = _stage(tmp_path, monkeypatch)

    class Clock:
        @staticmethod
        def now(_zone):
            return prepared.command.created_at - timedelta(seconds=1)

    monkeypatch.setattr(worker, "datetime", Clock)
    backend = _Backend()
    with pytest.raises(ProviderError, match="SDXL_PROBE_INPUT_INVALID"):
        _run(prepared, root, backend)
    assert not backend.calls and not leases and not (root / "initializers").exists()


@pytest.mark.parametrize("fault", [None, "exit", "large", "mismatch", "timeout", "path"])
def test_cpu_verification_fixed_identity_no_database_or_gpu_environment(monkeypatch, fault):
    calls = []
    reply = b"canonical-result"

    def run(args, **kwargs):
        calls.append((args, kwargs))
        assert args[:4] == ["/usr/sbin/runuser", "--user", "eom-image", "--"]
        assert args[4:7] == ["/srv/eom/conda/envs/eom-image-trainer/bin/python", "-I", "-c"]
        assert kwargs["timeout"] == 60 and not kwargs["check"]
        assert kwargs["env"]["CUDA_VISIBLE_DEVICES"] == ""
        assert not any("DATABASE" in key or "PASSWORD" in key for key in kwargs["env"])
        assert "'torch' not in sys.modules" in args[7] and "sqlalchemy" not in args[7]
        if fault == "timeout":
            raise subprocess.TimeoutExpired(args, 60)
        output = (
            b"x" * (256 * 1024 + 1)
            if fault == "large"
            else (b"wrong" if fault == "mismatch" else reply)
        )
        return SimpleNamespace(returncode=1 if fault == "exit" else 0, stdout=output)

    monkeypatch.setattr(publication.subprocess, "run", run)
    workspace = Path("/srv/eom/image-training-workspaces/imgsdxlvalcmprun_" + "a" * 32)
    if fault == "path":
        workspace = Path("/tmp/untrusted-workspace")
    if fault is None:
        publication.verify_reserved_transforms_cpu(workspace, reply)
    else:
        with pytest.raises(ValueError):
            publication.verify_reserved_transforms_cpu(workspace, reply)
    assert len(calls) == (0 if fault == "path" else 1)
