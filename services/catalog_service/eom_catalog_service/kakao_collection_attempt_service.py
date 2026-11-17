"""Own exact capture attempts and accepted evidence, without launching browser actions.

File reads use the existing Artifact owner outside locks. Only trusted installed
composition calls this application; worker DTOs and public request IDs are not grants.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from eom_catalog_contracts.kakao_collection_attempt import KakaoCollectionAttempt
from eom_catalog_contracts.kakao_source import (
    CAPTURE_REF,
    SOURCE_RESOLUTION_REF,
    KakaoCaptureAuthority,
    KakaoSourceAdmission,
)
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_kakao_archive_contracts.capture import (
    CaptureCapability,
    CaptureCommand,
    CaptureInventory,
    CaptureResult,
    CaptureRoomReport,
    validate_capture_inputs,
    validate_capture_result,
)
from eom_operator_identity import ActorContext, PermissionKey
from eom_orchestrator.database import build_session_factory
from eom_protocol.artifact_members import ArtifactMemberPointer
from pydantic import BaseModel
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from .artifacts import CatalogArtifactService
from .kakao_archive_authorization import KakaoArchiveError, authorize_kakao_actor
from .kakao_archive_commands import kakao_command_sha256
from .kakao_capability_models import KakaoCapabilityAcceptanceRecord as Capability
from .kakao_capture_publication import (
    AcceptedCapturePublication,
    CaptureMemberReader,
    publish_kakao_capture_source,
)
from .kakao_collection_attempt_models import KakaoCollectionAttemptRecord as Attempt
from .kakao_collection_authorization import (
    authorize_kakao_collection_preparation,
    lock_kakao_collection_browser,
    validate_kakao_collection_pins,
)
from .kakao_collection_browser_models import KakaoCollectionBrowserRecord as Browser
from .kakao_collection_models import KakaoCollectionRunRecord as Run
from .kakao_collection_models import KakaoCollectionTaskRecord as Task
from .kakao_manual_models import KakaoProfileRuntimeRecord as Profile
from .kakao_source_models import KakaoSourceCommandRecord, KakaoSourceRevisionRecord
from .kakao_source_pointers import validate_source_pointer_metadata_batch
from .kakao_source_service import AcceptedKakaoSource, KakaoSourceService

_INVALID = "KAKAO_ARCHIVE_CAPTURE_EVIDENCE_INVALID"


def _identity(row: Attempt) -> KakaoCollectionAttempt:
    return KakaoCollectionAttempt.model_validate(
        {
            name: getattr(row, name)
            for name in KakaoCollectionAttempt.model_fields
            if name != "schema_version"
        }
    )


def _pointer(artifact: str, revision: str, member: str, sha256: str) -> ArtifactMemberPointer:
    return ArtifactMemberPointer(
        artifact_id=artifact,
        artifact_revision_id=revision,
        member_path=member,
        schema_ref=CAPTURE_REF,
        media_type="application/json",
        sha256=sha256,
    )


def _command_pointer(row: Attempt) -> ArtifactMemberPointer:
    if (
        row.command_artifact_id is None
        or row.command_artifact_revision_id is None
        or row.command_sha256 is None
    ):
        raise KakaoArchiveError(_INVALID)
    return _pointer(
        row.command_artifact_id,
        row.command_artifact_revision_id,
        "command.json",
        row.command_sha256,
    )


@dataclass(frozen=True, slots=True)
class _CommandContext:
    attempt: KakaoCollectionAttempt
    capability: ArtifactMemberPointer
    command: ArtifactMemberPointer | None


def _inventory_pointer(row: Attempt) -> ArtifactMemberPointer:
    if (
        row.inventory_artifact_id is None
        or row.inventory_artifact_revision_id is None
        or row.inventory_sha256 is None
    ):
        raise KakaoArchiveError(_INVALID)
    return _pointer(
        row.inventory_artifact_id,
        row.inventory_artifact_revision_id,
        "inventory.json",
        row.inventory_sha256,
    )


class KakaoCollectionAttemptService:
    def __init__(
        self,
        engine: Engine,
        *,
        artifacts: CatalogArtifactService,
        profile_id: str,
        adapter_release_sha256: str,
    ) -> None:
        self._sessions = build_session_factory(engine)
        self.artifacts = artifacts
        self.profile_id, self.adapter_sha256 = profile_id, adapter_release_sha256
        self._sources = KakaoSourceService(
            engine, artifacts=artifacts, authorize_capture=self.authorize_source
        )

    def _authorize(self, session: Session, run: Run) -> None:
        authorize_kakao_collection_preparation(
            session, run, adapter_release_sha256=self.adapter_sha256
        )

    def get_attempt(self, attempt_id: str) -> KakaoCollectionAttempt:
        """Internal exact metadata, not a public read or execution credential."""
        with self._sessions.begin() as session:
            row = session.get(Attempt, attempt_id)
            if row is None:
                raise KakaoArchiveError("KAKAO_ARCHIVE_RESOURCE_NOT_FOUND")
            return _identity(row)

    @staticmethod
    def _current(browser: Browser, profile: Profile, run: Run) -> None:
        if (
            browser.phase != "RUNNING"
            or profile.mode != "AUTO"
            or profile.current_lease_id is not None
            or profile.current_collection_browser_run_id != browser.browser_run_id
            or run.current_browser_run_id != browser.browser_run_id
            or profile.fence_epoch != browser.fence_epoch
            or (profile.owner_operator_id, profile.source_binding_id)
            != (run.owner_operator_id, run.source_binding_id)
        ):
            raise KakaoArchiveError("KAKAO_ARCHIVE_COLLECTION_FENCE_STALE")

    def reserve_attempt(self, task_id: str, *, browser_run_id: str) -> KakaoCollectionAttempt:
        with self._sessions.begin() as session:
            browser, profile, run = lock_kakao_collection_browser(
                session, browser_run_id, profile_id=self.profile_id
            )
            self._authorize(session, run)
            task = session.scalar(select(Task).where(Task.task_id == task_id).with_for_update())
            if task is None or (task.run_id, task.source_binding_id, task.room_id) != (
                run.run_id,
                run.source_binding_id,
                run.anchor_room_id,
            ):
                raise KakaoArchiveError("KAKAO_ARCHIVE_RESOURCE_NOT_FOUND")
            prior = session.scalar(select(Attempt).where(Attempt.task_id == task_id))
            if prior is not None:
                if prior.browser_run_id != browser_run_id:
                    raise KakaoArchiveError("KAKAO_ARCHIVE_COLLECTION_FENCE_STALE")
                return _identity(prior)
            self._current(browser, profile, run)
            if task.state != "QUEUED":
                raise KakaoArchiveError("KAKAO_ARCHIVE_PRECONDITION_FAILED")
            now = datetime.now(UTC)
            if browser.browser_observed_at is None or now < browser.browser_observed_at:
                raise KakaoArchiveError("KAKAO_ARCHIVE_COLLECTION_OBSERVATION_STALE")
            row = Attempt(
                attempt_id="kakaoattempt_" + uuid4().hex,
                command_id="kakaocommand_" + uuid4().hex,
                task_id=task_id,
                run_id=run.run_id,
                source_binding_id=run.source_binding_id,
                room_id=task.room_id,
                profile_id=profile.profile_id,
                browser_run_id=browser_run_id,
                fence=browser.fence_epoch,
                attempt_number=1,
                snapshot_revision_id="kakaosnapshotrev_" + uuid4().hex,
                normalization_revision_id="kakaonormalizationrev_" + uuid4().hex,
                created_at=now,
                updated_at=now,
                resource_version=1,
                state="RESERVED",
            )
            session.add(row)
            session.flush()
            return _identity(row)

    def _context(self, session: Session, row: Attempt, cap_sha256: str) -> _CommandContext:
        run = session.get(Run, row.run_id)
        if run is None:
            raise KakaoArchiveError(_INVALID)
        self._authorize(session, run)
        cap = session.get(Capability, run.capability_revision_id)
        if cap is None:
            raise KakaoArchiveError(_INVALID)
        pointer = _pointer(
            cap.manifest_artifact_id,
            cap.manifest_artifact_revision_id,
            "capability.json",
            cap_sha256,
        )
        validate_source_pointer_metadata_batch(
            session, (pointer, *((_inventory_pointer(row),) if row.state != "RESERVED" else ()))
        )
        return _CommandContext(
            _identity(row), pointer, None if row.state == "RESERVED" else _command_pointer(row)
        )

    def _read[T: BaseModel](self, pointer: ArtifactMemberPointer, model: type[T]) -> T:
        if pointer.schema_ref != CAPTURE_REF or pointer.media_type != "application/json":
            raise KakaoArchiveError(_INVALID)
        try:
            payload = self.artifacts.read_member(
                artifact_id=pointer.artifact_id,
                revision_id=pointer.artifact_revision_id,
                member_path=pointer.member_path,
                sha256=pointer.sha256,
                schema_ref=CAPTURE_REF,
                media_type="application/json",
                max_bytes=4 * 1024 * 1024,
            )
            value = model.model_validate_json(payload)
            if sha256_bytes(canonical_json_bytes(value.model_dump(mode="json"))) != pointer.sha256:
                raise ValueError("noncanonical evidence")
            return value
        except (ValueError, OSError):
            raise KakaoArchiveError(_INVALID) from None

    @staticmethod
    def _match(command: CaptureCommand, expected: KakaoCollectionAttempt) -> None:
        if (
            command.operation != "CAPTURE_ROOM"
            or any(
                getattr(command, key) != getattr(expected, key)
                for key in (
                    "run_id",
                    "source_binding_id",
                    "room_id",
                    "profile_id",
                    "browser_run_id",
                    "snapshot_revision_id",
                    "normalization_revision_id",
                )
            )
            or any(
                getattr(command.execution, key) != getattr(expected, key)
                for key in ("command_id", "task_id", "attempt_id", "attempt_number", "fence")
            )
            or command.issued_at < expected.created_at
        ):
            raise KakaoArchiveError("KAKAO_ARCHIVE_CAPTURE_IDENTITY_MISMATCH")

    def pin_command(
        self,
        attempt_id: str,
        pointer: ArtifactMemberPointer,
        *,
        inventory_pointer: ArtifactMemberPointer,
    ) -> KakaoCollectionAttempt:
        if pointer.member_path != "command.json":
            raise KakaoArchiveError(_INVALID)
        command = self._read(pointer, CaptureCommand)
        with self._sessions.begin() as session:
            row = session.get(Attempt, attempt_id)
            if row is None:
                raise KakaoArchiveError("KAKAO_ARCHIVE_RESOURCE_NOT_FOUND")
            context = self._context(session, row, command.capability.sha256)
        self._match(command, context.attempt)
        capability = self._read(context.capability, CaptureCapability)
        if command.inventory is None:
            raise KakaoArchiveError(_INVALID)
        if (
            inventory_pointer.member_path != "inventory.json"
            or inventory_pointer.sha256 != command.inventory.sha256
        ):
            raise KakaoArchiveError(_INVALID)
        inventory = self._read(inventory_pointer, CaptureInventory)
        try:
            validate_capture_inputs(command, capability, inventory)
        except ValueError:
            raise KakaoArchiveError(_INVALID) from None
        with self._sessions.begin() as session:
            browser, profile, run = lock_kakao_collection_browser(
                session, context.attempt.browser_run_id, profile_id=self.profile_id
            )
            self._authorize(session, run)
            task = session.scalar(
                select(Task).where(Task.task_id == context.attempt.task_id).with_for_update()
            )
            row = session.scalar(
                select(Attempt)
                .where(Attempt.attempt_id == attempt_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            assert row is not None and task is not None
            current = self._context(session, row, command.capability.sha256)
            self._match(command, current.attempt)
            validate_source_pointer_metadata_batch(
                session, (pointer, inventory_pointer, current.capability)
            )
            if row.state != "RESERVED":
                if _command_pointer(row) != pointer or _inventory_pointer(row) != inventory_pointer:
                    raise KakaoArchiveError("KAKAO_ARCHIVE_IDEMPOTENCY_CONFLICT")
                return _identity(row)
            self._current(browser, profile, run)
            if run.state != "QUEUED" or task.state != "QUEUED":
                raise KakaoArchiveError("KAKAO_ARCHIVE_PRECONDITION_FAILED")
            row.state, row.command_artifact_id, row.command_artifact_revision_id = (
                "COMMAND_READY",
                pointer.artifact_id,
                pointer.artifact_revision_id,
            )
            row.command_sha256, row.capability_sha256 = pointer.sha256, current.capability.sha256
            row.inventory_artifact_id = inventory_pointer.artifact_id
            row.inventory_artifact_revision_id = inventory_pointer.artifact_revision_id
            row.inventory_sha256 = inventory_pointer.sha256
            row.resource_version, row.updated_at = row.resource_version + 1, datetime.now(UTC)
            task.state = "RUNNING"
            run.state, run.resource_version, run.updated_at = (
                "COLLECTING",
                run.resource_version + 1,
                row.updated_at,
            )
            session.flush()
            return _identity(row)

    def accept_result(
        self, attempt_id: str, pointer: ArtifactMemberPointer
    ) -> KakaoCollectionAttempt:
        if pointer.member_path != "result.json":
            raise KakaoArchiveError(_INVALID)
        with self._sessions.begin() as session:
            row = session.get(Attempt, attempt_id)
            if row is None or row.state == "RESERVED" or row.capability_sha256 is None:
                raise KakaoArchiveError(_INVALID)
            context = self._context(session, row, row.capability_sha256)
        assert context.command is not None
        command = self._read(context.command, CaptureCommand)
        capability = self._read(context.capability, CaptureCapability)
        result = self._read(pointer, CaptureResult)
        report_pointer = (
            None
            if result.report is None
            else _pointer(
                pointer.artifact_id,
                pointer.artifact_revision_id,
                "room-report.json",
                result.report.sha256,
            )
        )
        report = None if report_pointer is None else self._read(report_pointer, CaptureRoomReport)
        self._match(command, context.attempt)
        try:
            validate_capture_result(
                command, result, report, capability=capability, current_fence=context.attempt.fence
            )
        except ValueError:
            raise KakaoArchiveError(_INVALID) from None
        with self._sessions.begin() as session:
            browser, profile, run = lock_kakao_collection_browser(
                session, context.attempt.browser_run_id, profile_id=self.profile_id
            )
            self._authorize(session, run)
            task = session.scalar(
                select(Task).where(Task.task_id == context.attempt.task_id).with_for_update()
            )
            row = session.scalar(
                select(Attempt)
                .where(Attempt.attempt_id == attempt_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            assert row is not None and task is not None
            current = self._context(session, row, context.capability.sha256)
            if (
                current.command != context.command
                or row.capability_sha256 != context.capability.sha256
            ):
                raise KakaoArchiveError(_INVALID)
            validate_source_pointer_metadata_batch(
                session,
                (
                    pointer,
                    context.command,
                    context.capability,
                    *((report_pointer,) if report_pointer else ()),
                ),
            )
            if row.state == "RESULT_ACCEPTED":
                if (row.result_artifact_id, row.result_artifact_revision_id, row.result_sha256) != (
                    pointer.artifact_id,
                    pointer.artifact_revision_id,
                    pointer.sha256,
                ):
                    raise KakaoArchiveError("KAKAO_ARCHIVE_IDEMPOTENCY_CONFLICT")
                return _identity(row)
            if browser.phase == "CLOSED":
                if (
                    result.status in {"COMPLETED", "PARTIAL"} and browser.close_kind != "STOPPED"
                ) or (
                    report is not None
                    and (browser.closed_at is None or report.observed_end_at > browser.closed_at)
                ):
                    raise KakaoArchiveError("KAKAO_ARCHIVE_COLLECTION_FENCE_STALE")
            else:
                self._current(browser, profile, run)
            row.state = "RESULT_ACCEPTED"
            row.result_artifact_id, row.result_artifact_revision_id, row.result_sha256 = (
                pointer.artifact_id,
                pointer.artifact_revision_id,
                pointer.sha256,
            )
            row.result_status, row.error_code = result.status, result.error_code
            row.report_sha256 = None if report_pointer is None else report_pointer.sha256
            row.resource_version, row.updated_at = row.resource_version + 1, datetime.now(UTC)
            task.state = {
                "COMPLETED": "RUNNING",
                "PARTIAL": "RUNNING",
                "FAILED": "FAILED",
                "CANCELLED": "CANCELLED",
                "PAUSED": "RUNNING",
            }[result.status]
            session.flush()
            return _identity(row)

    def authorize_source(
        self, session: Session, actor: ActorContext, admission: KakaoSourceAdmission
    ) -> None:
        """Mandatory SourceService callback, never a worker-provided authority declaration."""
        owner = authorize_kakao_actor(
            session,
            actor,
            PermissionKey.KAKAO_ARCHIVE_COLLECT,
            now=datetime.now(UTC),
            admin_only=True,
        )
        row = session.get(Attempt, admission.authority.attempt_id)
        if (
            row is None
            or row.state != "RESULT_ACCEPTED"
            or row.result_status not in {"COMPLETED", "PARTIAL"}
        ):
            raise KakaoArchiveError("KAKAO_ARCHIVE_ADMISSION_AUTHORITY_REQUIRED")
        run = session.get(Run, row.run_id)
        if run is None or run.owner_operator_id != owner:
            raise KakaoArchiveError("KAKAO_ARCHIVE_ADMISSION_AUTHORITY_REQUIRED")
        prior = session.scalar(
            select(KakaoSourceCommandRecord).where(
                KakaoSourceCommandRecord.capture_attempt_id == row.attempt_id,
                KakaoSourceCommandRecord.source_binding_id == row.source_binding_id,
                KakaoSourceCommandRecord.owner_operator_id == owner,
            )
        )
        if (
            prior is not None
            and prior.state == "COMPLETED"
            and prior.request_sha256 == kakao_command_sha256(admission)
        ):
            validate_kakao_collection_pins(session, run)
        else:
            self._authorize(session, run)
        cap = session.get(Capability, run.capability_revision_id)
        assert cap is not None
        validate_source_pointer_metadata_batch(session, (_inventory_pointer(row),))
        auth = admission.authority
        if (
            (
                admission.source_binding_id,
                admission.room_id,
                admission.snapshot_revision_id,
                admission.normalization_revision_id,
            )
            != (
                row.source_binding_id,
                row.room_id,
                row.snapshot_revision_id,
                row.normalization_revision_id,
            )
            or (
                auth.run_id,
                auth.fence,
                auth.command_sha256,
                auth.capability_revision_id,
                auth.adapter_release_sha256,
            )
            != (
                row.run_id,
                row.fence,
                row.command_sha256,
                run.capability_revision_id,
                run.adapter_release_sha256,
            )
            or auth.command != _command_pointer(row)
            or auth.capability
            != _pointer(
                cap.manifest_artifact_id,
                cap.manifest_artifact_revision_id,
                "capability.json",
                row.capability_sha256 or "",
            )
            or auth.capture_result
            != _pointer(
                row.result_artifact_id or "",
                row.result_artifact_revision_id or "",
                "result.json",
                row.result_sha256 or "",
            )
            or auth.capture_report
            != _pointer(
                row.result_artifact_id or "",
                row.result_artifact_revision_id or "",
                "room-report.json",
                row.report_sha256 or "",
            )
        ):
            raise KakaoArchiveError("KAKAO_ARCHIVE_ADMISSION_AUTHORITY_REQUIRED")

    def admit_capture_source(
        self, actor: ActorContext, admission: KakaoSourceAdmission, *, idempotency_key: str
    ) -> AcceptedKakaoSource:
        """Resume the same source commit before marking its original task accepted.

        A source commit and task adoption have separate transaction boundaries.
        Source replay resolves the original revision if the process stopped between
        them; neither the download nor the capture attempt is run again here.
        """
        source = self._sources.admit_source(actor, admission, idempotency_key=idempotency_key)
        self.accept_source_revision(
            actor,
            source.resolution.admission.authority.attempt_id,
            source.resolution.source_revision_id,
        )
        return source

    def _publication_context(
        self, actor: ActorContext, attempt_id: str
    ) -> tuple[_CommandContext, ArtifactMemberPointer, ArtifactMemberPointer]:
        with self._sessions.begin() as session:
            owner = authorize_kakao_actor(
                session,
                actor,
                PermissionKey.KAKAO_ARCHIVE_COLLECT,
                now=datetime.now(UTC),
                admin_only=True,
            )
            row = session.get(Attempt, attempt_id)
            run = None if row is None else session.get(Run, row.run_id)
            if (
                row is None
                or run is None
                or run.owner_operator_id != owner
                or row.state != "RESULT_ACCEPTED"
                or row.result_status not in {"COMPLETED", "PARTIAL"}
                or row.capability_sha256 is None
                or row.report_sha256 is None
                or row.result_artifact_id is None
                or row.result_artifact_revision_id is None
                or row.result_sha256 is None
            ):
                raise KakaoArchiveError("KAKAO_ARCHIVE_ADMISSION_AUTHORITY_REQUIRED")
            context = self._context(session, row, row.capability_sha256)
            result = _pointer(
                row.result_artifact_id,
                row.result_artifact_revision_id,
                "result.json",
                row.result_sha256,
            )
            report = _pointer(
                row.result_artifact_id,
                row.result_artifact_revision_id,
                "room-report.json",
                row.report_sha256,
            )
            validate_source_pointer_metadata_batch(session, (result, report))
            return context, result, report

    def publish_and_admit_capture_source(
        self,
        actor: ActorContext,
        attempt_id: str,
        *,
        read_member: CaptureMemberReader,
        idempotency_key: str,
        expected_source_revision_id: str | None,
        expected_resource_version: int,
    ) -> AcceptedKakaoSource:
        """Connect actual accepted output to originals/source/task with same-request recovery.

        The caller pins the source precondition and supplies the trusted local
        input reader. A public client/worker cannot choose this composition.
        Completed replay never requires the worker workspace to still exist.
        """
        attempt = self.get_attempt(attempt_id)
        prior = self._sources.completed_capture_source(
            actor,
            attempt.source_binding_id,
            attempt.room_id,
            capture_attempt_id=attempt_id,
            idempotency_key=idempotency_key,
            expected_source_revision_id=expected_source_revision_id,
            expected_resource_version=expected_resource_version,
        )
        if prior is not None:
            return self.admit_capture_source(
                actor, prior.resolution.admission, idempotency_key=idempotency_key
            )
        expected = self._publication_context(actor, attempt_id)

        def authorize() -> None:
            if self._publication_context(actor, attempt_id) != expected:
                raise KakaoArchiveError("KAKAO_ARCHIVE_CAPTURE_EVIDENCE_INVALID")

        context, result_pointer, report_pointer = expected
        assert context.command is not None
        command = self._read(context.command, CaptureCommand)
        capture = AcceptedCapturePublication(
            authority=KakaoCaptureAuthority(
                run_id=command.run_id,
                attempt_id=attempt_id,
                fence=command.execution.fence,
                command_sha256=context.command.sha256,
                capability_revision_id=command.capability_revision_id,
                adapter_release_sha256=command.adapter_release_sha256,
                command=context.command,
                capability=context.capability,
                capture_report=report_pointer,
                capture_result=result_pointer,
            ),
            command=command,
            capability=self._read(context.capability, CaptureCapability),
            result=self._read(result_pointer, CaptureResult),
            report=self._read(report_pointer, CaptureRoomReport),
        )
        try:
            admission = publish_kakao_capture_source(
                self.artifacts,
                capture=capture,
                read_member=read_member,
                authorize=authorize,
                expected_source_revision_id=expected_source_revision_id,
                expected_resource_version=expected_resource_version,
            )
        except (ValueError, OSError):
            raise KakaoArchiveError("KAKAO_ARCHIVE_CAPTURE_EVIDENCE_INVALID") from None
        return self.admit_capture_source(actor, admission, idempotency_key=idempotency_key)

    def accept_source_revision(
        self, actor: ActorContext, attempt_id: str, source_revision_id: str
    ) -> KakaoCollectionAttempt:
        """Advance task only after the existing source owner committed its validated revision."""
        with self._sessions.begin() as session:
            seed = session.get(Attempt, attempt_id)
            if seed is None:
                raise KakaoArchiveError("KAKAO_ARCHIVE_RESOURCE_NOT_FOUND")
            _, _, run = lock_kakao_collection_browser(
                session, seed.browser_run_id, profile_id=self.profile_id
            )
            owner = authorize_kakao_actor(
                session,
                actor,
                PermissionKey.KAKAO_ARCHIVE_COLLECT,
                now=datetime.now(UTC),
                admin_only=True,
            )
            task = session.scalar(
                select(Task).where(Task.task_id == seed.task_id).with_for_update()
            )
            source = session.get(KakaoSourceRevisionRecord, source_revision_id)
            command = (
                None if source is None else session.get(KakaoSourceCommandRecord, source.command_id)
            )
            if (
                task is None
                or source is None
                or command is None
                or run.owner_operator_id != owner
                or source.owner_operator_id != owner
                or seed.state != "RESULT_ACCEPTED"
                or seed.result_status not in {"COMPLETED", "PARTIAL"}
                or command.capture_attempt_id != attempt_id
                or command.state != "COMPLETED"
                or (
                    source.source_binding_id,
                    source.room_id,
                    source.snapshot_revision_id,
                    source.normalization_revision_id,
                )
                != (
                    seed.source_binding_id,
                    seed.room_id,
                    seed.snapshot_revision_id,
                    seed.normalization_revision_id,
                )
            ):
                raise KakaoArchiveError("KAKAO_ARCHIVE_ADMISSION_AUTHORITY_REQUIRED")
            if task.state == "LOCAL_ACCEPTED":
                return _identity(seed)
            self._authorize(session, run)
            validate_source_pointer_metadata_batch(
                session,
                (
                    ArtifactMemberPointer(
                        artifact_id=source.manifest_artifact_id,
                        artifact_revision_id=source.manifest_artifact_revision_id,
                        member_path="resolution.json",
                        schema_ref=SOURCE_RESOLUTION_REF,
                        media_type="application/json",
                        sha256=source.manifest_sha256,
                    ),
                ),
            )
            if task.state != "RUNNING":
                raise KakaoArchiveError("KAKAO_ARCHIVE_PRECONDITION_FAILED")
            task.state = "LOCAL_ACCEPTED"
            return _identity(seed)
