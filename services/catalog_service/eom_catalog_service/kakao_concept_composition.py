"""PLAN result → official textbook retrieval → exact persisted COMPOSE input."""

import tempfile
from collections.abc import Callable
from pathlib import Path

from eom_catalog_contracts.kakao_concept_knowledge import (
    CONCEPT_KNOWLEDGE_REF,
    MAX_CONCEPT_KNOWLEDGE_BYTES,
    KakaoConceptKnowledge,
    KakaoConceptPagePin,
)
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_kakao_archive_contracts.concepts import (
    ConceptComposeRequest,
    ConceptPlan,
    ConceptPlanRequest,
)
from eom_operator_identity import ActorContext
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_workflow.kakao_concept_request import (
    CONCEPT_REQUEST_REF,
    KakaoConceptFile,
    KakaoConceptWork,
    validate_kakao_concept_request_bytes,
)

from .kakao_archive_authorization import KakaoArchiveError
from .kakao_concept_knowledge import KakaoConceptKnowledgeReader, ResolvedConceptTextbookKnowledge
from .kakao_concept_models import KakaoConceptPhaseRecord
from .kakao_concept_pages import ConceptPageSource, validate_kakao_concept_page_sources
from .kakao_concept_phase_results import read_kakao_concept_phase_result
from .kakao_concept_task_service import KakaoConceptSourceAuthority, KakaoConceptTaskService


def _question_authorizer(authority: KakaoConceptSourceAuthority) -> Callable[[], None]:
    def authorize() -> None:
        with authority.service.sessions() as session:
            authority.service.accepted_intent_row(
                session, authority.intent, operator_id=authority.owner_operator_id
            )

    return authorize


def read_kakao_concept_composition(
    authority: KakaoConceptSourceAuthority, work: KakaoConceptWork
) -> tuple[ConceptComposeRequest, KakaoConceptKnowledge]:
    if work.phase != "COMPOSE":
        raise KakaoArchiveError("KAKAO_CONCEPT_PHASE_INVALID")
    artifacts = authority.service.artifacts
    raw = artifacts.read_member(
        artifact_id=work.request_member.artifact_id,
        revision_id=work.request_member.artifact_revision_id,
        member_path=work.request_member.member_path,
        schema_ref=work.request_member.schema_ref,
        media_type=work.request_member.media_type,
        sha256=work.request_member.sha256,
        max_bytes=work.request_bytes,
    )
    request = validate_kakao_concept_request_bytes(work, raw)
    if not isinstance(request, ConceptComposeRequest):
        raise KakaoArchiveError("KAKAO_CONCEPT_PHASE_INVALID")
    pointer = artifacts.published_member_pointer(
        artifact_id=work.request_member.artifact_id,
        revision_id=work.request_member.artifact_revision_id,
        member_path="knowledge.json",
        schema_ref=CONCEPT_KNOWLEDGE_REF,
        media_type="application/json",
        max_bytes=MAX_CONCEPT_KNOWLEDGE_BYTES,
    )
    provenance = artifacts.read_member(
        artifact_id=pointer.artifact_id,
        revision_id=pointer.artifact_revision_id,
        member_path=pointer.member_path,
        schema_ref=pointer.schema_ref,
        media_type=pointer.media_type,
        sha256=pointer.sha256,
        max_bytes=MAX_CONCEPT_KNOWLEDGE_BYTES,
    )
    receipt = KakaoConceptKnowledge.model_validate_json(provenance)
    if canonical_json_bytes(receipt) != provenance or (
        receipt.task_id,
        receipt.request_sha256,
        receipt.scope,
    ) != (work.task_id, work.request_member.sha256, authority.intent.scope):
        raise KakaoArchiveError("KAKAO_CONCEPT_KNOWLEDGE_POINTER_INVALID")
    return request, receipt


