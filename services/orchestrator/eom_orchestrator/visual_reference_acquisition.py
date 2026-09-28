"""Orchestrator-owned publication around the isolated visual-reference acquirer."""

from __future__ import annotations

import grp
import hashlib
import json
import os
import pwd
import re
import stat
import struct
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from eom_image_contracts import (
    LocalImageVisualReferenceAcquisitionCommand,
    LocalImageVisualReferenceAcquisitionResult,
    LocalImageVisualReferenceDiscoveryCommand,
    LocalImageVisualReferenceDiscoveryResult,
    LocalImageVisualReferenceIntent,
    LocalImageVisualReferencePointer,
    VisualReferenceBundleManifestPointer,
    VisualReferenceIntentArtifactPointer,
    VisualReferencePngArtifactPointer,
    content_json_bytes,
    content_sha256,
    validate_contract,
    validate_visual_reference_acquisition,
    validate_visual_reference_discovery,
)

from eom_orchestrator.file_set_control_artifacts import (
    ControlFileSetMember,
    PublishedControlFileSet,
)
from eom_orchestrator.settings import Settings

_SOURCE_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_SYSTEMCTL = Path("/usr/bin/systemctl")
_SYSTEMCTL_ENV = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin"}
_BUNDLE_MEMBER = "manifests/visual-reference-bundle.json"
_REFERENCE_MEMBER = "references/primary.png"
_RESULT_MEMBER = "result.json"
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class VisualReferenceCoordinatorError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class FileSetPublisher(Protocol):
    def publish(
        self,
        *,
        members: tuple[ControlFileSetMember, ...],
        primary_file: str,
        artifact_type: str,
        manifest_version: str,
        idempotency_key: str,
        source_commit: str,
        created_at: datetime,
    ) -> PublishedControlFileSet: ...


@dataclass(frozen=True, slots=True)
class PublishedVisualReference:
    intent_artifact: PublishedControlFileSet
    bundle_artifact: PublishedControlFileSet
    command: LocalImageVisualReferenceAcquisitionCommand
    acquisition_result: LocalImageVisualReferenceAcquisitionResult
    pointer: LocalImageVisualReferencePointer
    unit_name: str


@dataclass(frozen=True, slots=True)
class DiscoveredVisualReference:
    discovery_command: LocalImageVisualReferenceDiscoveryCommand
    discovery_result: LocalImageVisualReferenceDiscoveryResult
    discovery_unit_name: str
    intent: LocalImageVisualReferenceIntent
    published: PublishedVisualReference


