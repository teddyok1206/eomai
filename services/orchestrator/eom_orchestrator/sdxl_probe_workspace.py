"""Private filesystem handoff for an already-admitted bounded SDXL diagnostic."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from eom_image_contracts import content_json_bytes

from eom_orchestrator.sdxl_micro_inputs import PreparedSdxlMicroInputs
from eom_orchestrator.sdxl_probe_inputs import PreparedSdxlProbeInputs, SdxlProbeInputMember


class SdxlProbeHandoffError(RuntimeError):
    """A handoff failed without replacing inputs or submitting another identity."""


@dataclass(frozen=True, slots=True)
class SdxlProbeWorkspaceOwner:
    uid: int
    gid: int


@dataclass(frozen=True, slots=True)
class StagedSdxlProbe:
    workspace: Path
    systemd_unit: str
    command_sha256: str


def stage_sdxl_probe_inputs(
    prepared: PreparedSdxlProbeInputs,
    *,
    workspace_parent: Path,
    worker: SdxlProbeWorkspaceOwner,
) -> StagedSdxlProbe:
    """Create one exclusive workspace; preserve incomplete handoffs for diagnosis."""
    payload = content_json_bytes(prepared.command.model_dump(mode="json"))
    expected = {
        "command.json": "sha256:" + hashlib.sha256(payload).hexdigest(),
        "inputs/prompt-policy.json": prepared.command.prompt_policy.sha256,
        **{case.staged_member_path: case.reference_image.sha256 for case in prepared.command.cases},
    }
    return _stage_inputs(
        files=prepared.files,
        expected=expected,
        command_payload=payload,
        run_id=prepared.command.run_id,
        command_sha256=prepared.command.command_sha256,
        unit_template="eom-image-sdxl-lineart-probe",
        workspace_parent=workspace_parent,
        worker=worker,
    )


def stage_sdxl_micro_inputs(
    prepared: PreparedSdxlMicroInputs,
    *,
    workspace_parent: Path,
    worker: SdxlProbeWorkspaceOwner,
) -> StagedSdxlProbe:
    """The same private handoff boundary, with only the micro command's 19 members."""
    payload = content_json_bytes(prepared.command.model_dump(mode="json"))
    expected = {
        "command.json": "sha256:" + hashlib.sha256(payload).hexdigest(),
        "inputs/crop-set.json": prepared.command.crop_set.sha256,
        "inputs/authorization.json": prepared.command.training_authorization.sha256,
        **{
            sample.staged_member_path: sample.source_image.sha256
            for sample in prepared.command.training_samples
        },
    }
    return _stage_inputs(
        files=prepared.files,
        expected=expected,
        command_payload=payload,
        run_id=prepared.command.training_run_id,
        command_sha256=prepared.command.command_sha256,
        unit_template="eom-image-sdxl-lora-micro-probe",
        workspace_parent=workspace_parent,
        worker=worker,
    )


