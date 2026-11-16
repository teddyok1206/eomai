"""One claimed export attempt: stage, fixed isolated run, validate, return local receipts.

Catalog owns authorization and publication. This adapter owns neither a queue nor
a database and never retries an uncertain process or changes historical results.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from eom_kakao_archive_contracts import (
    LocalMember,
    RenderCommand,
    RenderManifest,
    RenderResult,
    canonical_bytes,
    sha256,
)
from eom_kakao_archive_contracts.layout import RenderLayoutReceipt, check_layout_receipt
from eom_kakao_archive_contracts.render import render_input_members
from eom_kakao_archive_contracts.validation import validate_contract

from .kakao_pdf_files import (
    KakaoPdfExecutionError,
    create_directory,
    local_directory,
    read_local,
    read_pinned,
    require_owner_directory,
    write_local,
)


class KakaoPdfLauncher(Protocol):
    def run(self, command: RenderCommand, workspace: Path) -> None:
        """Return only after original worker has stopped; timeout is uncertain, never success."""


class KakaoPdfStoppedCheck(Protocol):
    def __call__(self, command: RenderCommand, workspace: Path) -> None:
        """Owner must prove the exact original attempt's process/cgroup is stopped."""


@dataclass(frozen=True, slots=True)
class AcceptedKakaoPdf:
    result: RenderResult
    layout: RenderLayoutReceipt | None
    files: tuple[LocalMember, ...]
    # Core-only staging location, not serializable as a public response or log value.
    staging_root: Path | None = field(repr=False)