class VisualReferenceAcquisitionCoordinator:
    """Publish one intent, invoke one fixed acquirer, and publish verified outputs."""

    def __init__(
        self,
        *,
        publisher: FileSetPublisher,
        settings: Settings,
        unit_runner: Callable[[str, int], None] | None = None,
        provider_uid: int | None = None,
        provider_gid: int | None = None,
        workspace_root_uid: int = 0,
    ) -> None:
        self.publisher = publisher
        self.settings = settings
        self.unit_runner = unit_runner or _run_fixed_unit
        self.provider_uid = (
            pwd.getpwnam("eom-image-reference").pw_uid if provider_uid is None else provider_uid
        )
        self.provider_gid = (
            grp.getgrnam(settings.image_reference_provider_group).gr_gid
            if provider_gid is None
            else provider_gid
        )
        self.workspace_root_uid = workspace_root_uid

    def discover_and_acquire(
        self,
        *,
        workflow_id: str,
        image_step_run_id: str,
        image_job_id: str,
        visual_ordinal: int,
        drawing_sha256: str,
        subject: str,
        source_commit: str,
        observed_at: datetime,
        timeout_seconds: int = 120,
    ) -> DiscoveredVisualReference:
        """Discover candidate identities, then acquire and publish the pinned primary reference."""

        try:
            command = _build_discovery_command(
                workflow_id=workflow_id,
                image_step_run_id=image_step_run_id,
                image_job_id=image_job_id,
                visual_ordinal=visual_ordinal,
                drawing_sha256=drawing_sha256,
                subject=subject,
                observed_at=observed_at,
                timeout_seconds=timeout_seconds,
            )
        except Exception as exc:
            raise VisualReferenceCoordinatorError("VISUAL_REFERENCE_INPUT_INVALID") from exc
        workspace = self._prepare_workspace(command.command_id)
        self._stage_input(
            workspace,
            workspace / "command.json",
            content_json_bytes(command.model_dump(mode="json")),
        )
        unit_name = f"eom-image-reference-discoverer@{command.command_id}.service"
        result_path = workspace / "output" / _RESULT_MEMBER
        if not result_path.exists() and not result_path.is_symlink():
            self.unit_runner(unit_name, timeout_seconds)
        result = self._validate_discovery_output(
            workspace=workspace,
            command=command,
        )
        intent = _build_intent(command=command, result=result)
        published = self.acquire(
            intent=intent,
            source_commit=source_commit,
            observed_at=observed_at,
            timeout_seconds=timeout_seconds,
        )
        return DiscoveredVisualReference(
            discovery_command=command,
            discovery_result=result,
            discovery_unit_name=unit_name,
            intent=intent,
            published=published,
        )

    def acquire(
        self,
        *,
        intent: LocalImageVisualReferenceIntent,
        source_commit: str,
        observed_at: datetime,
        timeout_seconds: int = 120,
    ) -> PublishedVisualReference:
        if (
            _SOURCE_COMMIT.fullmatch(source_commit) is None
            or observed_at.tzinfo is None
            or observed_at.utcoffset() != UTC.utcoffset(observed_at)
            or not 30 <= timeout_seconds <= 180
        ):
            raise VisualReferenceCoordinatorError("VISUAL_REFERENCE_INPUT_INVALID")
        intent_value = intent.model_dump(mode="json")
        validate_contract("visual-reference-intent", intent_value)
        intent_bytes = content_json_bytes(intent_value)
        intent_source = self._stage_intent(intent, intent_bytes)
        intent_artifact = self.publisher.publish(
            members=(
                ControlFileSetMember(
                    file_name="manifests/visual-reference-intent.json",
                    source=intent_source,
                    sha256=_sha256(intent_bytes),
                    bytes=len(intent_bytes),
                    schema_ref=(
                        "eom://schemas/image-provider/local-image-visual-reference-intent/1.0"
                    ),
                    media_type="application/json",
                ),
            ),
            primary_file="manifests/visual-reference-intent.json",
            artifact_type="control_local_image_visual_reference_intent",
            manifest_version="local-image-visual-reference-intent-file-set/1.0",
            idempotency_key=f"visual-reference-intent:{intent.intent_sha256}",
            source_commit=source_commit,
            created_at=observed_at,
        )
        intent_pointer = VisualReferenceIntentArtifactPointer(
            artifact_id=intent_artifact.artifact_id,
            artifact_revision_id=intent_artifact.artifact_revision_id,
            sha256=_sha256(intent_bytes),
            size_bytes=len(intent_bytes),
        )
        command = _build_command(
            intent=intent_pointer,
            observed_at=observed_at,
            timeout_seconds=timeout_seconds,
        )
        workspace = self._prepare_workspace(command.command_id)
        self._stage_input(
            workspace,
            workspace / "command.json",
            content_json_bytes(command.model_dump(mode="json")),
        )
        self._stage_input(workspace, workspace / command.intent_member_path, intent_bytes)
        unit_name = f"eom-image-reference-acquirer@{command.command_id}.service"
        result_path = workspace / "output" / _RESULT_MEMBER
        if not result_path.exists() and not result_path.is_symlink():
            self.unit_runner(unit_name, timeout_seconds)
        result, bundle_path, reference_path = self._validate_output(
            workspace=workspace,
            command=command,
            intent=intent,
        )
        assert result.bundle is not None
        bundle_bytes = _read_exact_output(
            bundle_path,
            maximum_bytes=16 * 1024 * 1024,
            expected_uid=self.provider_uid,
            expected_gid=self.provider_gid,
        )
        reference_bytes = _read_exact_output(
            reference_path,
            maximum_bytes=8 * 1024 * 1024,
            expected_uid=self.provider_uid,
            expected_gid=self.provider_gid,
        )
        bundle_artifact = self.publisher.publish(
            members=(
                ControlFileSetMember(
                    file_name=_BUNDLE_MEMBER,
                    source=bundle_path,
                    sha256=_sha256(bundle_bytes),
                    bytes=len(bundle_bytes),
                    schema_ref=(
                        "eom://schemas/image-provider/local-image-visual-reference-bundle/1.0"
                    ),
                    media_type="application/json",
                ),
                ControlFileSetMember(
                    file_name=_REFERENCE_MEMBER,
                    source=reference_path,
                    sha256=_sha256(reference_bytes),
                    bytes=len(reference_bytes),
                    schema_ref=("eom://schemas/image-provider/normalized-visual-reference/1.0"),
                    media_type="image/png",
                ),
            ),
            primary_file=_BUNDLE_MEMBER,
            artifact_type="control_local_image_visual_reference_bundle",
            manifest_version="local-image-visual-reference-file-set/1.0",
            idempotency_key=f"visual-reference-bundle:{result.bundle.bundle_sha256}",
            source_commit=source_commit,
            created_at=observed_at,
        )
        pointer = LocalImageVisualReferencePointer(
            bundle_id=result.bundle.bundle_id,
            bundle_revision_id=result.bundle.bundle_revision_id,
            bundle_manifest=VisualReferenceBundleManifestPointer(
                artifact_id=bundle_artifact.artifact_id,
                artifact_revision_id=bundle_artifact.artifact_revision_id,
                sha256=_sha256(bundle_bytes),
                size_bytes=len(bundle_bytes),
            ),
            primary_reference_id=result.bundle.primary_reference_id,
            reference_member=VisualReferencePngArtifactPointer(
                artifact_id=bundle_artifact.artifact_id,
                artifact_revision_id=bundle_artifact.artifact_revision_id,
                sha256=_sha256(reference_bytes),
                size_bytes=len(reference_bytes),
            ),
        )
        return PublishedVisualReference(
            intent_artifact=intent_artifact,
            bundle_artifact=bundle_artifact,
            command=command,
            acquisition_result=result,
            pointer=pointer,
            unit_name=unit_name,
        )

    def _stage_intent(
        self,
        intent: LocalImageVisualReferenceIntent,
        payload: bytes,
    ) -> Path:
        root = self.settings.staging_root / "visual-reference-intents"
        if not root.exists() and not root.is_symlink():
            root.mkdir(mode=0o700, parents=True)
        metadata = root.lstat()
        if (
            root.is_symlink()
            or not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) != 0o700
        ):
            raise VisualReferenceCoordinatorError("VISUAL_REFERENCE_HANDOFF_INVALID")
        target = root / f"{intent.intent_id}.json"
        _write_or_verify(target, payload, mode=0o600, gid=None)
        return target

    def _prepare_workspace(self, command_id: str) -> Path:
        root = self.settings.image_reference_workspace_root
        metadata = root.lstat()
        if (
            root.is_symlink()
            or not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != self.workspace_root_uid
            or metadata.st_gid != self.provider_gid
            or stat.S_IMODE(metadata.st_mode) != 0o3770
            or self.provider_gid not in {os.getegid(), *os.getgroups()}
        ):
            raise VisualReferenceCoordinatorError("VISUAL_REFERENCE_ROUTE_UNDEPLOYED")
        workspace = root / command_id
        if not workspace.exists() and not workspace.is_symlink():
            workspace.mkdir(mode=0o700)
            descriptor = os.open(
                workspace,
                os.O_RDONLY
                | os.O_CLOEXEC
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0),
            )
            try:
                os.fchown(descriptor, -1, self.provider_gid)
                os.fchmod(descriptor, 0o1730)
            finally:
                os.close(descriptor)
        current = workspace.lstat()
        if (
            workspace.is_symlink()
            or not stat.S_ISDIR(current.st_mode)
            or current.st_uid != os.geteuid()
            or current.st_gid != self.provider_gid
            or stat.S_IMODE(current.st_mode) != 0o1730
        ):
            raise VisualReferenceCoordinatorError("VISUAL_REFERENCE_HANDOFF_INVALID")
        return workspace

    def _stage_input(self, workspace: Path, path: Path, payload: bytes) -> None:
        if path.parent != workspace:
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            descriptor = os.open(
                path.parent,
                os.O_RDONLY
                | os.O_CLOEXEC
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0),
            )
            try:
                os.fchown(descriptor, -1, self.provider_gid)
                os.fchmod(descriptor, 0o750)
            finally:
                os.close(descriptor)
        _write_or_verify(path, payload, mode=0o440, gid=self.provider_gid)

    def _validate_output(
        self,
        *,
        workspace: Path,
        command: LocalImageVisualReferenceAcquisitionCommand,
        intent: LocalImageVisualReferenceIntent,
    ) -> tuple[LocalImageVisualReferenceAcquisitionResult, Path, Path]:
        output = workspace / "output"
        _require_output_directory(
            output,
            expected_uid=self.provider_uid,
            expected_gid=self.provider_gid,
        )
        result_path = output / _RESULT_MEMBER
        result_bytes = _read_exact_output(
            result_path,
            maximum_bytes=512 * 1024,
            expected_uid=self.provider_uid,
            expected_gid=self.provider_gid,
        )
        try:
            value = json.loads(result_bytes)
            if not isinstance(value, dict) or content_json_bytes(value) != result_bytes:
                raise ValueError("result is not canonical JSON")
            validate_contract("visual-reference-acquisition-result", value)
            result = LocalImageVisualReferenceAcquisitionResult.model_validate(value)
            validate_visual_reference_acquisition(command, intent, result)
        except Exception as exc:
            raise VisualReferenceCoordinatorError("VISUAL_REFERENCE_OUTPUT_INVALID") from exc
        if result.status != "SUCCEEDED" or result.bundle is None:
            raise VisualReferenceCoordinatorError(
                result.error_code or "VISUAL_REFERENCE_OUTPUT_INVALID"
            )
        for child in (output / "manifests", output / "references"):
            _require_output_directory(
                child,
                expected_uid=self.provider_uid,
                expected_gid=self.provider_gid,
            )
        bundle_path = output / _BUNDLE_MEMBER
        reference_path = output / _REFERENCE_MEMBER
        bundle_bytes = _read_exact_output(
            bundle_path,
            maximum_bytes=16 * 1024 * 1024,
            expected_uid=self.provider_uid,
            expected_gid=self.provider_gid,
        )
        reference_bytes = _read_exact_output(
            reference_path,
            maximum_bytes=8 * 1024 * 1024,
            expected_uid=self.provider_uid,
            expected_gid=self.provider_gid,
        )
        if (
            bundle_bytes != content_json_bytes(result.bundle.model_dump(mode="json"))
            or _sha256(reference_bytes) != result.bundle.normalized_member.sha256
            or len(reference_bytes) != result.bundle.normalized_member.size_bytes
        ):
            raise VisualReferenceCoordinatorError("VISUAL_REFERENCE_OUTPUT_INVALID")
        _validate_reference_png(reference_bytes)
        return result, bundle_path, reference_path

    def _validate_discovery_output(
        self,
        *,
        workspace: Path,
        command: LocalImageVisualReferenceDiscoveryCommand,
    ) -> LocalImageVisualReferenceDiscoveryResult:
        output = workspace / "output"
        _require_output_directory(
            output,
            expected_uid=self.provider_uid,
            expected_gid=self.provider_gid,
        )
        result_bytes = _read_exact_output(
            output / _RESULT_MEMBER,
            maximum_bytes=512 * 1024,
            expected_uid=self.provider_uid,
            expected_gid=self.provider_gid,
        )
        try:
            value = json.loads(result_bytes)
            if not isinstance(value, dict) or content_json_bytes(value) != result_bytes:
                raise ValueError("discovery result is not canonical JSON")
            validate_contract("visual-reference-discovery-result", value)
            result = LocalImageVisualReferenceDiscoveryResult.model_validate(value)
            validate_visual_reference_discovery(command, result)
        except Exception as exc:
            raise VisualReferenceCoordinatorError("VISUAL_REFERENCE_DISCOVERY_INVALID") from exc
        if result.status != "SUCCEEDED":
            raise VisualReferenceCoordinatorError(
                result.error_code or "VISUAL_REFERENCE_DISCOVERY_INVALID"
            )
        return result