def authorize_kakao_concept_composition(
    reader: KakaoConceptKnowledgeReader,
    authority: KakaoConceptSourceAuthority,
    work: KakaoConceptWork,
) -> ResolvedConceptTextbookKnowledge:
    request, receipt = read_kakao_concept_composition(authority, work)
    planned = read_kakao_concept_phase_result(authority, "PLAN")
    if (
        not isinstance(planned.request, ConceptPlanRequest)
        or not isinstance(planned.result.output.output, ConceptPlan)
        or (
            receipt.plan_result,
            request.question,
            request.plan,
            request.additional_instructions,
            request.base_study_revision_id,
        )
        != (
            planned.pin,
            planned.request.question,
            planned.result.output.output,
            planned.request.additional_instructions,
            planned.request.base_study_revision_id,
        )
    ):
        raise KakaoArchiveError("KAKAO_CONCEPT_PLAN_RESULT_MISMATCH")
    knowledge = reader.restore(
        authority,
        work.source_binding_id,
        receipt,
        reauthorize_question=_question_authorizer(authority),
    )
    page_index = {page.page_key: page for page in request.context.pages}
    keys = tuple(f"{pin.evidence_key}P{pin.physical_page}" for pin in receipt.pages)
    if tuple(page_index) != keys:
        raise KakaoArchiveError("KAKAO_CONCEPT_PAGE_PIN_INVALID")
    sources = tuple(
        ConceptPageSource(page_index[key], pin.original)
        for key, pin in zip(keys, receipt.pages, strict=True)
    )
    validate_kakao_concept_page_sources(knowledge, request.context, sources)
    expected_files = {file.relative_path: file for file in planned.work.files}
    for source in sources:
        page = source.page
        file = KakaoConceptFile(
            relative_path=page.member.relative_path,
            source=source.original,
            size_bytes=page.member.size_bytes,
            width_pixels=page.width_pixels,
            height_pixels=page.height_pixels,
        )
        old = expected_files.setdefault(file.relative_path, file)
        if old != file:
            raise KakaoArchiveError("KAKAO_CONCEPT_FILE_COLLISION")
    if {file.relative_path: file for file in work.files} != expected_files:
        raise KakaoArchiveError("KAKAO_CONCEPT_WORK_MEMBER_SET_MISMATCH")
    return knowledge


