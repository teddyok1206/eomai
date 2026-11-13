"""Resolve native intake evidence at existing Catalog Artifact/authorization boundaries.

Full native file validation is an explicit intake/registration action, never a status poll.
The protected native producer owns source-range preservation; these checks bind its
committed receipts, exact file bytes and original workbook to the actual operator.
"""

from __future__ import annotations

from collections.abc import Callable

from eom_catalog_contracts.material_learning import MaterialArtifactMember
from eom_catalog_contracts.material_learning_intake import MaterialLearningSourceSelection
from eom_catalog_contracts.material_native_files import (
    MaterialNativeItemBinding,
    require_material_native_split_result,
)
from eom_catalog_contracts.material_native_intake import (
    MATERIAL_NATIVE_BUNDLE_REF,
    MaterialNativeExamBundle,
    MaterialNativeExamItem,
    require_native_exam_bundle_sources,
    require_native_exam_bundle_workbook,
)
from eom_catalog_contracts.native_exam_intake import NativeExamWorkbookDocument
from eom_hwpx_contracts.native_item_split import NativeItemSplitResult
from eom_identifiers import sha256_bytes

from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.native_exam_workbook import read_native_exam_workbook

_MAX_METADATA = 4 * 1024 * 1024
_MAX_WORKBOOK = 8 * 1024 * 1024


def _read_exact(
    artifacts: CatalogArtifactService, pointer: MaterialArtifactMember, *, maximum: int
) -> bytes:
    if not 1 <= pointer.bytes <= maximum:
        raise ValueError("MATERIAL_NATIVE_ARTIFACT_SIZE_INVALID")
    payload = artifacts.read_member(
        artifact_id=pointer.artifact_id,
        revision_id=pointer.artifact_revision_id,
        member_path=pointer.member_path,
        schema_ref=pointer.schema_ref,
        media_type=pointer.media_type,
        sha256=pointer.sha256,
        max_bytes=pointer.bytes,
    )
    if len(payload) != pointer.bytes or sha256_bytes(payload) != pointer.sha256:
        raise ValueError("MATERIAL_NATIVE_ARTIFACT_IDENTITY_MISMATCH")
    return payload


def read_material_native_bundle(
    artifacts: CatalogArtifactService,
    pointer: MaterialArtifactMember,
    *,
    sources: tuple[MaterialLearningSourceSelection, ...],
    operator_id: str,
    authorize: Callable[[], None],
) -> MaterialNativeExamBundle:
    """Read small metadata only, with original source/upload ownership preserved."""
    authorize()
    if pointer.schema_ref != MATERIAL_NATIVE_BUNDLE_REF or pointer.media_type != "application/json":
        raise ValueError("MATERIAL_NATIVE_BUNDLE_POINTER_INVALID")
    bundle = MaterialNativeExamBundle.model_validate_json(
        _read_exact(artifacts, pointer, maximum=_MAX_METADATA)
    )
    require_native_exam_bundle_sources(bundle, sources, operator_id=operator_id)
    authorize()
    return bundle


def verify_material_native_bundle_files(
    artifacts: CatalogArtifactService,
    bundle: MaterialNativeExamBundle,
    *,
    authorize: Callable[[], None],
) -> None:
    """Verify one exam once at intake, not every question or progress refresh.

    The XLSX is actually decoded again rather than trusting model/caller-supplied row data.
    Each native member is streamed through its canonical Artifact descriptor and closed.
    No large document is returned to another component or duplicated in a DB value.
    """
    authorize()
    workbook_source = bundle.workbook
    supplied = NativeExamWorkbookDocument.model_validate_json(
        _read_exact(artifacts, workbook_source.parsed_workbook, maximum=_MAX_METADATA)
    )
    original = _read_exact(artifacts, workbook_source.workbook, maximum=_MAX_WORKBOOK)
    actual = read_native_exam_workbook(original, source_sha256=workbook_source.workbook.sha256)
    if actual != supplied:
        raise ValueError("MATERIAL_NATIVE_WORKBOOK_OBSERVATION_MISMATCH")
    require_native_exam_bundle_workbook(bundle, actual)
    for item in bundle.items:
        verify_material_native_item_files(artifacts, item, authorize=authorize)
    authorize()


def verify_material_native_item_files(
    artifacts: CatalogArtifactService,
    item: MaterialNativeExamItem | MaterialNativeItemBinding,
    *,
    authorize: Callable[[], None],
) -> None:
    """Registration verifies only its two pinned files, never rescans the whole exam/XLSX."""
    for file in (item.question, item.solution):
        authorize()
        result = NativeItemSplitResult.model_validate_json(
            _read_exact(artifacts, file.split_evidence, maximum=_MAX_METADATA)
        )
        require_material_native_split_result(file, result, item_number=item.item_number)
        pointer = file.document
        opened = artifacts.open_verified_member(
            artifact_id=pointer.artifact_id,
            revision_id=pointer.artifact_revision_id,
            member_path=pointer.member_path,
            schema_ref=pointer.schema_ref,
            media_type=pointer.media_type,
            sha256=pointer.sha256,
            max_bytes=pointer.bytes,
        )
        try:
            if opened.content_length != pointer.bytes or opened.stream.read(4) != b"PK\x03\x04":
                raise ValueError("MATERIAL_NATIVE_DOCUMENT_IDENTITY_MISMATCH")
        finally:
            opened.stream.close()
    authorize()
