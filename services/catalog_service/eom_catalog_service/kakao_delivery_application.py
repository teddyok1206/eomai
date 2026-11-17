"""Private packet and student-PDF use cases over existing durable owners."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from eom_catalog_contracts.kakao_delivery_rpc import (
    KakaoPacketStudent,
    KakaoPacketView,
    KakaoStudyView,
)
from eom_catalog_contracts.kakao_export_store import KakaoExportCreate, KakaoExportMutation
from eom_catalog_contracts.kakao_question import KakaoQuestionProvenance
from eom_catalog_contracts.kakao_study_export import (
    KakaoStudyExportCreate,
    KakaoStudyExportMutation,
)
from eom_catalog_contracts.kakao_study_store import KakaoStudyCreate, KakaoStudyQuestionEdit
from eom_operator_identity import ActorContext

from .kakao_archive_authorization import KakaoArchiveError
from .kakao_packet_service import KakaoPacketService

if TYPE_CHECKING:
    from .kakao_export_service import KakaoExportService
    from .kakao_study_service import KakaoStudyService


@dataclass(frozen=True, slots=True)
class KakaoDeliveryApplication:
    packets: KakaoPacketService
    exports: KakaoExportService | None = None
    submit_export: Callable[[ActorContext, str, str], None] | None = field(default=None, repr=False)
    studies: KakaoStudyService | None = None

    def read_packet(
        self, actor: ActorContext, binding: str, packet: str, revision: str
    ) -> KakaoPacketView:
        accepted = self.packets.get_packet(actor, binding, packet, revision_id=revision)
        students: dict[str, KakaoPacketStudent] = {}
        for question in accepted.packet.questions:
            pin = question.student
            previous = students.get(pin.student_id)
            students[pin.student_id] = KakaoPacketStudent(
                student_id=pin.student_id,
                student_display_revision_id=pin.student_display_revision_id,
                display_name=pin.display_name,
                question_count=1 if previous is None else previous.question_count + 1,
            )
        return KakaoPacketView(
            packet=accepted.stored,
            questions=tuple(
                KakaoQuestionProvenance(
                    question_id=q.question_id, question_revision_id=q.question_revision_id
                )
                for q in accepted.packet.questions
            ),
            students=tuple(students.values()),
        )

    def export_owner(self) -> KakaoExportService:
        if self.exports is None:
            raise KakaoArchiveError("KAKAO_ARCHIVE_PDF_RUNTIME_UNAVAILABLE")
        return self.exports

    def study_owner(self) -> KakaoStudyService:
        if self.studies is None:
            raise KakaoArchiveError("KAKAO_STUDY_RUNTIME_UNAVAILABLE")
        return self.studies

    def read_study(
        self, actor: ActorContext, binding: str, study: str, revision: str
    ) -> KakaoStudyView:
        accepted = self.study_owner().get_study(actor, binding, study, revision_id=revision)
        return KakaoStudyView(
            study=accepted.stored,
            questions=tuple(question.edit for question in accepted.manifest.questions),
        )

    def read_study_selection(
        self, actor: ActorContext, binding: str, packet: str, revision: str, student: str
    ) -> KakaoStudyCreate:
        """Read an unsaved form from the authorized subset, without inventing a study identity."""
        accepted, selected = self.packets.resolve_student(
            actor, binding, packet, revision_id=revision, student_id=student
        )
        return KakaoStudyCreate(
            source_binding_id=binding,
            packet_id=packet,
            packet_revision_id=revision,
            student_id=student,
            title=accepted.stored.title,
            questions=tuple(
                KakaoStudyQuestionEdit(
                    question_revision_id=question.stored.question_revision_id,
                    concept_task_id=None,
                    blocks=(),
                    notes=(),
                )
                for question in selected.questions
            ),
        )

    def request_export(
        self, actor: ActorContext, command: KakaoExportCreate, *, idempotency_key: str
    ) -> KakaoExportMutation:
        if self.submit_export is None:
            raise KakaoArchiveError("KAKAO_ARCHIVE_PDF_RUNTIME_UNAVAILABLE")
        result = self.export_owner().request_export(actor, command, idempotency_key=idempotency_key)
        # GET and completed replay never dispatch a renderer. A pending replay can
        # restore a lost process-local wake-up without creating another DB export.
        if result.export.state in {"PENDING", "RUNNING"}:
            self.submit_export(actor, command.source_binding_id, result.export.export_id)
        return result

    def request_study_export(
        self, actor: ActorContext, command: KakaoStudyExportCreate, *, idempotency_key: str
    ) -> KakaoStudyExportMutation:
        if self.submit_export is None:
            raise KakaoArchiveError("KAKAO_ARCHIVE_PDF_RUNTIME_UNAVAILABLE")
        result = self.export_owner().request_study_export(
            actor, command, idempotency_key=idempotency_key
        )
        if result.result.export.state in {"PENDING", "RUNNING"}:
            self.submit_export(actor, command.source_binding_id, result.result.export.export_id)
        return result