def prepare_kakao_concept_composition(
    service: KakaoConceptTaskService,
    reader: KakaoConceptKnowledgeReader,
    *,
    actor: ActorContext | KakaoConceptSourceAuthority,
    binding_id: str,
    task_id: str,
) -> KakaoConceptWork:
    authority = (
        service.source_authority(actor, binding_id, task_id)
        if isinstance(actor, ActorContext)
        else actor
    )
    if authority.service is not service or (
        authority.intent.task_id,
        authority.intent.request.source_binding_id,
    ) != (task_id, binding_id):
        raise KakaoArchiveError("KAKAO_CONCEPT_WORK_NOT_ACCEPTED")
    _question_authorizer(authority)()
    with service.sessions() as session:
        old = session.get(KakaoConceptPhaseRecord, (task_id, "COMPOSE"))
        if old is not None:
            work = KakaoConceptWork.model_validate(old.work_input)
            return authority.reauthorize(
                session, operator_id=authority.owner_operator_id, work=work
            )
    planned = read_kakao_concept_phase_result(authority, "PLAN")
    if (
        not isinstance(planned.request, ConceptPlanRequest)
        or not isinstance(planned.result.output.output, ConceptPlan)
        or planned.result.output.output.status != "PLANNED"
    ):
        raise KakaoArchiveError("KAKAO_CONCEPT_PLAN_NOT_READY")
    authorize_question = _question_authorizer(authority)
    knowledge = reader.retrieve(
        authority,
        binding_id,
        scope=authority.intent.scope,
        plan=planned.result.output.output,
        reauthorize_question=authorize_question,
    )

    def authorize() -> None:
        reader.reauthorize(
            authority, binding_id, knowledge, reauthorize_question=authorize_question
        )

    with tempfile.TemporaryDirectory(
        prefix="kakao-concept-pages.", dir=service.artifacts.settings.staging_root
    ) as local:
        root = Path(local)
        pages = reader.prepare_pages(
            authority,
            binding_id,
            knowledge,
            source_root=root,
            reauthorize_question=authorize_question,
        )
        request = ConceptComposeRequest(
            task_id=task_id,
            question=planned.request.question,
            base_study_revision_id=planned.request.base_study_revision_id,
            additional_instructions=planned.request.additional_instructions,
            plan=planned.result.output.output,
            context=pages.context,
        )
        raw = canonical_json_bytes(request)
        receipt = KakaoConceptKnowledge(
            task_id=task_id,
            request_sha256=sha256_bytes(raw),
            plan_result=planned.pin,
            scope=knowledge.scope,
            materials=tuple(material.pin() for material in knowledge.materials),
            pages=tuple(
                KakaoConceptPagePin.model_validate(
                    dict(
                        evidence_key=source.page.evidence_key,
                        physical_page=source.page.physical_page,
                        original=source.original,
                    )
                )
                for source in pages.sources
            ),
        )
        provenance = canonical_json_bytes(receipt)
        files = {file.relative_path: file for file in planned.work.files}
        for source in pages.sources:
            page = source.page
            file = KakaoConceptFile(
                relative_path=page.member.relative_path,
                source=source.original,
                size_bytes=page.member.size_bytes,
                width_pixels=page.width_pixels,
                height_pixels=page.height_pixels,
            )
            if files.setdefault(file.relative_path, file) != file:
                raise KakaoArchiveError("KAKAO_CONCEPT_FILE_COLLISION")
        # Only JSON is newly published. Page/photograph bytes retain their canonical pointers.
        input_path, provenance_path = root / "request.json", root / "knowledge.json"
        input_path.write_bytes(raw)
        provenance_path.write_bytes(provenance)
        authorize()
        publication = service.artifacts.commit_file_set(
            files={"request.json": input_path, "knowledge.json": provenance_path},
            primary_file="request.json",
            artifact_type="kakao-concept-compose",
            idempotency_key=f"kakao:concept:{task_id}:compose",
            request=dict(
                task_id=task_id,
                request_sha256=sha256_bytes(raw),
                knowledge_sha256=sha256_bytes(provenance),
            ),
            result=dict(request_sha256=sha256_bytes(raw)),
            file_metadata={
                name: dict(media_type="application/json", schema_ref=schema)
                for name, schema in (
                    ("request.json", CONCEPT_REQUEST_REF),
                    ("knowledge.json", CONCEPT_KNOWLEDGE_REF),
                )
            },
            expected_file_sha256={
                "request.json": sha256_bytes(raw),
                "knowledge.json": sha256_bytes(provenance),
            },
        )
        if (publication.content_hash, publication.content_bytes) != (sha256_bytes(raw), len(raw)):
            raise KakaoArchiveError("KAKAO_CONCEPT_PUBLICATION_MISMATCH")
    authorize()
    pointer = ArtifactMemberPointer(
        artifact_id=publication.artifact_id,
        artifact_revision_id=publication.revision_id,
        member_path="request.json",
        schema_ref=CONCEPT_REQUEST_REF,
        media_type="application/json",
        sha256=sha256_bytes(raw),
    )
    work = KakaoConceptWork(
        task_id=task_id,
        phase="COMPOSE",
        source_binding_id=binding_id,
        question_revision_id=planned.work.question_revision_id,
        question_manifest=planned.work.question_manifest,
        request_member=pointer,
        request_bytes=len(raw),
        files=tuple(files.values()),
    )
    validate_kakao_concept_request_bytes(work, raw)
    return service.adopt_accepted_phase(authority, work)
