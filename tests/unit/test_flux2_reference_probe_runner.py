from __future__ import annotations

import hashlib
import io
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from eom_image_candidate_runner.runner import (
    CandidateRunnerError,
    _verify_model,
    load_probe_command,
    run_probe,
)
from eom_image_contracts import (
    Flux2ReferenceProbeRuntime,
    LocalImageFlux2ReferenceProbeCommand,
    LocalImageModelCandidateManifest,
    content_json_bytes,
    content_sha256,
)
from PIL import Image, ImageDraw  # type: ignore[import-not-found]

from tests.unit.test_flux2_reference_probe_contracts import (
    _command_value,
    _manifest_value,
    _plan_value,
)


def _png(*, dark: int) -> bytes:
    image = Image.new("RGB", (800, 504), "white")
    drawing = ImageDraw.Draw(image)
    drawing.ellipse((180, 72, 620, 432), outline=(dark, dark, dark), width=5)
    target = io.BytesIO()
    image.save(target, format="PNG", compress_level=9, optimize=False)
    return target.getvalue()


def _sha256(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _rebuild_case(case: dict[str, Any], reference: bytes, conditioning: bytes) -> None:
    case["visual_reference"]["sha256"] = _sha256(reference)
    case["visual_reference"]["size_bytes"] = len(reference)
    case["conditioning"]["sha256"] = _sha256(conditioning)
    case["conditioning"]["size_bytes"] = len(conditioning)
    case.pop("case_id")
    case["case_id"] = "imgflux2case_" + content_sha256(case)[7:39]


def _rebuild_plan(plan: dict[str, Any]) -> None:
    plan["cases"].sort(key=lambda value: value["case_id"])
    plan.pop("plan_id")
    plan.pop("plan_sha256")
    identity_body = {
        key: field for key, field in plan.items() if key not in {"created_at", "created_by"}
    }
    plan["plan_id"] = "imgflux2probe_" + content_sha256(identity_body)[7:39]
    plan["plan_sha256"] = content_sha256(plan)


def _workspace(tmp_path: Path) -> tuple[Path, LocalImageFlux2ReferenceProbeCommand]:
    manifest = _manifest_value()
    plan = _plan_value(manifest)
    payloads: dict[str, tuple[bytes, bytes]] = {}
    for ordinal, case in enumerate(plan["cases"], start=1):
        reference = _png(dark=ordinal * 10)
        conditioning = _png(dark=ordinal * 10 + 2)
        _rebuild_case(case, reference, conditioning)
        payloads[case["subject_key"]] = (reference, conditioning)
    _rebuild_plan(plan)
    command_value = _command_value(plan)
    command = LocalImageFlux2ReferenceProbeCommand.model_validate(command_value)
    workspace = tmp_path / command.run_id
    references = workspace / "inputs" / "references"
    references.mkdir(parents=True, mode=0o700)
    workspace.chmod(0o700)
    (workspace / "inputs").chmod(0o700)
    references.chmod(0o700)
    for case in plan["cases"]:
        reference, conditioning = payloads[case["subject_key"]]
        (references / f"{case['case_id']}.png").write_bytes(reference)
        (references / f"{case['case_id']}-conditioning.png").write_bytes(conditioning)
    (workspace / command.staged_plan_path).write_bytes(content_json_bytes(plan))
    (workspace / command.staged_model_manifest_path).write_bytes(content_json_bytes(manifest))
    command_path = workspace / "command.json"
    command_path.write_bytes(content_json_bytes(command_value))
    return workspace, load_probe_command(command_path)


class _Backend:
    def prepare(self, _model_root: Path) -> Flux2ReferenceProbeRuntime:
        return Flux2ReferenceProbeRuntime(
            python_version="3.12.11",
            torch_version="2.7.1",
            diffusers_version="0.40.0",
            transformers_version="5.17.0",
            cuda_version="12.8",
            gpu_name="NVIDIA GeForce RTX 5080",
            compute_capability="12.0",
        )

    def generate(self, **_kwargs: object) -> tuple[Image.Image, int]:
        return Image.new("RGB", (800, 512), "white"), 12_000_000_000


def test_flux2_runner_writes_exact_atomic_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, command = _workspace(tmp_path)
    monkeypatch.setattr(
        "eom_image_candidate_runner.runner._verify_model",
        lambda _root, _manifest: None,
    )

    result = run_probe(workspace=workspace, command=command, backend=_Backend())

    assert result.status == "SUCCEEDED"
    assert len(result.outputs) == 6
    assert len(result.measurements) == 3
    assert not (workspace / "outputs.pending").exists()
    assert (workspace / "outputs" / "result.json").read_bytes() == content_json_bytes(
        result.model_dump(mode="json")
    )
    for output in result.outputs:
        payload = (workspace / output.relative_path).read_bytes()
        assert len(payload) == output.size_bytes
        assert _sha256(payload) == output.sha256


def test_flux2_runner_rejects_staged_hash_drift_before_inference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, command = _workspace(tmp_path)
    monkeypatch.setattr(
        "eom_image_candidate_runner.runner._verify_model",
        lambda _root, _manifest: None,
    )
    staged = command.inputs[0]
    path = workspace / staged.relative_path
    drift = bytearray(path.read_bytes())
    drift[-1] ^= 1
    path.write_bytes(drift)

    result = run_probe(workspace=workspace, command=command, backend=_Backend())

    assert result.status == "FAILED"
    assert result.error_code == "FLUX2_PROBE_INPUT_HASH_MISMATCH"
    assert list((workspace / "outputs").iterdir()) == [workspace / "outputs" / "result.json"]


def test_flux2_runner_failed_backend_publishes_only_failed_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, command = _workspace(tmp_path)
    monkeypatch.setattr(
        "eom_image_candidate_runner.runner._verify_model",
        lambda _root, _manifest: None,
    )

    class _FailingBackend(_Backend):
        def generate(self, **_kwargs: object) -> tuple[Image.Image, int]:
            raise CandidateRunnerError("FLUX2_PROBE_OOM")

    result = run_probe(workspace=workspace, command=command, backend=_FailingBackend())

    assert result.status == "FAILED"
    assert result.error_code == "FLUX2_PROBE_OOM"
    assert list((workspace / "outputs").iterdir()) == [workspace / "outputs" / "result.json"]
    assert not (workspace / "outputs.pending").exists()


def test_flux2_command_loader_rejects_noncanonical_json(tmp_path: Path) -> None:
    manifest = _manifest_value()
    command = _command_value(_plan_value(manifest))
    path = tmp_path / "command.json"
    path.write_text(json.dumps(deepcopy(command), indent=2), encoding="utf-8")

    with pytest.raises(CandidateRunnerError, match="FLUX2_PROBE_INPUT_INVALID"):
        load_probe_command(path)


def test_flux2_model_verifier_requires_exact_regular_file_set_and_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model_root = tmp_path / "model"
    model_root.mkdir()
    payload = b'{"_class_name":"Flux2KleinPipeline"}'
    (model_root / "model_index.json").write_bytes(payload)
    manifest_value = _manifest_value()
    manifest_value["files"] = [
        {
            "relative_path": "model_index.json",
            "size_bytes": len(payload),
            "sha256": _sha256(payload),
        }
    ]
    manifest_value["model_revision_id"] = (
        "imgmodelrev_"
        + content_sha256(
            {
                "upstream": manifest_value["upstream"],
                "files": manifest_value["files"],
            }
        )[7:39]
    )
    manifest_value.pop("manifest_sha256")
    manifest_value["manifest_sha256"] = content_sha256(manifest_value)
    manifest = LocalImageModelCandidateManifest.model_validate(manifest_value)
    monkeypatch.setattr("eom_image_candidate_runner.runner.MODEL_ROOT", model_root)

    _verify_model(model_root, manifest)

    (model_root / "untracked.bin").write_bytes(b"not pinned")
    with pytest.raises(CandidateRunnerError, match="FLUX2_PROBE_MODEL_INVALID"):
        _verify_model(model_root, manifest)
    (model_root / "untracked.bin").unlink()
    (model_root / "model_index.json").write_bytes(payload + b"\n")
    with pytest.raises(CandidateRunnerError, match="FLUX2_PROBE_MODEL_INVALID"):
        _verify_model(model_root, manifest)


def test_flux2_model_verifier_rejects_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model_root = tmp_path / "model"
    model_root.mkdir()
    outside = tmp_path / "outside"
    outside.write_bytes(b"unsafe")
    (model_root / "model_index.json").symlink_to(outside)
    manifest_value = _manifest_value()
    manifest = LocalImageModelCandidateManifest.model_validate(manifest_value)
    monkeypatch.setattr("eom_image_candidate_runner.runner.MODEL_ROOT", model_root)

    with pytest.raises(CandidateRunnerError, match="FLUX2_PROBE_MODEL_INVALID"):
        _verify_model(model_root, manifest)