def _build_command(
    *,
    intent: VisualReferenceIntentArtifactPointer,
    observed_at: datetime,
    timeout_seconds: int,
) -> LocalImageVisualReferenceAcquisitionCommand:
    identity = content_sha256(
        {
            "intent": intent.model_dump(mode="json"),
            "observed_at": observed_at.isoformat().replace("+00:00", "Z"),
            "timeout_seconds": timeout_seconds,
            "max_original_bytes": 16_777_216,
        }
    ).removeprefix("sha256:")
    body = {
        "schema_version": "local-image-visual-reference-acquisition-command/1.0",
        "command_id": "imgrefcmd_" + identity[:32],
        "attempt_id": "imgrefattempt_" + identity[32:],
        "intent": intent.model_dump(mode="json"),
        "intent_member_path": "input/visual-reference-intent.json",
        "observed_at": observed_at.isoformat().replace("+00:00", "Z"),
        "max_original_bytes": 16_777_216,
        "timeout_seconds": timeout_seconds,
    }
    command = LocalImageVisualReferenceAcquisitionCommand.model_validate(
        {**body, "command_sha256": content_sha256(body)}
    )
    validate_contract("visual-reference-acquisition-command", command.model_dump(mode="json"))
    return command


def _build_discovery_command(
    *,
    workflow_id: str,
    image_step_run_id: str,
    image_job_id: str,
    visual_ordinal: int,
    drawing_sha256: str,
    subject: str,
    observed_at: datetime,
    timeout_seconds: int,
) -> LocalImageVisualReferenceDiscoveryCommand:
    query_terms = _discovery_query_terms(subject)
    identity_body = {
        "schema_version": "local-image-visual-reference-discovery-command/1.0",
        "workflow_id": workflow_id,
        "image_step_run_id": image_step_run_id,
        "image_job_id": image_job_id,
        "visual_ordinal": visual_ordinal,
        "drawing_sha256": drawing_sha256,
        "subject": subject,
        "query_terms": list(query_terms),
        "candidate_limit": 5,
        "observed_at": observed_at.isoformat().replace("+00:00", "Z"),
        "timeout_seconds": timeout_seconds,
    }
    identity = content_sha256(identity_body).removeprefix("sha256:")
    body = {**identity_body, "command_id": "imgrefdiscover_" + identity[:32]}
    command = LocalImageVisualReferenceDiscoveryCommand.model_validate(
        {**body, "command_sha256": content_sha256(body)}
    )
    validate_contract("visual-reference-discovery-command", command.model_dump(mode="json"))
    return command


