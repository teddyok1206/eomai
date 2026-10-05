"""Reserved source authority, separate from a frozen TRAIN numerical configuration."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Literal, Self, TypeVar

from pydantic import Field, field_validator, model_validator

from eom_image_contracts.models import (
    FrozenModel,
    ImageEvaluationArtifactMember,
    LocalImageRuntime,
    Sha256,
    content_json_bytes,
    content_sha256,
)
from eom_image_contracts.sdxl_canny_reference import (
    LocalImageSdxlCannyReferenceCommand,
    SdxlCannyReferenceSources,
    SdxlCannyReferenceTrace,
    validate_sdxl_canny_reference_sources,
)
from eom_image_contracts.sdxl_learned_comparison import (
    LEARNED_COMPARISON_ARMS,
    SdxlLearnedComparisonBudget,
    SdxlLearnedComparisonOutput,
)
from eom_image_contracts.sdxl_lineart_probe import SdxlLineartProbeCase, SdxlProbeErrorCode
from eom_image_contracts.sdxl_lora_micro import LocalImageSdxlLoraMicroAdapterManifest
from eom_image_contracts.sdxl_native_canny_reference import (
    LocalImageSdxlNativeCannyReferenceCommandV2,
    SdxlNativeCannyReferenceSources,
    parse_reference_sources,
)
from eom_image_contracts.sdxl_native_lora import LocalImageSdxlNativeLoraAdapterManifest
from eom_image_contracts.sdxl_native_lora_sources import (
    SdxlNativeLoraSources,
    parse_sdxl_native_lora_sources,
)
from eom_image_contracts.sdxl_reviewed_micro import LocalImageSdxlReviewedMicroCommand
from eom_image_contracts.source_page_crops import (
    SOURCE_PAGE_CROP_REVIEW_V3_SCHEMA_REF,
    SOURCE_PAGE_CROP_SET_V3_SCHEMA_REF,
    LocalImageScienceSourcePageCropReview,
    LocalImageScienceSourcePageCropReviewV2,
    LocalImageScienceSourcePageCropReviewV3,
    LocalImageScienceSourcePageCropSet,
    LocalImageScienceSourcePageCropSetV2,
    LocalImageScienceSourcePageCropSetV3,
    ScienceSourcePageCropMember,
    ScienceSourcePageCropRegion,
    ScienceSourcePageRegionSelection,
    source_page_crop_pointer,
    validate_source_page_crop_set,
)

_PREFIX = "eom://schemas/image-provider/local-image-"
_Document = TypeVar("_Document", bound=FrozenModel)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("reserved comparison timestamp must use UTC")
    return value


def _document(  # noqa: UP047 -- installed numerical runtime is Python 3.11
    pointer: ImageEvaluationArtifactMember,
    raw: bytes,
    schema: str,
    model: type[_Document],
) -> _Document:
    from eom_image_contracts.validation import validate_contract

    if not 0 < len(raw) <= 2 * 1024**2 or (
        "sha256:" + hashlib.sha256(raw).hexdigest() != pointer.sha256
    ):
        raise ValueError("reserved comparison metadata bound/hash mismatch")
    validate_contract(schema, json.loads(raw))
    parsed = model.model_validate_json(raw)
    if content_json_bytes(parsed.model_dump(mode="json")) != raw:
        raise ValueError("reserved comparison metadata is noncanonical")
    return parsed


class SdxlValidationCropSourcePin(FrozenModel):
    review: ImageEvaluationArtifactMember
    crop_set: ImageEvaluationArtifactMember

    @model_validator(mode="after")
    def exact_source_family(self) -> Self:
        for pointer, schema, member in (
            (self.review, SOURCE_PAGE_CROP_REVIEW_V3_SCHEMA_REF, "science-source-page-crop-review"),
            (self.crop_set, SOURCE_PAGE_CROP_SET_V3_SCHEMA_REF, "science-source-page-crop-set"),
        ):
            if (
                pointer.schema_ref != schema
                or pointer.member_path != "manifests/" + member + ".json"
                or pointer.media_type != "application/json"
            ):
                raise ValueError("reserved comparison requires explicit original-page V3 sources")
        return self


class SdxlValidationComparisonCase(FrozenModel):
    source_set_sha256: Sha256
    selection_id: str = Field(pattern=r"^imgsourcecrop_[0-9a-f]{32}$")
    case: SdxlLineartProbeCase


class SdxlValidationComparisonBudget(SdxlLearnedComparisonBudget):
    maximum_outputs: Literal[32] = 32


class LocalImageSdxlValidationComparisonCommand(FrozenModel):
    schema_version: Literal["local-image-sdxl-validation-comparison-command/1.0"]
    run_id: str = Field(pattern=r"^imgsdxlvalcmprun_[0-9a-f]{32}$")
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    created_at: datetime
    purpose: Literal["EVALUATION_ONLY_RESERVED_SPATIAL_DIAGNOSTIC"]
    activation_policy: Literal["FORBIDDEN"]
    experiment_partition: Literal["VALIDATION"]
    configuration_role: Literal["NUMERICAL_CONFIGURATION_ONLY_NOT_CASE_AUTHORITY"]
    configuration_anchor: ImageEvaluationArtifactMember
    crop_sources: tuple[SdxlValidationCropSourcePin, ...] = Field(min_length=1, max_length=4)
    cases: tuple[SdxlValidationComparisonCase, ...] = Field(min_length=12, max_length=16)
    seed: int = Field(ge=0, le=2**32 - 1)
    budget: SdxlValidationComparisonBudget
    command_sha256: Sha256

    _created_utc = field_validator("created_at")(_utc)

    @model_validator(mode="after")
    def exact_command(self) -> Self:
        anchor = self.configuration_anchor
        protocol = sdxl_validation_protocol(self)
        if (
            anchor.schema_ref != protocol.anchor_schema_ref
            or anchor.member_path != "manifests/sdxl-canny-reference-command.json"
            or anchor.media_type != "application/json"
        ):
            raise ValueError("reserved comparison configuration anchor mismatch")
        sources = tuple(source.crop_set.sha256 for source in self.crop_sources)
        ids = tuple(entry.case.case_id for entry in self.cases)
        references = tuple(entry.case.reference_image.sha256 for entry in self.cases)
        selections = tuple(entry.selection_id for entry in self.cases)
        depictions = tuple(entry.case.depiction_key for entry in self.cases)
        if (
            sources != tuple(sorted(set(sources)))
            or ids != tuple(sorted(set(ids)))
            or len(set(references)) != len(ids)
            or len(set(selections)) != len(ids)
            or len(set(depictions)) != len(ids)
            or {entry.source_set_sha256 for entry in self.cases} != set(sources)
            or any(entry.case.seeds != (self.seed,) for entry in self.cases)
        ):
            raise ValueError("reserved comparison duplicate/unordered/unpinned cases or seed")
        identities = {
            (pin.artifact_id, pin.artifact_revision_id, pin.member_path)
            for source in self.crop_sources
            for pin in (source.crop_set, source.review)
        }
        if len(identities) != len(sources) * 2:
            raise ValueError("reserved comparison conflicting immutable source identities")
        if self.run_id != "imgsdxlvalcmprun_" + content_sha256(
            self.model_dump(mode="json", exclude={"run_id", "command_sha256"})
        )[7:39] or self.command_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"command_sha256"})
        ):
            raise ValueError("reserved comparison command identity/hash mismatch")
        return self


class LocalImageSdxlValidationComparisonCommandV2(LocalImageSdxlValidationComparisonCommand):
    schema_version: Literal["local-image-sdxl-validation-comparison-command/1.1"]  # type: ignore[assignment]


@dataclass(frozen=True, slots=True)
class SdxlValidationConfiguration:
    command: LocalImageSdxlCannyReferenceCommand
    sources: SdxlCannyReferenceSources
    training_review: LocalImageScienceSourcePageCropReview
    native_training_sources: SdxlNativeLoraSources | None = None


@dataclass(frozen=True, slots=True)
class SdxlValidationAdapter:
    training_result: ImageEvaluationArtifactMember
    manifest: LocalImageSdxlLoraMicroAdapterManifest | LocalImageSdxlNativeLoraAdapterManifest
    strength: float


def sdxl_validation_adapter(configuration: SdxlValidationConfiguration) -> SdxlValidationAdapter:
    """One rule owns the weights selected by canonical staging and numerical execution."""
    sources = configuration.sources
    if isinstance(sources, SdxlNativeCannyReferenceSources):
        return SdxlValidationAdapter(
            sources.evaluation.evaluation.training_result,
            sources.native.manifest,
            sources.evaluation.evaluation.adapter_strength,
        )
    pin = sources.spatial_sources.targets.evaluation.evaluation
    return SdxlValidationAdapter(
        pin.training_result, sources.spatial_sources.targets.lora.manifest, pin.adapter_strength
    )


def parse_sdxl_validation_configuration(
    command: LocalImageSdxlValidationComparisonCommand,
    anchor_raw: bytes,
    metadata: Mapping[str, bytes],
) -> SdxlValidationConfiguration:
    protocol = sdxl_validation_protocol(command)
    anchor = _document(
        command.configuration_anchor,
        anchor_raw,
        protocol.anchor_contract,
        protocol.anchor_model,
    )
    sources = parse_reference_sources(anchor, metadata)
    training = sources.spatial_sources.targets.lora.training_command
    if not isinstance(training, LocalImageSdxlReviewedMicroCommand):
        raise ValueError("reserved comparison requires admitted reviewed training history")
    supplemental = training.source_crop_set.schema_ref.endswith("/1.1")
    crop_set = _document(
        training.source_crop_set,
        metadata["inputs/source-crop-set.json"],
        "science-source-page-crop-set-v2" if supplemental else "science-source-page-crop-set",
        LocalImageScienceSourcePageCropSetV2
        if supplemental
        else LocalImageScienceSourcePageCropSet,
    )
    review = _document(
        crop_set.review,
        metadata["inputs/source-review.json"],
        "science-source-page-crop-review-v2" if supplemental else "science-source-page-crop-review",
        LocalImageScienceSourcePageCropReviewV2
        if supplemental
        else LocalImageScienceSourcePageCropReview,
    )
    validate_source_page_crop_set(review, crop_set)
    native_sources = None
    if isinstance(command, LocalImageSdxlValidationComparisonCommandV2):
        if not isinstance(sources, SdxlNativeCannyReferenceSources):
            raise ValueError("SDXL_VALIDATION_NATIVE_CONFIGURATION_MISSING")
        native_sources = parse_sdxl_native_lora_sources(
            sources.native.training_command,
            {name: raw for name, raw in metadata.items() if name.startswith("inputs/metadata/")},
        )
        if (
            sources.native.training_command.training_authorization != review.training_authorization
            or native_sources.batches[0].sources.review.basis_crop_set != review.basis_crop_set
        ):
            raise ValueError("SDXL_VALIDATION_NATIVE_SOURCE_BASIS_MISMATCH")
    return SdxlValidationConfiguration(anchor, sources, review, native_sources)


@dataclass(frozen=True, slots=True)
class SdxlValidationCropSource:
    pin: SdxlValidationCropSourcePin
    review: LocalImageScienceSourcePageCropReviewV3
    crop_set: LocalImageScienceSourcePageCropSetV3


def parse_sdxl_validation_crop_source(
    pin: SdxlValidationCropSourcePin, *, review_raw: bytes, crop_set_raw: bytes
) -> SdxlValidationCropSource:
    review = _document(
        pin.review,
        review_raw,
        "science-source-page-crop-review-v3",
        LocalImageScienceSourcePageCropReviewV3,
    )
    crop_set = _document(
        pin.crop_set,
        crop_set_raw,
        "science-source-page-crop-set-v3",
        LocalImageScienceSourcePageCropSetV3,
    )
    if crop_set.review != pin.review:
        raise ValueError("reserved comparison crop set has another reviewed revision")
    validate_source_page_crop_set(review, crop_set)
    return SdxlValidationCropSource(pin, review, crop_set)


@dataclass(frozen=True, slots=True)
class SdxlValidationComparisonSources:
    configuration: SdxlValidationConfiguration
    crop_sources: tuple[SdxlValidationCropSource, ...]


def validate_sdxl_validation_sources(
    command: LocalImageSdxlValidationComparisonCommand,
    sources: SdxlValidationComparisonSources,
) -> tuple[tuple[ScienceSourcePageRegionSelection, ScienceSourcePageCropMember], ...]:
    """Indexed case admission after the Orchestrator has checked complete canonical lineage."""
    configuration = sources.configuration
    validate_sdxl_canny_reference_sources(configuration.command, configuration.sources)
    raw = content_json_bytes(configuration.command.model_dump(mode="json"))
    if "sha256:" + hashlib.sha256(raw).hexdigest() != command.configuration_anchor.sha256:
        raise ValueError("reserved comparison differs from frozen configuration")
    spatial = configuration.sources.spatial_sources
    if command.seed != spatial.parent.seed or (
        command.created_at < configuration.command.created_at
        or tuple(source.pin for source in sources.crop_sources) != command.crop_sources
    ):
        raise ValueError("reserved comparison configuration/seed/source order mismatch")
    training = {row.sample_id for row in spatial.targets.lora.training_command.training_samples}
    training_rows: tuple[ScienceSourcePageRegionSelection | ScienceSourcePageCropRegion, ...] = (
        configuration.training_review.selections
    )
    if isinstance(command, LocalImageSdxlValidationComparisonCommandV2):
        if configuration.native_training_sources is None:
            raise ValueError("SDXL_VALIDATION_NATIVE_SOURCE_CLOSURE_MISSING")
        # The historical anchor cannot certify absence of native-only TRAIN leakage.
        training_rows = (*training_rows, *configuration.native_training_sources.regions)
        training.update(row.selection_id for row in configuration.native_training_sources.regions)
    training_documents = {row.document_id for row in training_rows}
    training_pdfs = {row.source_document.sha256 for row in training_rows}
    training_groups = {row.exam_group_sha256 for row in training_rows}
    by_set = {}
    for source in sources.crop_sources:
        validate_source_page_crop_set(source.review, source.crop_set)
        if (
            source.crop_set.review != source.pin.review
            or source.pin.crop_set.sha256
            != "sha256:"
            + hashlib.sha256(
                content_json_bytes(source.crop_set.model_dump(mode="json"))
            ).hexdigest()
            or source.review.training_authorization
            != configuration.training_review.training_authorization
            or source.review.basis_crop_set != configuration.training_review.basis_crop_set
            or (
                not isinstance(command, LocalImageSdxlValidationComparisonCommandV2)
                and source.review.created_at < configuration.command.created_at
            )
            or source.review.created_at > command.created_at
            or source.crop_set.created_at > command.created_at
        ):
            raise ValueError("reserved comparison source authorization/temporal basis mismatch")
        by_set[source.pin.crop_set.sha256] = (
            source,
            {row.selection_id: row for row in source.review.selections},
            {row.selection_id: row for row in source.crop_set.members},
        )
    admitted = []
    groups = set()
    documents: dict[str, tuple[ImageEvaluationArtifactMember, str]] = {}
    for entry in command.cases:
        source, selections, members = by_set[entry.source_set_sha256]
        selection, member = selections.get(entry.selection_id), members.get(entry.selection_id)
        if selection is None or member is None:
            raise ValueError("reserved comparison selection target missing")
        case = entry.case
        if (
            selection.partition != "VALIDATION"
            or selection.selection_id in training
            or selection.document_id in training_documents
            or selection.source_document.sha256 in training_pdfs
            or selection.exam_group_sha256 in training_groups
            or case.reference_image != source_page_crop_pointer(source.pin.crop_set, member)
            or case.depiction_key != selection.depiction_key
            or (case.reference_width_px, case.reference_height_px)
            != (member.width_px, member.height_px)
        ):
            raise ValueError("reserved comparison partition/leakage/crop/dimension mismatch")
        identity = (selection.source_document, selection.exam_group_sha256)
        if documents.setdefault(selection.document_id, identity) != identity:
            raise ValueError("reserved comparison conflicting document identity")
        groups.add(selection.exam_group_sha256)
        admitted.append((selection, member))
    if len(groups) < 6:
        raise ValueError("reserved comparison requires six independent original exam groups")
    return tuple(admitted)


class LocalImageSdxlValidationComparisonResult(FrozenModel):
    schema_version: Literal["local-image-sdxl-validation-comparison-result/1.0"]
    run_id: str = Field(pattern=r"^imgsdxlvalcmprun_[0-9a-f]{32}$")
    command_sha256: Sha256
    configuration_command_sha256: Sha256
    case_relation: Literal["RESERVED_VALIDATION_NOT_TRAIN_OR_HOLDOUT"]
    native_fit_policy: Literal["NATIVE_FIT_800X500_CENTER_832X512_OPENCV_CANNY/1.0"]
    quality_acceptance: Literal["NOT_REVIEWED"]
    activation_policy: Literal["FORBIDDEN"]
    training_steps: Literal[0]
    holdout_binary_reads: Literal[0]
    status: Literal["SUCCEEDED", "FAILED"]
    error_code: SdxlProbeErrorCode | None
    runtime: LocalImageRuntime | None
    inputs: tuple[SdxlCannyReferenceTrace, ...] = Field(min_length=12, max_length=16)
    outputs: tuple[SdxlLearnedComparisonOutput, ...] = Field(max_length=32)
    started_at: datetime
    completed_at: datetime
    duration_ms: int = Field(ge=1, le=3_600_000)
    result_sha256: Sha256

    _timestamps_utc = field_validator("started_at", "completed_at")(_utc)

    @model_validator(mode="after")
    def exact_result(self) -> Self:
        ids = tuple(row.case_id for row in self.inputs)
        keys = tuple((row.arm, row.case_id, row.seed) for row in self.outputs)
        if (
            ids != tuple(sorted(set(ids)))
            or keys != tuple(sorted(set(keys)))
            or self.completed_at < self.started_at
            or (self.status == "SUCCEEDED") != (self.error_code is None)
            or self.result_sha256
            != content_sha256(self.model_dump(mode="json", exclude={"result_sha256"}))
        ):
            raise ValueError("reserved comparison result order/status/time/hash mismatch")
        if self.outputs and (
            self.runtime is None
            or self.runtime.peak_gpu_memory_bytes
            < max(row.peak_gpu_memory_bytes for row in self.outputs)
        ):
            raise ValueError("reserved comparison result lacks measured runtime")
        return self


class LocalImageSdxlValidationComparisonResultV2(LocalImageSdxlValidationComparisonResult):
    schema_version: Literal["local-image-sdxl-validation-comparison-result/1.1"]  # type: ignore[assignment]
    native_evaluation_command_sha256: Sha256
    native_adapter_manifest_sha256: Sha256


@dataclass(frozen=True, slots=True)
class SdxlValidationProtocol:
    command_version: str
    result_version: str
    command_model: type[LocalImageSdxlValidationComparisonCommand]
    result_model: type[LocalImageSdxlValidationComparisonResult]
    command_contract: str
    result_contract: str
    anchor_model: type[LocalImageSdxlCannyReferenceCommand]
    anchor_contract: str
    anchor_schema_ref: str


_PROTOCOLS = (
    SdxlValidationProtocol(
        "local-image-sdxl-validation-comparison-command/1.0",
        "local-image-sdxl-validation-comparison-result/1.0",
        LocalImageSdxlValidationComparisonCommand,
        LocalImageSdxlValidationComparisonResult,
        "sdxl-validation-comparison-command",
        "sdxl-validation-comparison-result",
        LocalImageSdxlCannyReferenceCommand,
        "sdxl-canny-reference-command",
        _PREFIX + "sdxl-canny-reference-command/1.0",
    ),
    SdxlValidationProtocol(
        "local-image-sdxl-validation-comparison-command/1.1",
        "local-image-sdxl-validation-comparison-result/1.1",
        LocalImageSdxlValidationComparisonCommandV2,
        LocalImageSdxlValidationComparisonResultV2,
        "sdxl-validation-comparison-command-v2",
        "sdxl-validation-comparison-result-v2",
        LocalImageSdxlNativeCannyReferenceCommandV2,
        "sdxl-canny-reference-command-v3",
        _PREFIX + "sdxl-canny-reference-command/1.2",
    ),
)
_COMMAND_PROTOCOLS = MappingProxyType({p.command_version: p for p in _PROTOCOLS})
_RESULT_PROTOCOLS = MappingProxyType({p.result_version: p for p in _PROTOCOLS})


def sdxl_validation_protocol(
    command: LocalImageSdxlValidationComparisonCommand,
) -> SdxlValidationProtocol:
    protocol = _COMMAND_PROTOCOLS.get(command.schema_version)
    if protocol is None or type(command) is not protocol.command_model:
        raise ValueError("SDXL_VALIDATION_COMMAND_FAMILY_INVALID")
    return protocol


def parse_sdxl_validation_command(value: object) -> LocalImageSdxlValidationComparisonCommand:
    from eom_image_contracts.validation import validate_contract

    if not isinstance(value, dict) or not isinstance(value.get("schema_version"), str):
        raise ValueError("SDXL_VALIDATION_COMMAND_FAMILY_INVALID")
    protocol = _COMMAND_PROTOCOLS.get(value["schema_version"])
    if protocol is None:
        raise ValueError("SDXL_VALIDATION_COMMAND_FAMILY_INVALID")
    validate_contract(protocol.command_contract, value)
    return protocol.command_model.model_validate(value)


def parse_sdxl_validation_result(value: object) -> LocalImageSdxlValidationComparisonResult:
    from eom_image_contracts.validation import validate_contract

    if not isinstance(value, dict) or not isinstance(value.get("schema_version"), str):
        raise ValueError("SDXL_VALIDATION_RESULT_FAMILY_INVALID")
    protocol = _RESULT_PROTOCOLS.get(value["schema_version"])
    if protocol is None:
        raise ValueError("SDXL_VALIDATION_RESULT_FAMILY_INVALID")
    validate_contract(protocol.result_contract, value)
    return protocol.result_model.model_validate(value)


def sdxl_validation_native_result_fields(
    sources: SdxlValidationComparisonSources,
) -> dict[str, str]:
    configuration = sources.configuration.sources
    if isinstance(configuration, SdxlNativeCannyReferenceSources):
        return {
            "native_evaluation_command_sha256": configuration.evaluation.command_sha256,
            "native_adapter_manifest_sha256": configuration.native.manifest.manifest_sha256,
        }
    return {}


def validate_sdxl_validation_result(
    command: LocalImageSdxlValidationComparisonCommand,
    sources: SdxlValidationComparisonSources,
    result: LocalImageSdxlValidationComparisonResult,
) -> None:
    if type(result) is not sdxl_validation_protocol(command).result_model:
        raise ValueError("SDXL_VALIDATION_RESULT_FAMILY_INVALID")
    validate_sdxl_validation_sources(command, sources)
    native_fields = sdxl_validation_native_result_fields(sources)
    if isinstance(result, LocalImageSdxlValidationComparisonResultV2) and (
        native_fields != {name: getattr(result, name) for name in native_fields}
        or not isinstance(sources.configuration.sources, SdxlNativeCannyReferenceSources)
    ):
        raise ValueError("SDXL_VALIDATION_NATIVE_RESULT_LINEAGE_MISMATCH")
    expected = tuple(
        (arm, entry.case.case_id, command.seed)
        for arm in LEARNED_COMPARISON_ARMS
        for entry in command.cases
    )
    observed = tuple((row.arm, row.case_id, row.seed) for row in result.outputs)
    traces = {row.case_id: row for row in result.inputs}
    if (
        result.run_id != command.run_id
        or result.command_sha256 != command.command_sha256
        or result.configuration_command_sha256 != sources.configuration.command.command_sha256
        or result.started_at < command.created_at
        or tuple(traces) != tuple(entry.case.case_id for entry in command.cases)
        or observed != expected[: len(observed)]
        or any(
            traces[entry.case.case_id].source_sha256 != entry.case.reference_image.sha256
            for entry in command.cases
        )
        or any(
            row.reference_sha256 != traces[row.case_id].source_sha256
            or row.conditioning_sha256 != traces[row.case_id].conditioning_sha256
            for row in result.outputs
        )
    ):
        raise ValueError("reserved comparison result differs from pinned ordered case prefix")
    if result.status == "SUCCEEDED" and (
        observed != expected
        or result.runtime is None
        or result.duration_ms > command.budget.maximum_duration_ms
        or result.runtime.peak_gpu_memory_bytes > command.budget.maximum_peak_gpu_memory_bytes
    ):
        raise ValueError("reserved comparison success coverage/resource budget mismatch")