@dataclass(frozen=True, slots=True)
class KakaoPdfExecutor:
    workspace_root: Path = field(repr=False)
    worker_uid: int
    shared_gid: int
    launcher: KakaoPdfLauncher = field(repr=False)
    assert_current: Callable[[RenderCommand], None] = field(repr=False)

    def execute(self, command: RenderCommand, *, source_root: Path) -> AcceptedKakaoPdf:
        """The source root is owner-created materialization, never a browser-supplied path."""
        try:
            return self._execute(command, source_root=source_root)
        except KakaoPdfExecutionError:
            raise
        except (OSError, ValueError, RuntimeError):
            # Decoder and filesystem exceptions may contain personal text or local paths.
            raise KakaoPdfExecutionError("KAKAO_PDF_EXECUTION_INVALID") from None

    def recover_finished(
        self, command: RenderCommand, *, assert_stopped: KakaoPdfStoppedCheck
    ) -> AcceptedKakaoPdf:
        """Revalidate stopped output only. This never dispatches or overwrites staged files."""
        try:
            validate_contract("command", command.model_dump(mode="json"))
            self.assert_current(command)
            require_owner_directory(self.workspace_root, os.geteuid(), self.shared_gid)
            workspace = self.workspace_root / command.execution.attempt_id
            assert_stopped(command, workspace)
            inputs = workspace / "input"
            raw_request = read_local(
                inputs, "request.json", limit=32768, uid=os.geteuid(), gid=self.shared_gid
            )
            request = json.loads(raw_request)
            validate_contract("command", request)
            if RenderCommand.model_validate(request) != command:
                raise KakaoPdfExecutionError("KAKAO_PDF_RECOVERY_PINS_MISMATCH")
            raw_manifest = read_pinned(
                inputs, command.manifest, uid=os.geteuid(), gid=self.shared_gid
            )
            value = json.loads(raw_manifest)
            validate_contract("manifest", value)
            manifest = RenderManifest.model_validate(value)
            for member in render_input_members(command, manifest):
                if member != command.manifest:
                    read_pinned(inputs, member, uid=os.geteuid(), gid=self.shared_gid)
            self.assert_current(command)
            return self._accept(command, manifest, workspace, recovery=True)
        except KakaoPdfExecutionError:
            raise
        except (OSError, ValueError, RuntimeError):
            raise KakaoPdfExecutionError("KAKAO_PDF_RECOVERY_INVALID") from None

    def _execute(self, command: RenderCommand, *, source_root: Path) -> AcceptedKakaoPdf:
        validate_contract("command", command.model_dump(mode="json"))
        self.assert_current(command)
        owner_uid = os.geteuid()
        require_owner_directory(self.workspace_root, owner_uid, self.shared_gid)
        if source_root.is_relative_to(self.workspace_root) or self.workspace_root.is_relative_to(
            source_root
        ):
            raise KakaoPdfExecutionError("KAKAO_PDF_SOURCE_WORKSPACE_OVERLAP")
        raw_manifest = read_pinned(source_root, command.manifest, uid=owner_uid)
        decoded = json.loads(raw_manifest)
        validate_contract("manifest", decoded)
        manifest = RenderManifest.model_validate(decoded)
        members = render_input_members(command, manifest)
        if any(
            member.relative_path == "request.json"
            or member.relative_path.startswith("request.json/")
            for member in members
        ):
            raise KakaoPdfExecutionError("KAKAO_PDF_MEMBER_RESERVED")
        # Exclusive directory allocation is the dispatch fence against local replay.
        try:
            workspace = create_directory(
                self.workspace_root, command.execution.attempt_id, gid=self.shared_gid, mode=0o750
            )
        except FileExistsError:
            raise KakaoPdfExecutionError("KAKAO_PDF_ATTEMPT_ALREADY_STAGED") from None
        inputs = create_directory(workspace, "input", gid=self.shared_gid, mode=0o750)
        create_directory(workspace, "output", gid=self.shared_gid, mode=0o770)
        for member in members:
            raw = (
                raw_manifest
                if member == command.manifest
                else read_pinned(source_root, member, uid=owner_uid)
            )
            write_local(inputs, member.relative_path, raw, gid=self.shared_gid)
        write_local(
            inputs,
            "request.json",
            canonical_bytes(command.model_dump(mode="json")),
            gid=self.shared_gid,
        )
        self.assert_current(command)
        self.launcher.run(command, workspace)
        self.assert_current(command)
        return self._accept(command, manifest, workspace, recovery=False)

    def _accept(
        self, command: RenderCommand, manifest: RenderManifest, workspace: Path, *, recovery: bool
    ) -> AcceptedKakaoPdf:
        outputs = workspace / "output"
        raw_result = read_local(
            outputs, "result.json", limit=128 * 1024, uid=self.worker_uid, gid=self.shared_gid
        )
        value = json.loads(raw_result)
        validate_contract("result", value)
        result = RenderResult.model_validate(value)
        if (
            result.execution != command.execution
            or result.export_id != command.export_id
            or result.command_sha256 != sha256(canonical_bytes(command.model_dump(mode="json")))
            or result.manifest_sha256 != command.manifest.sha256
        ):
            raise KakaoPdfExecutionError("KAKAO_PDF_RESULT_PINS_MISMATCH")
        if result.question_revision_id is not None and result.question_revision_id not in {
            question.question_revision_id for question in manifest.questions
        }:
            raise KakaoPdfExecutionError("KAKAO_PDF_RESULT_QUESTION_MISMATCH")
        if result.status != "COMPLETED":
            return AcceptedKakaoPdf(result, None, (), None)
        if (
            result.page_count != len(manifest.questions)
            or sum(m.size_bytes for m in result.outputs) > 256 * 1024 * 1024
        ):
            raise KakaoPdfExecutionError("KAKAO_PDF_RESULT_SIZE_INVALID")
        with local_directory(outputs) as directory:
            if set(os.listdir(directory)) != {
                "result.json",
                *(member.relative_path for member in result.outputs),
            }:
                raise KakaoPdfExecutionError("KAKAO_PDF_RESULT_MEMBERS_INVALID")
        by_name = {member.relative_path: member for member in result.outputs}
        raw_layout = read_pinned(
            outputs, by_name["layout.json"], uid=self.worker_uid, gid=self.shared_gid
        )
        layout_value = json.loads(raw_layout)
        validate_contract("layout", layout_value)
        layout = RenderLayoutReceipt.model_validate(layout_value)
        check_layout_receipt(command, manifest, layout)
        try:
            accepted = create_directory(workspace, "accepted", gid=self.shared_gid, mode=0o700)
        except FileExistsError:
            if not recovery:
                raise KakaoPdfExecutionError("KAKAO_PDF_ACCEPTANCE_ALREADY_STAGED") from None
            accepted = workspace / "accepted"
            require_owner_directory(accepted, os.geteuid(), self.shared_gid)
        with local_directory(accepted) as directory:
            existing = set(os.listdir(directory))
        if not existing <= by_name.keys():
            raise KakaoPdfExecutionError("KAKAO_PDF_RECOVERY_MEMBERS_INVALID")
        # Binary decode already happened in the isolated worker. Core checks identity/hash
        # while copying, not a second untrusted PDF parser in the owner process.
        for member in result.outputs:
            raw = (
                raw_layout
                if member.relative_path == "layout.json"
                else read_pinned(outputs, member, uid=self.worker_uid, gid=self.shared_gid)
            )
            if member.media_type == "application/pdf" and not raw.startswith(b"%PDF-"):
                raise KakaoPdfExecutionError("KAKAO_PDF_RESULT_MEDIA_INVALID")
            if member.media_type == "image/png" and not raw.startswith(b"\x89PNG\r\n\x1a\n"):
                raise KakaoPdfExecutionError("KAKAO_PDF_RESULT_MEDIA_INVALID")
            if member.relative_path in existing:
                read_pinned(accepted, member, uid=os.geteuid(), gid=self.shared_gid)
            else:
                write_local(accepted, member.relative_path, raw, gid=self.shared_gid)
        self.assert_current(command)
        return AcceptedKakaoPdf(result, layout, result.outputs, accepted)