def _discovery_query_terms(subject: str) -> tuple[str, ...]:
    """Derive one bounded morphology query from the validated English subject.

    The subject remains the immutable semantic identity. Commons search performs better when
    presentation-only clauses such as isolation, direction, and background are removed, while an
    explicit viewpoint remains part of the morphology query.
    """

    normalized = re.sub(r"[^A-Za-z0-9 .()/_-]+", " ", subject)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    lowered = normalized.casefold()
    cut_positions = [
        index
        for marker in (
            " in ",
            " with ",
            " isolated ",
            " on white",
            " facing ",
            " viewed ",
            " showing ",
            " after ",
            " before ",
        )
        if (index := lowered.find(marker)) > 0
    ]
    core = normalized[: min(cut_positions)] if cut_positions else normalized
    core = re.sub(
        r"^(?:a|an|the|one|two|three|four|five|six|seven|eight|nine|ten|[0-9]+)\s+",
        "",
        core,
        flags=re.IGNORECASE,
    ).strip()
    viewpoint = next(
        (
            value
            for value in (
                "side view",
                "front view",
                "rear view",
                "top view",
                "cross-section",
                "cross section",
            )
            if value in lowered
        ),
        None,
    )
    if viewpoint is not None and viewpoint not in core.casefold():
        core = f"{core} {viewpoint}"
    query = core[:80].rstrip(" ._-/")
    if not query:
        query = normalized[:80].rstrip(" ._-/")
    return (query,)


