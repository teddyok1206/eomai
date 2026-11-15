"""Read a score from the exact question Artifact; never choose a source or publish bytes."""

import re
from collections.abc import Callable
from zipfile import ZIP_DEFLATED, ZIP_STORED, BadZipFile, ZipFile

from eom_catalog_contracts.material_native_files import MaterialNativeFileBinding
from eom_catalog_contracts.source_score import (
    PrintedSourceScoreV2,
    SourceScoreV2,
    require_source_score_matches,
)
from eom_hwpx_contracts.native_item_score import (
    NativePrintedScore,
    NativePrintedScoreObservation,
    observe_native_printed_score,
)

from eom_catalog_service.artifacts import CatalogArtifactService

_SECTION = re.compile(r"Contents/section[0-9]+\.xml\Z")
_MAX_DOCUMENT = 32 * 1024 * 1024
_MAX_SECTION = 16 * 1024 * 1024
_MAX_XML_TOTAL = 32 * 1024 * 1024


def read_native_question_score(
    artifacts: CatalogArtifactService,
    question: MaterialNativeFileBinding,
    *,
    authorize: Callable[[], None],
) -> NativePrintedScoreObservation:
    """Resolve once at preparation/registration, not on each status poll.

    The caller has already resolved this binding's original source and split
    receipt. Catalog's descriptor owner enforces exact schema/media/hash/lifecycle;
    this adapter bounds ZIP/XML reads without copying or extracting the package.
    """
    question = MaterialNativeFileBinding.model_validate(question.model_dump(mode="json"))
    if question.source_role != "MAIN":
        raise ValueError("MATERIAL_NATIVE_SCORE_QUESTION_REQUIRED")
    pointer = question.document
    if pointer.bytes > _MAX_DOCUMENT:
        raise ValueError("MATERIAL_NATIVE_SCORE_DOCUMENT_LIMIT")
    authorize()
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
        if opened.content_length != pointer.bytes:
            raise ValueError("MATERIAL_NATIVE_DOCUMENT_IDENTITY_MISMATCH")
        with ZipFile(opened.stream) as archive:
            members = archive.infolist()
            if not 1 <= len(members) <= 2048 or len({part.filename for part in members}) != len(
                members
            ):
                raise ValueError("MATERIAL_NATIVE_SCORE_PACKAGE_INVALID")
            sections = tuple(part for part in members if _SECTION.fullmatch(part.filename))
            if not 1 <= len(sections) <= 32:
                raise ValueError("MATERIAL_NATIVE_SCORE_PACKAGE_INVALID")
            if (
                any(
                    part.flag_bits & 1
                    or part.compress_type not in {ZIP_STORED, ZIP_DEFLATED}
                    or not 1 <= part.file_size <= _MAX_SECTION
                    for part in sections
                )
                or sum(part.file_size for part in sections) > _MAX_XML_TOTAL
            ):
                raise ValueError("MATERIAL_NATIVE_SCORE_PACKAGE_LIMIT")
            candidates: list[NativePrintedScore] = []
            for part in sections:
                with archive.open(part) as stream:
                    raw = stream.read(_MAX_SECTION + 1)
                if len(raw) != part.file_size:
                    raise ValueError("MATERIAL_NATIVE_SCORE_PACKAGE_INVALID")
                candidates.extend(observe_native_printed_score(raw).candidates)
                if len(candidates) > 64:
                    raise ValueError("NATIVE_ITEM_SCORE_CANDIDATE_LIMIT")
    except BadZipFile as error:
        raise ValueError("MATERIAL_NATIVE_SCORE_PACKAGE_INVALID") from error
    finally:
        opened.stream.close()
    authorize()
    return NativePrintedScoreObservation(tuple(candidates))


def expected_native_source_score(
    observation: NativePrintedScoreObservation,
) -> PrintedSourceScoreV2:
    """Absence/ambiguity is not UNPRINTED; unsupported precision is not rounded."""
    if observation.state != "MATCHED":
        raise ValueError("MATERIAL_NATIVE_SCORE_" + observation.state)
    points = observation.candidates[0].points
    value = int(points) if points == points.to_integral_value() else format(points.normalize(), "f")
    try:
        return PrintedSourceScoreV2(state="PRINTED", points=value)
    except ValueError as error:
        raise ValueError("MATERIAL_NATIVE_SCORE_UNSUPPORTED") from error


def require_native_source_score(
    observation: NativePrintedScoreObservation, proposed: SourceScoreV2
) -> None:
    expected = expected_native_source_score(observation)
    try:
        require_source_score_matches(expected, proposed)
    except ValueError as error:
        raise ValueError("MATERIAL_NATIVE_SCORE_MISMATCH") from error
