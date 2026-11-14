"""Pure native BODY-use matching; Catalog owns file verification and authorization.

The fixed extractor must produce both catalogs from the exact verified sources.
Whole raster pixels identify a member across HWP/HWPX containers; the rendered
view additionally binds its viewport and orientation. Neither a member inventory
nor this small scope is permission to register an image.
"""

from __future__ import annotations

from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_image_contracts.office_embedded_images import OfficeEmbeddedImage
from eom_image_contracts.office_picture_uses import OfficePictureUseCatalog, OfficePictureView

from eom_catalog_contracts.material_native_files import MaterialNativeFileBinding
from eom_catalog_contracts.material_native_visual_preparation import (
    MaterialNativeQuestionVisualScope,
)
from eom_catalog_contracts.office_item_learning import OfficeVisualBindings

_ViewIdentity = tuple[str, int, int, str, int, int]


def _view_identity(image: OfficeEmbeddedImage, view: OfficePictureView) -> _ViewIdentity:
    return (
        image.pixel_sha256,
        image.width_px,
        image.height_px,
        view.sha256,
        view.width_px,
        view.height_px,
    )


def _require_catalog(catalog: OfficePictureUseCatalog, *, question: bool) -> None:
    # Recheck even typed values: model_copy/model_construct can skip validators.
    views = {view.use_id: view for view in catalog.rendered_uses}
    if len(views) != len(catalog.rendered_uses):
        raise ValueError("MATERIAL_NATIVE_VISUAL_CATALOG_INVALID")
    if question:
        images = {image.source_member for image in catalog.embedded_images.images}
        if any(
            use.unresolved_reasons
            or use.geometry is None
            or use.source_member not in images
            or use.use_id not in views
            for use in catalog.picture_uses
        ):
            raise ValueError("MATERIAL_NATIVE_VISUAL_QUESTION_USE_UNRESOLVED")
    try:
        OfficePictureUseCatalog.model_validate(catalog.model_dump(mode="json"))
    except ValueError as error:
        raise ValueError("MATERIAL_NATIVE_VISUAL_CATALOG_INVALID") from error


def build_material_native_question_visual_scope(
    file: MaterialNativeFileBinding,
    *,
    item_number: int,
    source_catalog: OfficePictureUseCatalog,
    source_catalog_sha256: str,
    question_catalog: OfficePictureUseCatalog,
) -> MaterialNativeQuestionVisualScope:
    """Match each actual fragment BODY use to one original-source use, or fail.

    This bounded map is O(source uses + question uses), not a service/global cache.
    Unreferenced embedded members never create candidates or allowed uses.
    """
    if file.source_role != "MAIN":
        raise ValueError("MATERIAL_NATIVE_VISUAL_QUESTION_FILE_REQUIRED")
    if (
        source_catalog.embedded_images.source_sha256 != file.original_source_sha256
        or sha256_bytes(canonical_json_bytes(source_catalog.model_dump(mode="json")))
        != source_catalog_sha256
    ):
        raise ValueError("MATERIAL_NATIVE_VISUAL_SOURCE_CATALOG_MISMATCH")
    if (
        question_catalog.embedded_images.source_sha256 != file.document.sha256
        or question_catalog.embedded_images.source_format != "HWPX"
    ):
        raise ValueError("MATERIAL_NATIVE_VISUAL_QUESTION_CATALOG_MISMATCH")
    _require_catalog(source_catalog, question=False)
    _require_catalog(question_catalog, question=True)
    source_images = {image.source_member: image for image in source_catalog.embedded_images.images}
    source_views = {view.use_id: view for view in source_catalog.rendered_uses}
    candidates: dict[_ViewIdentity, list[str]] = {}
    for use in source_catalog.picture_uses:
        if use.unresolved_reasons:
            continue
        # A validated resolved catalog closes these two lookups over the use.
        assert use.source_member is not None
        key = _view_identity(source_images[use.source_member], source_views[use.use_id])
        candidates.setdefault(key, []).append(use.use_id)
    question_images = {
        image.source_member: image for image in question_catalog.embedded_images.images
    }
    question_views = {view.use_id: view for view in question_catalog.rendered_uses}
    allowed: set[str] = set()
    for use in question_catalog.picture_uses:
        assert use.source_member is not None
        key = _view_identity(question_images[use.source_member], question_views[use.use_id])
        matches = candidates.get(key, ())
        if not matches:
            raise ValueError("MATERIAL_NATIVE_VISUAL_SOURCE_USE_NOT_FOUND")
        if len(matches) != 1:
            raise ValueError("MATERIAL_NATIVE_VISUAL_SOURCE_USE_AMBIGUOUS")
        allowed.add(matches[0])
    if len(allowed) > 64:
        raise ValueError("MATERIAL_NATIVE_VISUAL_QUESTION_USE_LIMIT")
    return MaterialNativeQuestionVisualScope(
        item_number=item_number,
        question_document=file.document,
        split_evidence=file.split_evidence,
        source_catalog_sha256=source_catalog_sha256,
        allowed_picture_use_ids=tuple(sorted(allowed)),
    )


def validate_material_native_visual_bindings(
    selection: OfficeVisualBindings, *, scope: MaterialNativeQuestionVisualScope
) -> None:
    """Add question locality only; the existing validator still owns full block closure."""
    if selection.office_catalog_sha256 != scope.source_catalog_sha256:
        raise ValueError("MATERIAL_NATIVE_VISUAL_SELECTION_CATALOG_MISMATCH")
    allowed = frozenset(scope.allowed_picture_use_ids)
    if any(binding.picture_use_id not in allowed for binding in selection.bindings):
        raise ValueError("MATERIAL_NATIVE_VISUAL_SELECTION_OUT_OF_SCOPE")


def material_native_visual_guidance(scope: MaterialNativeQuestionVisualScope) -> str:
    """Deterministic scope hints, not source authorization or a select-all instruction."""
    question = scope.question_document
    evidence = scope.split_evidence
    identifiers = "\n".join(scope.allowed_picture_use_ids) or "(없음)"
    guidance = (
        "\n\n[Native 문항 그림 선택 범위]\n"
        f"문항 번호: {scope.item_number}\n"
        f"문항 Artifact: {question.artifact_id}/{question.artifact_revision_id}\n"
        f"문항 HWPX SHA-256: {question.sha256}\n"
        f"분할 근거 Artifact: {evidence.artifact_id}/{evidence.artifact_revision_id}\n"
        f"분할 근거 SHA-256: {evidence.sha256}\n"
        f"Office catalog SHA-256: {scope.source_catalog_sha256}\n"
        "허용된 picture_use_id:\n"
        f"{identifiers}\n"
        "source_image를 선택할 때에는 위 ID 범위 안에서 실제 본문에 필요한 사용 개체만 "
        "고르세요. 허용된 그림을 모두 포함하라는 뜻은 아닙니다. 제목 장식·다른 문항·참고·"
        "해설 사용 개체를 대신 선택하지 마세요. 원 viewport·방향·축·단위·표기를 확인하고 "
        "기존 block/binding 규칙을 지키세요. 필요한 그림을 충실하게 표현할 수 없으면 "
        "미해결 상태를 명시하고 임의의 그림이나 PDF crop으로 대체하지 마세요. "
        "이 목록은 선택 안내이며 권한이나 검증 완료를 뜻하지 않습니다."
    )
    if len(guidance.encode("utf-8")) > 8000:
        raise ValueError("MATERIAL_NATIVE_VISUAL_GUIDANCE_TOO_LARGE")
    return guidance
