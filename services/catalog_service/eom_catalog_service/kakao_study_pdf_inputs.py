"""Saved edit selections to existing local PDF inputs; no renderer, model run or NAS writer."""

import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from eom_catalog_contracts.kakao_study_export import KakaoStudyExportPin
from eom_catalog_contracts.kakao_study_store import KakaoStudyQuestion
from eom_kakao_archive_contracts.render import (
    LocalMember,
    RenderImageReference,
    RenderText,
    RenderTextReference,
)
from eom_kakao_archive_contracts.study import StudyRenderManifest, StudySupplement
from eom_operator_identity import ActorContext
from eom_orchestrator.kakao_pdf_files import create_directory, read_pinned, write_local

from .kakao_archive_authorization import KakaoArchiveError
from .kakao_concept_study import KakaoPreparedConceptStudy, prepare_kakao_concept_study
from .kakao_pdf_inputs import MAX_IMAGES_BYTES
from .kakao_study_service import AcceptedKakaoStudy, KakaoStudyService


def select_kakao_study_supplements(
    selected: KakaoStudyQuestion, draft: KakaoPreparedConceptStudy | None
) -> tuple[StudySupplement, ...]:
    """Keep original citations/captures; users edit only the fields in their saved command."""
    edit = selected.edit
    values: list[StudySupplement] = []
    if edit.concept_task_id is None:
        if draft is not None or selected.result is not None or edit.blocks:
            raise KakaoArchiveError("KAKAO_STUDY_SOURCE_CHANGED")
    else:
        if draft is None or (draft.task_id, draft.question_revision_id, draft.result) != (
            edit.concept_task_id,
            edit.question_revision_id,
            selected.result,
        ):
            raise KakaoArchiveError("KAKAO_STUDY_SOURCE_CHANGED")
        by_id = {block.supplement_id: block for block in draft.supplements}
        for choice in edit.blocks:
            block = by_id.get(f"concept-{choice.block_index}")
            if block is None:
                raise KakaoArchiveError("KAKAO_STUDY_BLOCK_SELECTION_INVALID")
            changes = {}
            if choice.relevance is not None:
                changes[f"concept-{choice.block_index}-relevance"] = (
                    "질문과의 연결: " + choice.relevance
                )
            if choice.explanation is not None:
                changes[f"concept-{choice.block_index}-explanation"] = choice.explanation
            texts = tuple(
                RenderText(span_id=t.span_id, text=changes.get(t.span_id, t.text))
                for t in block.text_blocks
            )
            if not changes.keys() <= {t.span_id for t in block.text_blocks}:
                raise KakaoArchiveError("KAKAO_STUDY_BLOCK_SELECTION_INVALID")
            indices = (
                tuple(range(len(block.images)))
                if choice.capture_indices is None
                else choice.capture_indices
            )
            if any(index >= len(block.images) for index in indices):
                raise KakaoArchiveError("KAKAO_STUDY_BLOCK_SELECTION_INVALID")
            images = tuple(block.images[i] for i in indices)
            values.append(
                StudySupplement.model_validate(
                    block.model_dump(mode="json")
                    | dict(
                        title=choice.title if choice.title is not None else block.title,
                        origin="USER_NOTE" if changes else block.origin,
                        text_blocks=[t.model_dump(mode="json") for t in texts],
                        images=[p.model_dump(mode="json") for p in images],
                        ordered_blocks=[
                            *(
                                RenderTextReference(kind="TEXT", span_id=t.span_id).model_dump(
                                    mode="json"
                                )
                                for t in texts
                            ),
                            *(
                                RenderImageReference(
                                    kind="IMAGE",
                                    attachment_occurrence_id=p.attachment_occurrence_id,
                                ).model_dump(mode="json")
                                for p in images
                            ),
                        ],
                    )
                )
            )
        values.extend(
            block
            for block in draft.supplements
            if block.supplement_id in {"staff-checks", "limitations"}
        )
    for index, note in enumerate(edit.notes):
        key = f"note-{index}"
        values.append(
            StudySupplement(
                supplement_id=key,
                title=note.title,
                origin="USER_NOTE",
                text_blocks=(RenderText(span_id=key, text=note.text),),
                images=(),
                ordered_blocks=(RenderTextReference(kind="TEXT", span_id=key),),
                citations=(),
            )
        )
    if len(values) > 8:
        raise KakaoArchiveError("KAKAO_STUDY_BLOCK_SELECTION_INVALID")
    return tuple(values)


