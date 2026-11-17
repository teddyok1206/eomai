"""Publish exact optional concept inputs through the existing Artifact owner."""

import tempfile
from collections.abc import Callable
from pathlib import Path

from eom_catalog_contracts.kakao_concept_tasks import (
    CONCEPT_TASK_REF,
    MAX_CONCEPT_INTENT_BYTES,
    KakaoConceptIntent,
)
from eom_catalog_contracts.kakao_question import KakaoQuestionImage
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_kakao_archive_contracts.concepts import ConceptPlanRequest, ConceptQuestion
from eom_kakao_archive_contracts.render import LocalMember
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_workflow.kakao_concept_request import (
    CONCEPT_REQUEST_REF,
    KakaoConceptFile,
    KakaoConceptWork,
    validate_kakao_concept_request_bytes,
)

from .artifacts import CatalogArtifactService
from .kakao_media_publication import inspect_kakao_media
from .kakao_question_editing import validate_question_sources
from .kakao_question_service import ResolvedKakaoQuestions
from .kakao_render_projection import KakaoRenderImageInput, image_pointer_key
from .kakao_study_projection import project_kakao_source_content


def publish_kakao_concept_input(
    artifacts: CatalogArtifactService,
    *,
    task_id: str,
    value: KakaoConceptIntent | ConceptPlanRequest,
    authorize: Callable[[], None],
) -> ArtifactMemberPointer:
    """Only bounded JSON is materialized here; source images remain canonical references."""
    authorize()
    value = type(value).model_validate(value.model_dump(mode="json"))
    intent = isinstance(value, KakaoConceptIntent)
    member, schema, kind, maximum = (
        ("intent.json", CONCEPT_TASK_REF, "intent", MAX_CONCEPT_INTENT_BYTES)
        if intent
        else ("request.json", CONCEPT_REQUEST_REF, "plan", 262144)
    )
    if value.task_id != task_id:
        raise ValueError("KAKAO_CONCEPT_TASK_MISMATCH")
    payload = canonical_json_bytes(value)
    if len(payload) > maximum:
        raise ValueError("KAKAO_CONCEPT_INPUT_TOO_LARGE")
    digest = sha256_bytes(payload)
    with tempfile.TemporaryDirectory(
        prefix="kakao-concept.", dir=artifacts.settings.staging_root
    ) as folder:
        path = Path(folder) / member
        path.write_bytes(payload)
        authorize()
        publication = artifacts.commit_file_set(
            files={member: path},
            primary_file=member,
            artifact_type="kakao-concept-" + kind,
            idempotency_key=f"kakao:concept:{task_id}:{kind}",
            request=dict(task_id=task_id, input_sha256=digest, schema_ref=schema),
            result=dict(input_sha256=digest),
            file_metadata={member: dict(media_type="application/json", schema_ref=schema)},
            expected_file_sha256={member: digest},
        )
    if (publication.content_hash, publication.content_bytes) != (digest, len(payload)):
        raise ValueError("KAKAO_CONCEPT_PUBLICATION_MISMATCH")
    authorize()
    return ArtifactMemberPointer(
        artifact_id=publication.artifact_id,
        artifact_revision_id=publication.revision_id,
        member_path=member,
        schema_ref=schema,
        media_type="application/json",
        sha256=digest,
    )