def _build_intent(
    *,
    command: LocalImageVisualReferenceDiscoveryCommand,
    result: LocalImageVisualReferenceDiscoveryResult,
) -> LocalImageVisualReferenceIntent:
    if result.status != "SUCCEEDED" or not result.candidates:
        raise VisualReferenceCoordinatorError("VISUAL_REFERENCE_DISCOVERY_INVALID")
    identity_body = {
        "workflow_id": command.workflow_id,
        "image_step_run_id": command.image_step_run_id,
        "image_job_id": command.image_job_id,
        "visual_ordinal": command.visual_ordinal,
        "drawing_sha256": command.drawing_sha256,
        "subject": command.subject,
        "query_terms": list(command.query_terms),
        "candidates": [candidate.model_dump(mode="json") for candidate in result.candidates],
        "primary_candidate_page_id": result.candidates[0].page_id,
    }
    identity = content_sha256(identity_body).removeprefix("sha256:")
    body = {
        "schema_version": "local-image-visual-reference-intent/1.0",
        "intent_id": "imgrefintent_" + identity[:32],
        **identity_body,
    }
    intent = LocalImageVisualReferenceIntent.model_validate(
        {**body, "intent_sha256": content_sha256(body)}
    )
    validate_contract("visual-reference-intent", intent.model_dump(mode="json"))
    return intent