def _stage_supplements(
    values: tuple[StudySupplement, ...],
    *,
    source_root: Path,
    target_root: Path,
    staged: dict[str, LocalMember],
    available_bytes: int,
) -> tuple[tuple[StudySupplement, ...], int]:
    """Only selected crops cross the final input boundary; equal bytes are staged once."""
    result = []
    for block in values:
        images = []
        for image in block.images:
            member = image.member
            if member is None or member.media_type != "image/png":
                raise KakaoArchiveError("KAKAO_CONCEPT_CAPTURE_POINTER_INVALID")
            existing = staged.get(member.sha256)
            if existing is None:
                if member.size_bytes > available_bytes:
                    raise KakaoArchiveError("KAKAO_ARCHIVE_RENDER_INPUT_TOO_LARGE")
                raw = read_pinned(source_root, member, uid=os.geteuid(), gid=os.getgid())
                existing = member.model_copy(
                    update={"relative_path": "study-images/" + member.sha256[7:] + ".png"}
                )
                write_local(target_root, existing.relative_path, raw, gid=os.getgid())
                staged[member.sha256] = existing
                available_bytes -= member.size_bytes
            if (existing.size_bytes, existing.media_type) != (member.size_bytes, member.media_type):
                raise KakaoArchiveError("KAKAO_CONCEPT_CAPTURE_POINTER_INVALID")
            images.append(image.model_copy(update={"member": existing}))
        result.append(
            StudySupplement.model_validate(
                block.model_dump(mode="json")
                | dict(images=[i.model_dump(mode="json") for i in images])
            )
        )
    return tuple(result), available_bytes


@dataclass(frozen=True, slots=True)
class KakaoSavedStudyPdfSource:
    studies: KakaoStudyService = field(repr=False)
    actor: ActorContext = field(repr=False)
    binding_id: str
    pin: KakaoStudyExportPin

    def _read(self) -> AcceptedKakaoStudy:
        value = self.studies.get_study(
            self.actor,
            self.binding_id,
            self.pin.study_id,
            revision_id=self.pin.study_revision_id,
        )
        if value.stored.manifest.sha256 != self.pin.manifest_sha256:
            raise KakaoArchiveError("KAKAO_STUDY_SOURCE_CHANGED")
        return value

    def apply(self, manifest: StudyRenderManifest, source_root: Path) -> StudyRenderManifest:
        """Caller already projected/authorized original roles, source content and metadata."""
        value = self._read()
        if (
            manifest.study_revision_id is not None
            or (
                manifest.source_binding_id,
                manifest.packet_revision_id,
                manifest.student_id,
                manifest.subset_sha256,
                tuple(q.question_revision_id for q in manifest.questions),
            )
            != (
                self.binding_id,
                value.stored.packet_revision_id,
                value.stored.student_id,
                value.manifest.subset_sha256,
                tuple(q.edit.question_revision_id for q in value.manifest.questions),
            )
            or any(q.supplements for q in manifest.questions)
        ):
            raise KakaoArchiveError("KAKAO_STUDY_QUESTION_SET_MISMATCH")
        questions = []
        base_members = {
            p.value.member.relative_path: p.value.member
            for q in manifest.questions
            for content in (q.student, q.staff)
            if content is not None
            for p in content.images
            if p.value.member is not None
        }
        staged = {member.sha256: member for member in base_members.values()}
        available = MAX_IMAGES_BYTES - sum(m.size_bytes for m in base_members.values())
        for index, (question, selected) in enumerate(
            zip(manifest.questions, value.manifest.questions, strict=True)
        ):
            draft = None
            if selected.edit.concept_task_id is not None:
                if self.studies.concepts is None:
                    raise KakaoArchiveError("KAKAO_CONCEPT_RUNTIME_UNAVAILABLE")
                authority = self.studies.concepts.source_authority(
                    self.actor, self.binding_id, selected.edit.concept_task_id
                )
                with tempfile.TemporaryDirectory(
                    prefix=f"study-{index:04d}.", dir=self.studies.artifacts.settings.staging_root
                ) as folder:
                    root = Path(folder)
                    pages = create_directory(root, "pages", gid=os.getgid(), mode=0o700)
                    captures = create_directory(root, "images", gid=os.getgid(), mode=0o700)
                    draft = prepare_kakao_concept_study(
                        authority, source_root=pages, output_root=captures
                    )
                    blocks, available = _stage_supplements(
                        select_kakao_study_supplements(selected, draft),
                        source_root=captures,
                        target_root=source_root,
                        staged=staged,
                        available_bytes=available,
                    )
            else:
                blocks = select_kakao_study_supplements(selected, None)
            questions.append(
                question.model_dump(mode="json")
                | dict(supplements=[b.model_dump(mode="json") for b in blocks])
            )
        self._read()
        return StudyRenderManifest.model_validate(
            manifest.model_dump(mode="json")
            | dict(
                study_revision_id=self.pin.study_revision_id,
                questions=questions,
            )
        )
