from __future__ import annotations

import hashlib
import os
import stat
import subprocess
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_orchestrator import sdxl_probe_workspace as handoff
from eom_orchestrator.sdxl_probe_inputs import SdxlProbeInputMember, prepare_sdxl_probe_inputs

from tests.unit.test_sdxl_probe_inputs import _fixture


def _prepared(monkeypatch):
    command, _, records = _fixture()
    monkeypatch.setattr(
        "eom_orchestrator.sdxl_probe_inputs.resolve_control_artifact_member",
        lambda _engine, pointer, **_kwargs: records[pointer],
    )
    return prepare_sdxl_probe_inputs(object(), command)


def _operator(monkeypatch, tmp_path):
    root = tmp_path / "workspaces"
    root.mkdir(mode=0o3770)
    root.chmod(0o3770)
    original = Path.lstat

    def metadata(path):
        value = original(path)
        if path == root:
            return SimpleNamespace(st_uid=0, st_gid=os.getgid(), st_mode=value.st_mode)
        return value

    monkeypatch.setattr(Path, "lstat", metadata)
    monkeypatch.setattr(handoff.os, "geteuid", lambda: 0)
    ownership = []
    monkeypatch.setattr(handoff.os, "chown", lambda *args: ownership.append(args))
    monkeypatch.setattr(handoff.os, "fchown", lambda *args: ownership.append(args))
    return (
        root,
        handoff.SdxlProbeWorkspaceOwner(os.getuid() or 1000, os.getgid() or 1000),
        ownership,
    )


def test_exclusive_handoff_pins_every_byte_and_changes_owner_only_after_inputs(
    monkeypatch, tmp_path
):
    prepared = _prepared(monkeypatch)
    root, worker, ownership = _operator(monkeypatch, tmp_path)
    staged = handoff.stage_sdxl_probe_inputs(prepared, workspace_parent=root, worker=worker)
    assert staged.command_sha256 == prepared.command.command_sha256
    assert staged.systemd_unit == f"eom-image-sdxl-lineart-probe@{prepared.command.run_id}.service"
    assert stat.S_IMODE(staged.workspace.stat().st_mode) == 0o700
    assert stat.S_IMODE((staged.workspace / "inputs").stat().st_mode) == 0o550
    assert not (staged.workspace / "outputs").exists()
    for member in prepared.files:
        path = staged.workspace / member.member_path
        assert path.read_bytes() == member.payload
        assert stat.S_IMODE(path.stat().st_mode) == 0o440
    assert ownership[-1] == (staged.workspace, worker.uid, worker.gid)
    with pytest.raises(handoff.SdxlProbeHandoffError, match="WORKSPACE_EXISTS"):
        handoff.stage_sdxl_probe_inputs(prepared, workspace_parent=root, worker=worker)
    assert (staged.workspace / "command.json").read_bytes() == prepared.files[0].payload


@pytest.mark.parametrize("fault", ["hash", "identity", "missing", "extra", "duplicate", "order"])
def test_bad_member_sets_fail_before_workspace_creation(monkeypatch, tmp_path, fault):
    prepared = _prepared(monkeypatch)
    root, worker, _ = _operator(monkeypatch, tmp_path)
    members = list(prepared.files)
    if fault in {"hash", "identity"}:
        payload = b"changed"
        sha = (
            members[0].sha256
            if fault == "hash"
            else "sha256:" + hashlib.sha256(payload).hexdigest()
        )
        members[0] = SdxlProbeInputMember(members[0].member_path, sha, payload)
    elif fault == "missing":
        members.pop()
    elif fault == "extra":
        members.append(SdxlProbeInputMember("../../escape", members[0].sha256, members[0].payload))
    elif fault == "duplicate":
        members.append(members[-1])
    else:
        members.reverse()
    with pytest.raises(handoff.SdxlProbeHandoffError, match="MEMBERS_INVALID"):
        handoff.stage_sdxl_probe_inputs(
            replace(prepared, files=tuple(members)), workspace_parent=root, worker=worker
        )
    assert list(root.iterdir()) == []


@pytest.mark.parametrize("fault", ["operator", "worker", "mode", "link", "relative", "parent"])
def test_operator_identity_and_no_link_parent_boundary(monkeypatch, tmp_path, fault):
    prepared = _prepared(monkeypatch)
    root, worker, _ = _operator(monkeypatch, tmp_path)
    if fault == "operator":
        monkeypatch.setattr(handoff.os, "geteuid", lambda: 1000)
    elif fault == "worker":
        worker = handoff.SdxlProbeWorkspaceOwner(0, worker.gid)
    elif fault == "mode":
        root.chmod(0o777)
    elif fault == "link":
        linked = tmp_path / "link"
        linked.symlink_to(root)
        root = linked
    elif fault == "relative":
        root = Path("relative")
    else:
        root = root / ".." / "workspaces"
    with pytest.raises(handoff.SdxlProbeHandoffError):
        handoff.stage_sdxl_probe_inputs(prepared, workspace_parent=root, worker=worker)


def test_fixed_systemd_dispatch_and_ambiguous_start_are_not_retried(monkeypatch):
    monkeypatch.setattr(handoff.os, "geteuid", lambda: 0)
    run_id = "imgsdxlproberun_" + "a" * 32
    staged = handoff.StagedSdxlProbe(
        Path("/srv/eom/image-workspaces") / run_id,
        f"eom-image-sdxl-lineart-probe@{run_id}.service",
        "sha256:" + "b" * 64,
    )
    calls = []

    def start(args, **kwargs):
        calls.append((args, kwargs))

    monkeypatch.setattr(handoff.subprocess, "run", start)
    handoff.dispatch_sdxl_probe(staged)
    assert calls[0][0] == ["systemctl", "start", "--no-block", staged.systemd_unit]
    assert calls[0][1]["timeout"] == 30
    for invalid in (
        replace(staged, workspace=Path("/tmp") / run_id),
        replace(staged, systemd_unit="other.service"),
        replace(staged, command_sha256="unbound"),
    ):
        with pytest.raises(handoff.SdxlProbeHandoffError, match="DISPATCH_INVALID"):
            handoff.dispatch_sdxl_probe(invalid)
    assert len(calls) == 1

    def ambiguous(*args, **kwargs):
        calls.append((args, kwargs))
        raise subprocess.TimeoutExpired("systemctl", 30)

    monkeypatch.setattr(handoff.subprocess, "run", ambiguous)
    with pytest.raises(handoff.SdxlProbeHandoffError, match="UNCONFIRMED"):
        handoff.dispatch_sdxl_probe(staged)
    assert len(calls) == 2
