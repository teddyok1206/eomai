"""Native training reuses the protected handoff, not a parallel worker/queue framework."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest
from eom_image_contracts import content_json_bytes
from eom_orchestrator import sdxl_native_lora_inputs as inputs
from eom_orchestrator import sdxl_probe_workspace as handoff
from eom_orchestrator.sdxl_probe_inputs import SdxlProbeInputMember

from tests.unit.test_sdxl_native_lora_sources import _fixture
from tests.unit.test_sdxl_probe_workspace import _operator


def _prepared(monkeypatch):
    command, records, pixels, *_ = _fixture(monkeypatch)
    monkeypatch.setattr(
        inputs,
        "resolve_control_artifact_members",
        lambda _e, reads: tuple(
            records[r.pointer]
            if r.pointer.media_type != "image/png"
            else pixels[r.pointer.member_path.removeprefix("targets/").removesuffix(".png")]
            for r in reads
        ),
    )
    return inputs.prepare_sdxl_native_lora_inputs(object(), command)


def test_native_handoff_pins_closed_inputs_once_and_uses_distinct_unit(monkeypatch, tmp_path):
    prepared = _prepared(monkeypatch)
    root, worker, ownership = _operator(monkeypatch, tmp_path)
    staged = handoff.stage_sdxl_native_lora_inputs(prepared, workspace_parent=root, worker=worker)
    assert (
        staged.systemd_unit
        == f"eom-image-sdxl-native-lora@{prepared.command.training_run_id}.service"
    )
    assert (staged.workspace / "command.json").read_bytes() == content_json_bytes(
        prepared.command.model_dump(mode="json")
    )
    assert ownership[-1] == (staged.workspace, worker.uid, worker.gid)
    for member in prepared.files:
        assert (staged.workspace / member.member_path).read_bytes() == member.payload
    with pytest.raises(handoff.SdxlProbeHandoffError, match="WORKSPACE_EXISTS"):
        handoff.stage_sdxl_native_lora_inputs(prepared, workspace_parent=root, worker=worker)


@pytest.mark.parametrize(
    "fault", ["hash", "self_declared_hash", "missing", "foreign", "duplicate", "order"]
)
def test_invalid_native_handoff_never_creates_workspace(monkeypatch, tmp_path, fault):
    prepared = _prepared(monkeypatch)
    root, worker, _ = _operator(monkeypatch, tmp_path)
    files = list(prepared.files)
    if fault in {"hash", "self_declared_hash"}:
        index = next(i for i, f in enumerate(files) if f.member_path.startswith("inputs/targets/"))
        original = files[index]
        raw = b"changed"
        sha = original.sha256 if fault == "hash" else "sha256:" + hashlib.sha256(raw).hexdigest()
        files[index] = SdxlProbeInputMember(original.member_path, sha, raw)
    elif fault == "missing":
        files.pop()
    elif fault == "foreign":
        files.append(SdxlProbeInputMember("unexpected.bin", "sha256:" + "f" * 64, b"foreign"))
    elif fault == "duplicate":
        files.append(files[-1])
    else:
        files.reverse()
    with pytest.raises((ValueError, handoff.SdxlProbeHandoffError)):
        handoff.stage_sdxl_native_lora_inputs(
            replace(prepared, files=tuple(files)), workspace_parent=root, worker=worker
        )
    assert list(root.iterdir()) == []


def test_native_dispatch_is_fixed_to_one_unit_parent_and_namespace(monkeypatch):
    monkeypatch.setattr(handoff.os, "geteuid", lambda: 0)
    run_id = "imgsdxlnativetrainrun_" + "a" * 32
    staged = handoff.StagedSdxlProbe(
        Path("/srv/eom/image-training-workspaces") / run_id,
        f"eom-image-sdxl-native-lora@{run_id}.service",
        "sha256:" + "b" * 64,
    )
    calls = []
    monkeypatch.setattr(handoff.subprocess, "run", lambda args, **kw: calls.append((args, kw)))
    handoff.dispatch_sdxl_native_lora(staged)
    assert calls[0][0] == ["systemctl", "start", "--no-block", staged.systemd_unit]
    for invalid in (
        replace(staged, workspace=Path("/tmp") / run_id),
        replace(staged, systemd_unit="eom-image-sdxl-lora-micro-probe@" + run_id + ".service"),
        replace(staged, command_sha256="unbound"),
    ):
        with pytest.raises(handoff.SdxlProbeHandoffError, match="DISPATCH_INVALID"):
            handoff.dispatch_sdxl_native_lora(invalid)
    assert len(calls) == 1


def test_native_unit_preserves_shared_gpu_lock_and_isolated_worker_boundaries():
    root = Path(__file__).resolve().parents[2]
    unit = (root / "infra/systemd/eom-image-sdxl-native-lora@.service").read_text()
    for required in (
        "User=eom-image",
        "Group=eom-image",
        "sdxl-native-lora --command",
        "--gpu-lock /var/lib/eom-image/gpu0.lock",
        "PrivateNetwork=true",
        "NoNewPrivileges=true",
        "ProtectHome=true",
        "CapabilityBoundingSet=\n",
        "InaccessiblePaths=/mnt/nas",
        "InaccessiblePaths=/etc/eom",
        "InaccessiblePaths=/home/eom/EOM\n",
        "InaccessiblePaths=/root/.codex",
        "InaccessiblePaths=/var/run/docker.sock",
        "CUBLAS_WORKSPACE_CONFIG=:4096:8",
        "ReadWritePaths=/srv/eom/image-training-workspaces/%i",
        "Restart=no",
    ):
        assert required in unit


def test_operator_preflight_is_metadata_only_and_disposes_connection(monkeypatch):
    import sys
    from types import SimpleNamespace

    from scripts.image_trainer import stage_sdxl_native_lora as operator

    prepared = _prepared(monkeypatch)
    disposed = []
    engine = SimpleNamespace(dispose=lambda: disposed.append(True))
    monkeypatch.setattr(operator.os, "geteuid", lambda: 0)
    monkeypatch.setattr(operator, "build_engine", lambda: engine)
    monkeypatch.setattr(
        operator,
        "resolve_control_artifact_member",
        lambda *_a, **_k: content_json_bytes(prepared.command.model_dump(mode="json")),
    )
    monkeypatch.setattr(
        operator,
        "resolve_sdxl_native_lora_sources",
        lambda *_a: SimpleNamespace(sources=SimpleNamespace(targets=tuple(range(12)))),
    )
    monkeypatch.setattr(
        operator,
        "prepare_sdxl_native_lora_inputs",
        lambda *_a: pytest.fail("metadata preflight read PNGs"),
    )
    monkeypatch.setattr(
        operator, "dispatch_sdxl_native_lora", lambda *_a: pytest.fail("preflight dispatched")
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "stage",
            "--artifact-id",
            "artifact_" + "a" * 32,
            "--artifact-revision-id",
            "rev_" + "b" * 32,
            "--sha256",
            "sha256:" + "c" * 64,
            "--preflight-only",
        ],
    )
    operator.main()
    assert disposed == [True]