def _write_or_verify(path: Path, payload: bytes, *, mode: int, gid: int | None) -> None:
    if path.exists() or path.is_symlink():
        existing = _read_staged(path, maximum_bytes=max(1, len(payload)), mode=mode, gid=gid)
        if existing != payload:
            raise VisualReferenceCoordinatorError("VISUAL_REFERENCE_HANDOFF_INVALID")
        return
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        mode,
    )
    try:
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("short visual-reference handoff write")
            view = view[written:]
        os.fsync(descriptor)
        if gid is not None:
            os.fchown(descriptor, -1, gid)
        os.fchmod(descriptor, mode)
    except OSError as exc:
        raise VisualReferenceCoordinatorError("VISUAL_REFERENCE_HANDOFF_INVALID") from exc
    finally:
        os.close(descriptor)


def _read_staged(path: Path, *, maximum_bytes: int, mode: int, gid: int | None) -> bytes:
    expected_uid = os.geteuid()
    return _read_exact_file(
        path,
        maximum_bytes=maximum_bytes,
        expected_mode=mode,
        expected_uid=expected_uid,
        expected_gid=gid,
        error_code="VISUAL_REFERENCE_HANDOFF_INVALID",
    )


def _read_exact_output(
    path: Path,
    *,
    maximum_bytes: int,
    expected_uid: int,
    expected_gid: int,
) -> bytes:
    return _read_exact_file(
        path,
        maximum_bytes=maximum_bytes,
        expected_mode=0o640,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
        error_code="VISUAL_REFERENCE_OUTPUT_INVALID",
    )


def _require_output_directory(path: Path, *, expected_uid: int, expected_gid: int) -> None:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise VisualReferenceCoordinatorError("VISUAL_REFERENCE_OUTPUT_INVALID") from exc
    if (
        path.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != expected_uid
        or metadata.st_gid != expected_gid
        or stat.S_IMODE(metadata.st_mode) != 0o750
    ):
        raise VisualReferenceCoordinatorError("VISUAL_REFERENCE_OUTPUT_INVALID")


def _read_exact_file(
    path: Path,
    *,
    maximum_bytes: int,
    expected_mode: int,
    expected_uid: int,
    expected_gid: int | None,
    error_code: str,
) -> bytes:
    descriptor = -1
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        )
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or not 1 <= opened.st_size <= maximum_bytes
            or stat.S_IMODE(opened.st_mode) != expected_mode
            or opened.st_uid != expected_uid
            or (expected_gid is not None and opened.st_gid != expected_gid)
        ):
            raise OSError("visual-reference file metadata differs")
        payload = bytearray()
        while len(payload) <= maximum_bytes:
            chunk = os.read(descriptor, min(64 * 1024, maximum_bytes + 1 - len(payload)))
            if not chunk:
                break
            payload.extend(chunk)
        closed = os.fstat(descriptor)
        if len(payload) != opened.st_size or (closed.st_dev, closed.st_ino, closed.st_size) != (
            opened.st_dev,
            opened.st_ino,
            opened.st_size,
        ):
            raise OSError("visual-reference file changed while reading")
        return bytes(payload)
    except OSError as exc:
        raise VisualReferenceCoordinatorError(error_code) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _validate_reference_png(payload: bytes) -> None:
    if (
        not 32 <= len(payload) <= 8 * 1024 * 1024
        or payload[:8] != _PNG_SIGNATURE
        or payload[12:16] != b"IHDR"
        or struct.unpack(">II", payload[16:24]) != (800, 504)
        or payload[24:26] != b"\x08\x02"
        or payload[-12:-8] != b"\x00\x00\x00\x00"
        or payload[-8:-4] != b"IEND"
    ):
        raise VisualReferenceCoordinatorError("VISUAL_REFERENCE_OUTPUT_INVALID")


def _sha256(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _run_fixed_unit(unit_name: str, timeout_seconds: int) -> None:
    try:
        completed = subprocess.run(
            [str(_SYSTEMCTL), "--no-ask-password", "--wait", "start", unit_name],
            capture_output=True,
            timeout=timeout_seconds + 30,
            check=False,
            env=_SYSTEMCTL_ENV,
        )
    except subprocess.TimeoutExpired as exc:
        raise VisualReferenceCoordinatorError("VISUAL_REFERENCE_SOURCE_UNAVAILABLE") from exc
    if completed.returncode != 0:
        raise VisualReferenceCoordinatorError("VISUAL_REFERENCE_SOURCE_UNAVAILABLE")
