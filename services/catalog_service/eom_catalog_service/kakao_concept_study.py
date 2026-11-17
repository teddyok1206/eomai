"""Verified concept output to local study values; no saved revision or export is invented."""

from dataclasses import dataclass, field
from pathlib import Path

from eom_catalog_contracts.kakao_concept_knowledge import KakaoConceptResultPin
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_kakao_archive_contracts.concepts import (
    ConceptComposeRequest,
    ConceptComposition,
    ConceptResult,
    validate_concept_result,
)
from eom_kakao_archive_contracts.render import (
    RenderBlockReference,
    RenderImage,
    RenderImageReference,
    RenderText,
    RenderTextReference,
)
from eom_kakao_archive_contracts.study import StudyCitation, StudySupplement

from .kakao_archive_authorization import KakaoArchiveError
from .kakao_concept_composition import read_kakao_concept_composition
from .kakao_concept_pages import (
    CROP_PROFILE,
    PreparedConceptCapture,
    PreparedConceptPages,
    concept_crop_pixel_bounds,
    validate_kakao_concept_page_sources,
)
from .kakao_concept_phase_results import read_kakao_concept_phase_result
from .kakao_concept_task_service import KakaoConceptSourceAuthority


@dataclass(frozen=True, slots=True)
class KakaoPreparedConceptStudy:
    task_id: str
    question_revision_id: str
    result: KakaoConceptResultPin
    supplements: tuple[StudySupplement, ...]
    captures: tuple[PreparedConceptCapture, ...]
    source_root: Path = field(repr=False)


def project_kakao_concept_supplements(
    *,
    prepared: PreparedConceptPages,
    request: ConceptComposeRequest,
    result: ConceptResult,
    captures: tuple[PreparedConceptCapture, ...],
) -> tuple[StudySupplement, ...]:
    """Only verified local captures and exact evidence become display values, never authority."""
    validated = validate_concept_result(request, result.model_dump(mode="json"))
    if not isinstance(validated.output, ConceptComposition) or request.context != prepared.context:
        raise KakaoArchiveError("KAKAO_CONCEPT_CAPTURE_CONTEXT_MISMATCH")
    output = validated.output
    validate_kakao_concept_page_sources(prepared.knowledge, prepared.context, prepared.sources)
    pages = {source.page.page_key: source for source in prepared.sources}
    capture_index = {(c.block_index, c.capture_index): c for c in captures}
    expected = {(i, j) for i, b in enumerate(output.blocks) for j in range(len(b.captures))}
    if len(capture_index) != len(captures) or set(capture_index) != expected:
        raise KakaoArchiveError("KAKAO_CONCEPT_CAPTURE_SET_MISMATCH")
    materials = {f"E{i}": material for i, material in enumerate(prepared.knowledge.materials, 1)}
    if tuple(materials) != tuple(e.evidence_key for e in request.context.evidence):
        raise KakaoArchiveError("KAKAO_CONCEPT_EVIDENCE_TEXT_CHANGED")
    supplements = []
    for i, block in enumerate(output.blocks):
        texts = [
            RenderText(span_id=f"concept-{i}-relevance", text="질문과의 연결: " + block.relevance),
            RenderText(span_id=f"concept-{i}-explanation", text=block.explanation),
        ]
        citations: dict[tuple[str, str], StudyCitation] = {}
        images = []
        for j, citation in enumerate(block.citations):
            material = materials[citation.evidence_key]
            label = "승인된 분석 근거 · 교재 원문 인용 아님"
            if citation.quote is not None:
                label = "제공된 교재 원문 발췌 " + str(citation.passage_key)
                texts.append(
                    RenderText(
                        span_id=f"concept-{i}-quote-{j}", text="교재 원문 인용: " + citation.quote
                    )
                )
            citations[citation.evidence_key, label] = StudyCitation(
                evidence_id=citation.evidence_key,
                source_title=material.title,
                page_label=label,
                source_sha256=material.analysis.accepted_result.sha256,
            )
        for j, selection in enumerate(block.captures):
            capture = capture_index[i, j]
            source = pages.get(selection.page_key)
            if (
                source is None
                or capture.page_key != selection.page_key
                or capture.original != source.original
                or capture.profile != CROP_PROFILE
                or capture.member.media_type != "image/png"
                or capture.pixel_bounds
                != concept_crop_pixel_bounds(source.page, selection.rectangle)
            ):
                raise KakaoArchiveError("KAKAO_CONCEPT_CAPTURE_POINTER_INVALID")
            # These are display uses, not newly registered Kakao message attachments.
            identity = sha256_bytes(
                canonical_json_bytes(
                    dict(task=request.task_id, block=i, capture=j, sha256=capture.member.sha256)
                )
            )[7:39]
            images.append(
                RenderImage(
                    attachment_occurrence_id="kakaoattachment_" + identity,
                    attachment_revision_id="kakaoattachmentrev_" + identity,
                    member=capture.member,
                    availability="AVAILABLE",
                    quality_accepted=False,
                )
            )
            label = f"원본 PNG · 물리 페이지 {source.page.physical_page} · 인쇄 쪽수 미확인"
            key = source.page.evidence_key
            citations[key, label] = StudyCitation(
                evidence_id=key,
                source_title=materials[key].title,
                page_label=label,
                source_sha256=capture.original.sha256,
            )
        order: tuple[RenderBlockReference, ...] = (
            *(RenderTextReference(kind="TEXT", span_id=t.span_id) for t in texts),
            *(
                RenderImageReference(
                    kind="IMAGE", attachment_occurrence_id=p.attachment_occurrence_id
                )
                for p in images
            ),
        )
        supplements.append(
            StudySupplement(
                supplement_id=f"concept-{i}",
                title=block.title,
                origin="MODEL_DRAFT",
                text_blocks=tuple(texts),
                images=tuple(images),
                ordered_blocks=order,
                citations=tuple(citations.values()),
            )
        )
    notes = [
        (
            "staff-checks",
            "조교 답변 확인 메모 · 원래 답변은 변경하지 않음",
            tuple(f"{c.observation}\n확인 이유: {c.reason}" for c in output.staff_checks),
            tuple(
                StudyCitation(
                    evidence_id=key,
                    source_title=materials[key].title,
                    page_label="승인된 분석 근거 · 교재 원문 인용 아님",
                    source_sha256=materials[key].analysis.accepted_result.sha256,
                )
                for key in dict.fromkeys(
                    key for check in output.staff_checks for key in check.evidence_keys
                )
            ),
        ),
        (
            "limitations",
            "학습 주제와 자료의 한계",
            (
                output.focus_summary,
                *dict.fromkeys((*request.context.limitations, *output.limitations)),
            ),
            (),
        ),
    ]
    for key, title, values, note_citations in notes:
        if not values:
            continue
        texts = [RenderText(span_id=f"{key}-{i}", text=value) for i, value in enumerate(values)]
        supplements.append(
            StudySupplement(
                supplement_id=key,
                title=title,
                origin="MODEL_DRAFT",
                text_blocks=tuple(texts),
                images=(),
                ordered_blocks=tuple(
                    RenderTextReference(kind="TEXT", span_id=t.span_id) for t in texts
                ),
                citations=note_citations,
            )
        )
    return tuple(supplements)