def prepare_kakao_concept_plan(
    artifacts: CatalogArtifactService,
    *,
    intent: KakaoConceptIntent,
    selected: ResolvedKakaoQuestions,
    authorize: Callable[[], None],
) -> KakaoConceptWork:
    authorize()
    if len(selected.questions) != 1:
        raise ValueError("KAKAO_CONCEPT_QUESTION_SET_INVALID")
    item = selected.questions[0]
    if (
        item.stored.source_binding_id,
        item.stored.room_id,
        item.stored.question_id,
        item.stored.question_revision_id,
        item.stored.manifest,
    ) != (
        intent.request.source_binding_id,
        intent.request.room_id,
        intent.request.question_id,
        intent.request.question_revision_id,
        intent.question_manifest,
    ):
        raise ValueError("KAKAO_CONCEPT_QUESTION_PIN_MISMATCH")
    sources = {
        source.resolved.normalization.normalization_revision_id: source.resolved
        for source in selected.sources
    }
    validate_question_sources(item.published.question, tuple(sources.values()))
    images: dict[tuple[str, ...], KakaoRenderImageInput] = {}
    files: list[KakaoConceptFile] = []
    formats = {"image/png": "png", "image/jpeg": "jpeg", "image/webp": "webp"}
    total = 0
    for block in item.published.question.ordered_blocks:
        if not isinstance(block, KakaoQuestionImage) or block.source_pointer is None:
            continue
        pointer = block.source_pointer
        key = image_pointer_key(pointer)
        if key in images:
            continue
        opened = artifacts.open_verified_member(
            artifact_id=pointer.artifact_id,
            revision_id=pointer.artifact_revision_id,
            member_path=pointer.member_path,
            sha256=pointer.sha256,
            schema_ref=pointer.schema_ref,
            media_type=pointer.media_type,
            max_bytes=64 * 1024 * 1024,
        )
        with opened.stream as stream:
            total += opened.content_length
            if total > 128 * 1024 * 1024 or len(files) >= 60:
                raise ValueError("KAKAO_CONCEPT_IMAGE_INPUT_LIMIT")
            payload = stream.read(opened.content_length + 1)
            if len(payload) != opened.content_length or sha256_bytes(payload) != pointer.sha256:
                raise ValueError("KAKAO_CONCEPT_IMAGE_HASH_MISMATCH")
        observed = inspect_kakao_media(intent.request.source_binding_id, payload)
        if observed.media_type != pointer.media_type:
            raise ValueError("KAKAO_CONCEPT_IMAGE_MEDIA_MISMATCH")
        relative = f"images/photo-{len(files) + 1:04d}." + formats[observed.media_type]
        member = LocalMember(
            relative_path=relative,
            sha256=pointer.sha256,
            size_bytes=observed.source_bytes,
            media_type=observed.media_type,
        )
        images[key] = KakaoRenderImageInput(pointer, member)
        files.append(
            KakaoConceptFile(
                relative_path=relative,
                source=pointer,
                size_bytes=member.size_bytes,
                width_pixels=observed.width_px,
                height_pixels=observed.height_px,
            )
        )
    groups = {
        role: tuple(block for block in item.published.question.ordered_blocks if block.role == role)
        for role in ("student", "staff")
    }
    used: set[tuple[str, ...]] = set()
    request = ConceptPlanRequest(
        task_id=intent.task_id,
        question=ConceptQuestion(
            question_revision_id=item.stored.question_revision_id,
            question_manifest_sha256=item.stored.manifest.sha256,
            student=project_kakao_source_content(groups["student"], sources, images, used),
            staff=project_kakao_source_content(groups["staff"], sources, images, used)
            if groups["staff"]
            else None,
        ),
        base_study_revision_id=intent.request.base_study_revision_id,
        additional_instructions=intent.request.additional_instructions,
    )
    if used != set(images):
        raise ValueError("KAKAO_CONCEPT_IMAGE_SET_MISMATCH")
    pointer = publish_kakao_concept_input(
        artifacts, task_id=intent.task_id, value=request, authorize=authorize
    )
    work = KakaoConceptWork(
        task_id=intent.task_id,
        phase="PLAN",
        source_binding_id=intent.request.source_binding_id,
        question_revision_id=item.stored.question_revision_id,
        question_manifest=item.stored.manifest,
        request_member=pointer,
        request_bytes=len(canonical_json_bytes(request)),
        files=tuple(files),
    )
    validate_kakao_concept_request_bytes(work, canonical_json_bytes(request))
    authorize()
    return work
