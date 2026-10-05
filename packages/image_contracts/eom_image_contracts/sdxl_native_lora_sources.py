"""Pure, metadata-only closure and multi-batch source admission for native SDXL training."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TypeVar, cast

from eom_image_contracts.models import (
    FrozenModel,
    ImageEvaluationArtifactMember,
    content_json_bytes,
)
from eom_image_contracts.science_corpus_visual import LocalImageScienceCorpusTrainingAuthorization
from eom_image_contracts.sdxl_native_lora import LocalImageSdxlNativeLoraCommand
from eom_image_contracts.sdxl_native_training_targets import (
    SDXL_NATIVE_TARGET_COMMAND_SCHEMA_REF,
    SDXL_NATIVE_TARGET_RESULT_SCHEMA_REF,
    LocalImageSdxlNativeTrainingTargetCommand,
    LocalImageSdxlNativeTrainingTargetResult,
    SdxlNativeTrainingTargetSources,
    SdxlPreparedNativeTrainingTarget,
    validate_sdxl_native_training_target_command_sources,
    validate_sdxl_native_training_target_result,
    validate_sdxl_native_training_target_sources,
)
from eom_image_contracts.sdxl_training_targets import _source_document
from eom_image_contracts.source_page_crops import (
    SOURCE_PAGE_CROP_REVIEW_SCHEMA_REF,
    SOURCE_PAGE_CROP_REVIEW_V2_SCHEMA_REF,
    SOURCE_PAGE_CROP_REVIEW_V3_SCHEMA_REF,
    LocalImageScienceSourcePageCropReview,
    LocalImageScienceSourcePageCropReviewV2,
    LocalImageScienceSourcePageCropReviewV3,
    ScienceSourcePageCropRegion,
    SourcePageCropReview,
    parse_source_page_crop_review,
)
from eom_image_contracts.source_pdf_crops import (
    SOURCE_PDF_CROP_COMMAND_SCHEMA_REF,
    SOURCE_PDF_CROP_SET_SCHEMA_REF,
    LocalImageScienceSourcePdfCropCommand,
    LocalImageScienceSourcePdfCropSet,
)
from eom_image_contracts.validation import validate_contract

NATIVE_LORA_MAX_METADATA_BYTES = 2 * 1024**2
NATIVE_LORA_MAX_METADATA_TOTAL_BYTES = 32 * 1024**2
_AUTH_SCHEMA = "eom://schemas/image-provider/local-image-science-corpus-training-authorization/1.0"
_SCREEN_SCHEMA = "eom://schemas/operations/plain-text-log/1.0"
_REVIEW_SCHEMAS = frozenset(
    {
        SOURCE_PAGE_CROP_REVIEW_SCHEMA_REF,
        SOURCE_PAGE_CROP_REVIEW_V2_SCHEMA_REF,
        SOURCE_PAGE_CROP_REVIEW_V3_SCHEMA_REF,
    }
)
_REVIEW_MODELS = (
    LocalImageScienceSourcePageCropReview,
    LocalImageScienceSourcePageCropReviewV2,
    LocalImageScienceSourcePageCropReviewV3,
)
# A closed business dependency graph, not an extensible parser/plugin registry.
_JSON_DOCUMENTS: Mapping[str, tuple[str, str, type[FrozenModel]]] = MappingProxyType(
    {
        SDXL_NATIVE_TARGET_COMMAND_SCHEMA_REF: (
            "sdxl-training-target-command-v3",
            "sdxl-training-target-command",
            LocalImageSdxlNativeTrainingTargetCommand,
        ),
        SDXL_NATIVE_TARGET_RESULT_SCHEMA_REF: (
            "sdxl-training-target-result-v3",
            "sdxl-training-target-result",
            LocalImageSdxlNativeTrainingTargetResult,
        ),
        SOURCE_PDF_CROP_SET_SCHEMA_REF: (
            "science-source-pdf-crop-set",
            "science-source-pdf-crop-set",
            LocalImageScienceSourcePdfCropSet,
        ),
        SOURCE_PDF_CROP_COMMAND_SCHEMA_REF: (
            "science-source-pdf-crop-command",
            "science-source-pdf-crop-command",
            LocalImageScienceSourcePdfCropCommand,
        ),
        _AUTH_SCHEMA: (
            "science-corpus-training-authorization",
            "science-corpus-training-authorization",
            LocalImageScienceCorpusTrainingAuthorization,
        ),
    }
)
NativeLoraMetadataValue = (
    LocalImageSdxlNativeTrainingTargetCommand
    | LocalImageSdxlNativeTrainingTargetResult
    | LocalImageScienceSourcePdfCropSet
    | LocalImageScienceSourcePdfCropCommand
    | SourcePageCropReview
    | LocalImageScienceCorpusTrainingAuthorization
    | str
)
_Document = TypeVar("_Document", bound=FrozenModel)


def sdxl_native_lora_metadata_member_path(pointer: ImageEvaluationArtifactMember) -> str:
    """One explicit materialization per full immutable pointer, including role/hash."""
    identity = hashlib.sha256(content_json_bytes(pointer.model_dump(mode="json"))).hexdigest()
    return f"inputs/metadata/{identity}.{'txt' if pointer.schema_ref == _SCREEN_SCHEMA else 'json'}"


def _decode_metadata(pointer: ImageEvaluationArtifactMember, raw: bytes) -> NativeLoraMetadataValue:
    if not 0 < len(raw) <= NATIVE_LORA_MAX_METADATA_BYTES:
        raise ValueError("SDXL_NATIVE_LORA_METADATA_SIZE_INVALID")
    if pointer.schema_ref in _REVIEW_SCHEMAS:
        return parse_source_page_crop_review(pointer, raw)
    if pointer.schema_ref == _SCREEN_SCHEMA:
        if (
            pointer.media_type != "text/plain"
            or not pointer.member_path.startswith("reports/")
            or "sha256:" + hashlib.sha256(raw).hexdigest() != pointer.sha256
        ):
            raise ValueError("SDXL_NATIVE_LORA_SCREENING_POINTER_INVALID")
        text = raw.decode("utf-8")
        if not text.strip() or "\x00" in text:
            raise ValueError("SDXL_NATIVE_LORA_SCREENING_TEXT_INVALID")
        return text
    specification = _JSON_DOCUMENTS.get(pointer.schema_ref)
    if specification is None:
        raise ValueError("SDXL_NATIVE_LORA_METADATA_SCHEMA_UNSUPPORTED")
    contract, family, model = specification
    if (
        pointer.media_type != "application/json"
        or pointer.member_path != f"manifests/{family}.json"
    ):
        raise ValueError("SDXL_NATIVE_LORA_METADATA_POINTER_INVALID")
    value = _source_document(pointer, raw, contract, model)
    # Native successor metadata has never allowed historical newline normalization.
    if pointer.schema_ref != _AUTH_SCHEMA and raw != content_json_bytes(
        value.model_dump(mode="json")
    ):
        raise ValueError("SDXL_NATIVE_LORA_METADATA_NONCANONICAL")
    return cast(NativeLoraMetadataValue, value)


def _dependencies(value: NativeLoraMetadataValue) -> tuple[ImageEvaluationArtifactMember, ...]:
    if isinstance(value, LocalImageSdxlNativeTrainingTargetCommand):
        return (value.source_crop_set, value.training_authorization)
    if isinstance(value, LocalImageScienceSourcePdfCropSet):
        return (value.command,)
    if isinstance(value, LocalImageScienceSourcePdfCropCommand):
        return (value.source_review,)
    if isinstance(value, _REVIEW_MODELS):
        return (value.training_authorization,)
    return ()


@dataclass(frozen=True, slots=True)
class SdxlNativeLoraBatchSources:
    command: LocalImageSdxlNativeTrainingTargetCommand
    result: LocalImageSdxlNativeTrainingTargetResult
    sources: SdxlNativeTrainingTargetSources


@dataclass(frozen=True, slots=True)
class SdxlNativeLoraSources:
    metadata_pointers: tuple[ImageEvaluationArtifactMember, ...]
    batches: tuple[SdxlNativeLoraBatchSources, ...]
    targets: tuple[SdxlPreparedNativeTrainingTarget, ...]
    regions: tuple[ScienceSourcePageCropRegion, ...]


class SdxlNativeLoraMetadataAdmission:
    """Per-call bounded parser state, shared by canonical admission and local validation."""

    def __init__(self, command: LocalImageSdxlNativeLoraCommand) -> None:
        validate_contract("sdxl-native-lora-command", command.model_dump(mode="json"))
        self.command = LocalImageSdxlNativeLoraCommand.model_validate(
            command.model_dump(mode="json")
        )
        self._documents: dict[ImageEvaluationArtifactMember, NativeLoraMetadataValue] = {}
        self._required: set[ImageEvaluationArtifactMember] = set()
        self._locations: dict[tuple[str, str, str], ImageEvaluationArtifactMember] = {}
        self._total_bytes = 0
        for pointer in (
            command.training_authorization,
            command.screening_evidence,
            *(p for batch in command.target_batches for p in (batch.command, batch.result)),
        ):
            self._require(pointer)

    def _require(self, pointer: ImageEvaluationArtifactMember) -> None:
        location = (pointer.artifact_id, pointer.artifact_revision_id, pointer.member_path)
        if self._locations.setdefault(location, pointer) != pointer:
            raise ValueError("SDXL_NATIVE_LORA_CONFLICTING_IMMUTABLE_POINTERS")
        self._required.add(pointer)

    def pending_pointers(self) -> tuple[ImageEvaluationArtifactMember, ...]:
        return tuple(
            sorted(
                self._required - self._documents.keys(), key=sdxl_native_lora_metadata_member_path
            )
        )

    def admit(self, pointer: ImageEvaluationArtifactMember, raw: bytes) -> None:
        if pointer not in self._required or pointer in self._documents:
            raise ValueError("SDXL_NATIVE_LORA_UNREQUESTED_OR_REPEATED_METADATA")
        if self._total_bytes + len(raw) > NATIVE_LORA_MAX_METADATA_TOTAL_BYTES:
            raise ValueError("SDXL_NATIVE_LORA_METADATA_TOTAL_BUDGET_EXCEEDED")
        document = _decode_metadata(pointer, raw)
        for child in _dependencies(document):
            self._require(child)
        self._documents[pointer] = document
        self._total_bytes += len(raw)

    def _document(
        self, pointer: ImageEvaluationArtifactMember, model: type[_Document]
    ) -> _Document:
        value = self._documents.get(pointer)
        if not isinstance(value, model):
            raise ValueError("SDXL_NATIVE_LORA_METADATA_DOCUMENT_MISSING")
        return value

    def validated_sources(self) -> SdxlNativeLoraSources:
        if self.pending_pointers():
            raise ValueError("SDXL_NATIVE_LORA_METADATA_CLOSURE_INCOMPLETE")
        command = self.command
        authorization = self._document(
            command.training_authorization, LocalImageScienceCorpusTrainingAuthorization
        )
        if authorization.approved_at > command.reviewed_at:
            raise ValueError("SDXL_NATIVE_LORA_SOURCE_APPROVAL_CHRONOLOGY_INVALID")
        batches = []
        snapshots: dict[ImageEvaluationArtifactMember, SdxlNativeTrainingTargetSources] = {}
        prepared = {}
        common_basis = None
        for pin in command.target_batches:
            target_command = self._document(pin.command, LocalImageSdxlNativeTrainingTargetCommand)
            target_result = self._document(pin.result, LocalImageSdxlNativeTrainingTargetResult)
            if (
                target_command.training_authorization != command.training_authorization
                or target_result.status != "SUCCEEDED"
                or target_result.completed_at > command.reviewed_at
            ):
                raise ValueError("SDXL_NATIVE_LORA_BATCH_SCOPE_OR_REVIEW_CHRONOLOGY_INVALID")
            sources = snapshots.get(target_command.source_crop_set)
            if sources is None:
                crop_set = self._document(
                    target_command.source_crop_set, LocalImageScienceSourcePdfCropSet
                )
                source_command = self._document(
                    crop_set.command, LocalImageScienceSourcePdfCropCommand
                )
                review = self._documents.get(source_command.source_review)
                if not isinstance(review, _REVIEW_MODELS):
                    raise ValueError("SDXL_NATIVE_LORA_REVIEW_MISSING")
                sources = validate_sdxl_native_training_target_sources(
                    target_command,
                    crop_set=crop_set,
                    source_command=source_command,
                    review=review,
                    authorization=authorization,
                )
                snapshots[target_command.source_crop_set] = sources
            else:
                validate_sdxl_native_training_target_command_sources(target_command, sources)
            if common_basis is None:
                common_basis = sources.review.basis_crop_set
            elif sources.review.basis_crop_set != common_basis:
                raise ValueError("SDXL_NATIVE_LORA_FROZEN_BASIS_MISMATCH")
            validate_sdxl_native_training_target_result(target_command, sources, target_result)
            regions = {r.selection_id: r for r in sources.review.selections}
            decisions = {d.sample_id: d for d in target_command.decisions}
            for target in target_result.prepared_targets:
                key = (pin.result.artifact_id, pin.result.artifact_revision_id, target.sample_id)
                prepared[key] = (target, regions[target.sample_id], decisions[target.sample_id])
            batches.append(SdxlNativeLoraBatchSources(target_command, target_result, sources))
        targets, selected_regions = [], []
        for sample in command.training_samples:
            key = (
                sample.source_image.artifact_id,
                sample.source_image.artifact_revision_id,
                sample.sample_id,
            )
            found = prepared.get(key)
            if found is None:
                raise ValueError("SDXL_NATIVE_LORA_SELECTED_TARGET_MISSING")
            target, region, decision = found
            if (
                target.target_id != sample.target_id
                or target.target_revision_id != sample.target_revision_id
                or target.sha256 != sample.source_image.sha256
                or target.placement.canvas != sample.canvas
                or region.document_id != sample.source_document_id
                or region.exam_group_sha256 != sample.exam_group_sha256
                or region.partition != "TRAIN"
                or decision.disposition != "PREPARE"
                or decision.expression != sample.conditioning.expression
            ):
                raise ValueError("SDXL_NATIVE_LORA_SELECTED_TARGET_SOURCE_OR_RECIPE_INVALID")
            targets.append(target)
            selected_regions.append(region)
        if sum(t.size_bytes for t in targets) > command.budget.maximum_input_png_bytes:
            raise ValueError("SDXL_NATIVE_LORA_INPUT_PNG_BUDGET_EXCEEDED")
        _validate_physical_sources(tuple(selected_regions))
        return SdxlNativeLoraSources(
            tuple(sorted(self._required, key=sdxl_native_lora_metadata_member_path)),
            tuple(batches),
            tuple(targets),
            tuple(selected_regions),
        )


def _validate_physical_sources(regions: tuple[ScienceSourcePageCropRegion, ...]) -> None:
    by_pdf: dict[str, tuple[str, ImageEvaluationArtifactMember]] = {}
    by_document: dict[str, ImageEvaluationArtifactMember] = {}
    frames: dict[tuple[str, int], list[ScienceSourcePageCropRegion]] = {}
    for region in regions:
        pointer = region.source_document
        if (
            by_pdf.setdefault(pointer.sha256, (region.document_id, pointer))
            != (region.document_id, pointer)
            or by_document.setdefault(region.document_id, pointer) != pointer
        ):
            raise ValueError("SDXL_NATIVE_LORA_SOURCE_PDF_ALIAS_OR_POINTER_CONFLICT")
        key = (pointer.sha256, region.physical_page)
        prior_frames = frames.setdefault(key, [])
        # The command already caps every declared PDF at3; this is constant per bucket.
        for prior in prior_frames:
            if region.source_page != prior.source_page:
                raise ValueError("SDXL_NATIVE_LORA_SOURCE_PAGE_POINTER_CONFLICT")
            left, top, right, bottom = region.pixel_box
            pleft, ptop, pright, pbottom = prior.pixel_box
            intersection = max(0, min(right, pright) - max(left, pleft)) * max(
                0, min(bottom, pbottom) - max(top, ptop)
            )
            smaller = min((right - left) * (bottom - top), (pright - pleft) * (pbottom - ptop))
            if intersection * 1000 >= smaller * 800:
                raise ValueError("SDXL_NATIVE_LORA_PHYSICAL_SOURCE_VARIANT_REUSED")
        prior_frames.append(region)


def parse_sdxl_native_lora_sources(
    command: LocalImageSdxlNativeLoraCommand, metadata: Mapping[str, bytes]
) -> SdxlNativeLoraSources:
    """The staged worker uses the same pure rule and must supply exactly the metadata closure."""
    admission = SdxlNativeLoraMetadataAdmission(command)
    observed = set()
    while pending := admission.pending_pointers():
        for pointer in pending:
            path = sdxl_native_lora_metadata_member_path(pointer)
            raw = metadata.get(path)
            if raw is None:
                raise ValueError("SDXL_NATIVE_LORA_METADATA_MEMBER_MISSING")
            admission.admit(pointer, raw)
            observed.add(path)
    if observed != metadata.keys():
        raise ValueError("SDXL_NATIVE_LORA_METADATA_FOREIGN_MEMBER")
    return admission.validated_sources()