def prepare_kakao_concept_study(
    authority: KakaoConceptSourceAuthority, *, source_root: Path, output_root: Path
) -> KakaoPreparedConceptStudy:
    """Read existing completed output; stage/crop originals through their supported owner."""
    completed = read_kakao_concept_phase_result(authority, "COMPOSE")
    request, _receipt = read_kakao_concept_composition(authority, completed.work)
    if request != completed.request:
        raise KakaoArchiveError("KAKAO_CONCEPT_RESULT_INPUT_MISMATCH")
    service = authority.service
    reader = service.knowledge_reader
    if reader is None:
        raise KakaoArchiveError("KAKAO_CONCEPT_KNOWLEDGE_NOT_CONFIGURED")

    def authorize() -> None:
        with service.sessions() as session:
            authority.reauthorize(
                session, operator_id=authority.owner_operator_id, work=completed.work
            )

    from .kakao_concept_composition import authorize_kakao_concept_composition

    knowledge = authorize_kakao_concept_composition(reader, authority, completed.work)
    prepared = reader.prepare_pages(
        authority,
        completed.work.source_binding_id,
        knowledge,
        source_root=source_root,
        reauthorize_question=authorize,
    )
    result = completed.result.output
    captures = reader.prepare_captures(
        authority,
        completed.work.source_binding_id,
        prepared,
        request=request,
        result=result,
        output_root=output_root,
        reauthorize_question=authorize,
    )
    supplements = project_kakao_concept_supplements(
        prepared=prepared, request=request, result=result, captures=captures
    )
    authorize()
    return KakaoPreparedConceptStudy(
        request.task_id,
        request.question.question_revision_id,
        completed.pin,
        supplements,
        captures,
        output_root,
    )
