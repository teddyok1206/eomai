"""One claimed export, using the existing materializer, isolated executor and publisher."""

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from eom_catalog_contracts.kakao_export_store import KakaoExport
from eom_kakao_archive_contracts import LocalMember, RenderCommand, RenderExecution
from eom_operator_identity import ActorContext
from eom_orchestrator.kakao_pdf_execution import (
    AcceptedKakaoPdf,
    KakaoPdfExecutor,
    KakaoPdfLauncher,
    KakaoPdfStoppedCheck,
)
from eom_orchestrator.kakao_pdf_files import create_directory, read_pinned, require_owner_directory

from .artifacts import CatalogArtifactService
from .kakao_export_service import KakaoExportService
from .kakao_pdf_inputs import prepare_kakao_pdf_inputs
from .kakao_pdf_publication import publish_kakao_pdf


@dataclass(frozen=True, slots=True)
class KakaoPdfDelivery:
    exports: KakaoExportService = field(repr=False)
    artifacts: CatalogArtifactService = field(repr=False)
    input_root: Path = field(repr=False)
    workspace_root: Path = field(repr=False)
    font_source: Path = field(repr=False)
    font: LocalMember
    worker_uid: int
    shared_gid: int
    launcher: KakaoPdfLauncher = field(repr=False)
    assert_stopped: KakaoPdfStoppedCheck = field(repr=False)

    def run(self, actor: ActorContext, binding: str, export_id: str) -> KakaoExport:
        claim = self.exports.claim_export(actor, binding, export_id)
        if not claim.acquired and claim.export.state != "RUNNING":
            return claim.export
        _, packet, selected = self.exports.resolve_inputs(actor, binding, export_id)

        def authorize_claim() -> None:
            self.exports.check_claim(actor, binding, export_id, claim.execution, packet, selected)

        def authorize(command: RenderCommand) -> None:
            self.exports.check_attempt(actor, binding, export_id, command, packet, selected)

        executor = KakaoPdfExecutor(
            self.workspace_root, self.worker_uid, self.shared_gid, self.launcher, authorize
        )
        if not claim.acquired:
            command = self.exports.read_command(actor, binding, export_id, claim.execution)
            accepted = executor.recover_finished(command, assert_stopped=self.assert_stopped)
            source_root = self.workspace_root / claim.execution.attempt_id / "input"
        else:
            command = None
            try:
                authorize_claim()
                require_owner_directory(self.input_root, os.geteuid(), os.getgid())
                source_root = create_directory(
                    self.input_root, claim.execution.attempt_id, gid=os.getgid(), mode=0o700
                )
                prepared = prepare_kakao_pdf_inputs(
                    self.artifacts,
                    packet=packet,
                    selection=selected,
                    student_id=claim.export.student_id,
                    source_root=source_root,
                    font_source=self.font_source,
                    font=self.font,
                    authorize=authorize_claim,
                )
                command = RenderCommand(
                    schema_version="kakao-question-render/1.0",
                    execution=claim.execution,
                    export_id=export_id,
                    source_binding_id=binding,
                    packet_revision_id=claim.export.packet_revision_id,
                    student_id=claim.export.student_id,
                    subset_sha256=prepared.manifest.subset_sha256,
                    mode=claim.export.mode,
                    renderer_release_sha256=claim.export.profile.renderer_release_sha256,
                    layout_policy=claim.export.profile.layout_policy,
                    manifest=prepared.manifest_member,
                    font=prepared.font_member,
                )
                self.exports.bind_command(actor, binding, export_id, command)
                accepted = executor.execute(command, source_root=source_root)
            except Exception:

                def stopped(execution: RenderExecution) -> None:
                    if execution != claim.execution:
                        raise ValueError("KAKAO_ARCHIVE_EXPORT_EXECUTION_MISMATCH")
                    # The single DB claim winner has not called any process adapter
                    # before command creation. After that point require OS evidence.
                    if command is not None:
                        self.assert_stopped(command, self.workspace_root / execution.attempt_id)

                self.exports.fail_attempt(
                    actor,
                    binding,
                    export_id,
                    claim.execution,
                    error_code="KAKAO_PDF_EXECUTION_FAILED",
                    assert_stopped=stopped,
                )
                raise
        assert command is not None
        return self._finish(actor, binding, export_id, command, accepted, source_root, authorize)

    def _finish(
        self,
        actor: ActorContext,
        binding: str,
        export_id: str,
        command: RenderCommand,
        accepted: AcceptedKakaoPdf,
        source_root: Path,
        authorize: Callable[[RenderCommand], None],
    ) -> KakaoExport:
        def stopped(execution: RenderExecution) -> None:
            if execution != command.execution:
                raise ValueError("KAKAO_ARCHIVE_EXPORT_EXECUTION_MISMATCH")
            self.assert_stopped(command, self.workspace_root / execution.attempt_id)

        if accepted.result.status != "COMPLETED":
            layout = accepted.result.status == "NEEDS_LAYOUT_REVIEW"
            return self.exports.fail_attempt(
                actor,
                binding,
                export_id,
                command.execution,
                error_code="KAKAO_PDF_LAYOUT_REVIEW_REQUIRED"
                if layout
                else "KAKAO_PDF_INPUT_INVALID",
                assert_stopped=stopped,
                layout_review=layout,
            )
        raw_manifest = read_pinned(source_root, command.manifest, uid=os.geteuid())
        publication = publish_kakao_pdf(
            self.artifacts,
            command=command,
            manifest_bytes=raw_manifest,
            accepted=accepted,
            authorize=lambda: authorize(command),
        )
        # Publication/adoption errors deliberately leave this exact RUNNING command
        # recoverable; they are not a failed render and must not trigger new output.
        return self.exports.complete_export(actor, binding, export_id, command, publication)