def _stage_inputs(
    *,
    files: tuple[SdxlProbeInputMember, ...],
    expected: dict[str, str],
    command_payload: bytes,
    run_id: str,
    command_sha256: str,
    unit_template: str,
    workspace_parent: Path,
    worker: SdxlProbeWorkspaceOwner,
) -> StagedSdxlProbe:
    if re.fullmatch(r"(?:imgsdxlproberun_|imgsdxlmicrotrainrun_)[0-9a-f]{32}", run_id) is None:
        raise SdxlProbeHandoffError("SDXL_PROBE_HANDOFF_IDENTITY_INVALID")
    if os.geteuid() != 0 or worker.uid <= 0 or worker.gid <= 0:
        raise SdxlProbeHandoffError("SDXL_PROBE_HANDOFF_IDENTITY_INVALID")
    if not workspace_parent.is_absolute() or ".." in workspace_parent.parts:
        raise SdxlProbeHandoffError("SDXL_PROBE_HANDOFF_ROOT_INVALID")
    current = Path(workspace_parent.root)
    for part in workspace_parent.parts[1:]:
        current /= part
        if not stat.S_ISDIR(current.lstat().st_mode):
            raise SdxlProbeHandoffError("SDXL_PROBE_HANDOFF_ROOT_INVALID")
    metadata = workspace_parent.lstat()
    if (metadata.st_uid, metadata.st_gid, stat.S_IMODE(metadata.st_mode)) != (
        0,
        worker.gid,
        0o3770,
    ):
        raise SdxlProbeHandoffError("SDXL_PROBE_HANDOFF_ROOT_INVALID")
    names = tuple(member.member_path for member in files)
    if names != tuple(sorted(expected)):
        raise SdxlProbeHandoffError("SDXL_PROBE_HANDOFF_MEMBERS_INVALID")
    for member in files:
        relative_path = PurePosixPath(member.member_path)
        if (
            relative_path.is_absolute()
            or any(part in {"", ".", ".."} for part in member.member_path.split("/"))
            or "\\" in member.member_path
            or not 0 < len(member.payload) <= 16 * 1024**2
            or member.sha256 != expected[member.member_path]
            or member.sha256 != "sha256:" + hashlib.sha256(member.payload).hexdigest()
            or (member.member_path == "command.json" and member.payload != command_payload)
        ):
            raise SdxlProbeHandoffError("SDXL_PROBE_HANDOFF_MEMBERS_INVALID")
    workspace = workspace_parent / run_id
    try:
        workspace.mkdir(mode=0o700)
    except FileExistsError as exc:
        raise SdxlProbeHandoffError("SDXL_PROBE_WORKSPACE_EXISTS") from exc
    # The worker cannot observe a partially staged tree: ownership changes only after fsync.
    directories = sorted(
        {
            parent
            for member in files
            for parent in PurePosixPath(member.member_path).parents
            if str(parent) != "."
        },
        key=lambda path: (len(path.parts), str(path)),
    )
    for relative in directories:
        directory = workspace / relative
        directory.mkdir(mode=0o700)
        os.chown(directory, 0, worker.gid)
    for member in files:
        path = workspace / member.member_path
        descriptor = os.open(
            path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o440
        )
        try:
            offset = 0
            while offset < len(member.payload):
                written = os.write(descriptor, member.payload[offset:])
                if written <= 0:
                    raise SdxlProbeHandoffError("SDXL_PROBE_HANDOFF_WRITE_FAILED")
                offset += written
            os.fchmod(descriptor, 0o440)
            os.fchown(descriptor, 0, worker.gid)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    for relative in directories:
        (workspace / relative).chmod(0o550)
    for directory in (
        *(workspace / path for path in reversed(directories)),
        workspace,
        workspace_parent,
    ):
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    os.chmod(workspace, 0o700)
    os.chown(workspace, worker.uid, worker.gid)
    return StagedSdxlProbe(
        workspace,
        f"{unit_template}@{run_id}.service",
        command_sha256,
    )


def dispatch_sdxl_probe(staged: StagedSdxlProbe) -> None:
    """Start only the fixed isolated unit after the Orchestrator handoff is complete."""
    _dispatch(
        staged,
        unit_template="eom-image-sdxl-lineart-probe",
        parent=Path("/srv/eom/image-workspaces"),
        prefix="imgsdxlproberun_",
    )


def dispatch_sdxl_micro_probe(staged: StagedSdxlProbe) -> None:
    _dispatch(
        staged,
        unit_template="eom-image-sdxl-lora-micro-probe",
        parent=Path("/srv/eom/image-training-workspaces"),
        prefix="imgsdxlmicrotrainrun_",
    )


def _dispatch(staged: StagedSdxlProbe, *, unit_template: str, parent: Path, prefix: str) -> None:
    expected = f"{unit_template}@{staged.workspace.name}.service"
    if (
        os.geteuid() != 0
        or staged.systemd_unit != expected
        or staged.workspace.parent != parent
        or re.fullmatch(prefix + r"[0-9a-f]{32}", staged.workspace.name) is None
        or re.fullmatch(r"sha256:[0-9a-f]{64}", staged.command_sha256) is None
    ):
        raise SdxlProbeHandoffError("SDXL_PROBE_DISPATCH_INVALID")
    try:
        subprocess.run(
            ["systemctl", "start", "--no-block", staged.systemd_unit],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        # An ambiguous start is queried by this same unit identity, never resubmitted as a new run.
        raise SdxlProbeHandoffError("SDXL_PROBE_DISPATCH_UNCONFIRMED") from exc
