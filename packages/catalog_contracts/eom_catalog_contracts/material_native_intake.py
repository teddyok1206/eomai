"""Native exam attachment successors; existing material V1 bytes and meanings stay fixed."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, Self

from eom_identifiers import content_sha256
from pydantic import Field, field_validator, model_validator

from eom_catalog_contracts.material_learning import (
    MaterialArtifactMember,
    MaterialLearningUpload,
    MaterialPreparedSource,
)
from eom_catalog_contracts.material_learning_intake import (
    CreateMaterialLearningCommand,
    MaterialIdempotencyKey,
    MaterialLearningIntakeManifest,
    MaterialLearningSourceSelection,
    MaterialOperatorId,
    _require_source_selections,
)
from eom_catalog_contracts.material_learning_preparation import (
    MaterialPreparationInput,
    MaterialPreparationProfile,
    MaterialPreparedArtifact,
)
from eom_catalog_contracts.material_native_files import (
    MaterialNativeFileBinding,
    MaterialNativeItemBinding,
    MaterialNativeSourceMetadata,
    MaterialNativeWorkbookRow,
    MaterialNativeWorkbookSelection,
    NativeNumber,
    material_native_printed_number,
    require_material_native_workbook_members,
    require_material_native_workbook_selections,
)
from eom_catalog_contracts.models import FrozenModel, Sha256, _safe_text
from eom_catalog_contracts.native_exam_intake import NativeExamWorkbookDocument
from eom_catalog_contracts.validation import validate_contract

MATERIAL_NATIVE_BUNDLE_REF = "eom://schemas/material-learning/native-exam-bundle/1.0"
MATERIAL_NATIVE_INTAKE_REF = "eom://schemas/material-learning/intake/2.0"
MATERIAL_NATIVE_PREPARATION_REF = "eom://schemas/material-learning/preparation-input/2.0"
MATERIAL_NATIVE_PREPARED_REF = "eom://schemas/material-learning/prepared/2.0"


def _require_native_bundle_pointer(pointer: MaterialArtifactMember) -> None:
    if pointer.schema_ref != MATERIAL_NATIVE_BUNDLE_REF or pointer.media_type != "application/json":
        raise ValueError("MATERIAL_NATIVE_BUNDLE_POINTER_INVALID")


def _require_native_sources(
    sources: tuple[MaterialLearningSourceSelection, ...], actor_id: str
) -> None:
    _require_source_selections(sources, actor_id)
    if tuple(source.source_role for source in sources) != ("MAIN", "SOLUTIONS") or any(
        source.source_upload.source_format not in {"HWP", "HWPX"} for source in sources
    ):
        raise ValueError("MATERIAL_NATIVE_ORIGINAL_PAIR_REQUIRED")


class MaterialNativeWorkbookSource(FrozenModel):
    workbook: MaterialArtifactMember
    parsed_workbook: MaterialArtifactMember
    worksheet_name: str = Field(min_length=1, max_length=255)

    _text = field_validator("worksheet_name")(_safe_text)

    @model_validator(mode="after")
    def exact_shared_workbook(self) -> Self:
        require_material_native_workbook_members(self.workbook, self.parsed_workbook)
        return self


class MaterialNativeExamItem(FrozenModel):
    item_number: NativeNumber
    printed_label: str = Field(min_length=1, max_length=100)
    question: MaterialNativeFileBinding
    solution: MaterialNativeFileBinding
    row_number: int = Field(strict=True, ge=1, le=1048576)
    row_sha256: Sha256
    source_metadata: MaterialNativeSourceMetadata

    @model_validator(mode="after")
    def explicit_number_and_file_roles(self) -> Self:
        if (
            material_native_printed_number(self.printed_label) != self.item_number
            or self.question.source_role != "MAIN"
            or self.solution.source_role != "SOLUTIONS"
        ):
            raise ValueError("MATERIAL_NATIVE_EXAM_ITEM_INVALID")
        return self


class MaterialNativeExamBundle(FrozenModel):
    schema_version: Literal["material-native-exam-bundle/1.0"] = "material-native-exam-bundle/1.0"
    uploaded_by: MaterialOperatorId
    source_namespace: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")
    exam_key: str = Field(min_length=1, max_length=256)
    main_original: MaterialArtifactMember
    solutions_original: MaterialArtifactMember
    workbook: MaterialNativeWorkbookSource
    items: tuple[MaterialNativeExamItem, ...] = Field(min_length=1, max_length=10000)
    bundle_sha256: Sha256

    _text = field_validator("exam_key")(_safe_text)

    @model_validator(mode="after")
    def exact_native_source_set(self) -> Self:
        numbers = tuple(item.item_number for item in self.items)
        if numbers != tuple(sorted(set(numbers))) or len(
            {item.row_number for item in self.items}
        ) != len(self.items):
            raise ValueError("MATERIAL_NATIVE_EXAM_ITEM_DUPLICATED_OR_UNORDERED")
        originals = {"MAIN": self.main_original, "SOLUTIONS": self.solutions_original}
        if self.main_original.sha256 == self.solutions_original.sha256:
            raise ValueError("MATERIAL_NATIVE_EXAM_ORIGINAL_DUPLICATED")
        native_hashes: dict[str, set[str]] = {"MAIN": set(), "SOLUTIONS": set()}
        for item in self.items:
            for file in (item.question, item.solution):
                source = originals[file.source_role]
                if (
                    source.media_type
                    not in {
                        "application/vnd.hancom.hwp",
                        "application/x-hwp",
                        "application/haansofthwp",
                        "application/vnd.hancom.hwpx",
                        "application/hwp+zip",
                    }
                    or file.original_source_sha256 != source.sha256
                ):
                    raise ValueError("MATERIAL_NATIVE_EXAM_ORIGINAL_MISMATCH")
                native_hashes[file.source_role].add(file.native_source_sha256)
        if any(len(values) != 1 for values in native_hashes.values()):
            raise ValueError("MATERIAL_NATIVE_EXAM_CONVERSION_MIXED")
        if self.bundle_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"bundle_sha256"})
        ):
            raise ValueError("MATERIAL_NATIVE_EXAM_BUNDLE_HASH_MISMATCH")
        validate_contract("material-native-exam-bundle-v1", self.model_dump(mode="json"))
        return self


def require_native_exam_bundle_sources(
    bundle: MaterialNativeExamBundle,
    sources: tuple[MaterialLearningSourceSelection, ...],
    *,
    operator_id: str,
) -> None:
    """Actual operator authorization and Artifact resolution remain application responsibilities."""
    _require_native_sources(sources, operator_id)
    if bundle.uploaded_by != operator_id or (
        bundle.main_original,
        bundle.solutions_original,
    ) != tuple(source.source_upload.original for source in sources):
        raise ValueError("MATERIAL_NATIVE_EXAM_OWNER_OR_SOURCE_MISMATCH")


def require_native_exam_bundle_workbook(
    bundle: MaterialNativeExamBundle, parsed: NativeExamWorkbookDocument
) -> None:
    """Validate real workbook rows before discovered unit keys exist, without fake IDs."""
    require_material_native_workbook_selections(
        tuple(
            MaterialNativeWorkbookSelection(
                MaterialNativeWorkbookRow(
                    **bundle.workbook.model_dump(mode="json"),
                    row_number=item.row_number,
                    row_sha256=item.row_sha256,
                ),
                item.item_number,
                item.source_metadata,
            )
            for item in bundle.items
        ),
        parsed,
    )


def bind_native_exam_items(
    bundle: MaterialNativeExamBundle,
    *,
    material_id: str,
    material_revision_id: str,
    units: Mapping[int, tuple[str, str]],
) -> tuple[MaterialNativeItemBinding, ...]:
    """Bind discovered unit keys in O(exam items + selected units), without guessing labels."""
    items = {item.item_number: item for item in bundle.items}
    if not units or not set(units).issubset(items):
        raise ValueError("MATERIAL_NATIVE_EXAM_UNIT_NUMBER_MISSING")
    result = []
    for number in sorted(units):
        unit_key, printed_label = units[number]
        if material_native_printed_number(printed_label) != number:
            raise ValueError("MATERIAL_NATIVE_EXAM_UNIT_LABEL_MISMATCH")
        item = items[number]
        body = dict(
            schema_version="material-native-item-binding/1.0",
            material_id=material_id,
            material_revision_id=material_revision_id,
            unit_key=unit_key,
            source_namespace=bundle.source_namespace,
            exam_key=bundle.exam_key,
            item_number=number,
            printed_label=printed_label,
            question=item.question.model_dump(mode="json"),
            solution=item.solution.model_dump(mode="json"),
            workbook={
                **bundle.workbook.model_dump(mode="json"),
                "row_number": item.row_number,
                "row_sha256": item.row_sha256,
            },
            source_metadata=item.source_metadata.model_dump(mode="json"),
        )
        result.append(
            MaterialNativeItemBinding.model_validate(
                {**body, "binding_sha256": content_sha256(body)}
            )
        )
    return tuple(result)


class CreateNativeMaterialLearningCommand(FrozenModel):
    schema_version: Literal["material-learning-create/2.0"] = "material-learning-create/2.0"
    operation: Literal["CREATE_MATERIAL_LEARNING"] = "CREATE_MATERIAL_LEARNING"
    actor_id: MaterialOperatorId
    idempotency_key: MaterialIdempotencyKey
    upload: MaterialLearningUpload
    sources: tuple[MaterialLearningSourceSelection, ...] = Field(min_length=2, max_length=2)
    native_bundle: MaterialArtifactMember

    @model_validator(mode="after")
    def exact_native_submission(self) -> Self:
        _require_native_sources(self.sources, self.actor_id)
        _require_native_bundle_pointer(self.native_bundle)
        validate_contract("material-learning-create-v2", self.model_dump(mode="json"))
        return self


class MaterialNativeLearningIntakeManifest(FrozenModel):
    schema_version: Literal["material-learning-intake/2.0"] = "material-learning-intake/2.0"
    material_id: str = Field(pattern=r"^material_[0-9a-f]{32}$")
    material_revision_id: str = Field(pattern=r"^materialrev_[0-9a-f]{32}$")
    requested_by: MaterialOperatorId
    request_sha256: Sha256
    upload: MaterialLearningUpload
    sources: tuple[MaterialLearningSourceSelection, ...] = Field(min_length=2, max_length=2)
    rights_attestation: MaterialArtifactMember
    native_bundle: MaterialArtifactMember

    @model_validator(mode="after")
    def exact_native_intake(self) -> Self:
        _require_native_sources(self.sources, self.requested_by)
        _require_native_bundle_pointer(self.native_bundle)
        if (
            self.rights_attestation.schema_ref != "eom://schemas/material-learning/rights/1.0"
            or self.rights_attestation.member_path != "rights/attestation.json"
            or self.rights_attestation.media_type != "application/json"
        ):
            raise ValueError("MATERIAL_LEARNING_INTAKE_RIGHTS_POINTER_INVALID")
        validate_contract("material-learning-intake-v2", self.model_dump(mode="json"))
        return self


class MaterialNativePreparationInput(FrozenModel):
    schema_version: Literal["material-learning-preparation-input/2.0"] = (
        "material-learning-preparation-input/2.0"
    )
    task_id: str = Field(pattern=r"^materialtask_[0-9a-f]{32}$")
    material_id: str = Field(pattern=r"^material_[0-9a-f]{32}$")
    material_revision_id: str = Field(pattern=r"^materialrev_[0-9a-f]{32}$")
    intake_manifest: MaterialArtifactMember
    profile: MaterialPreparationProfile
    native_bundle: MaterialArtifactMember
    input_sha256: Sha256

    @model_validator(mode="after")
    def exact_native_preparation(self) -> Self:
        _require_native_bundle_pointer(self.native_bundle)
        if (
            self.intake_manifest.schema_ref != MATERIAL_NATIVE_INTAKE_REF
            or self.intake_manifest.media_type != "application/json"
        ):
            raise ValueError("MATERIAL_LEARNING_PREPARATION_INTAKE_INVALID")
        if self.input_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"input_sha256"})
        ):
            raise ValueError("MATERIAL_LEARNING_PREPARATION_HASH_MISMATCH")
        validate_contract("material-learning-preparation-input-v2", self.model_dump(mode="json"))
        return self


class MaterialNativePreparedArtifact(FrozenModel):
    schema_version: Literal["material-learning-prepared/2.0"] = "material-learning-prepared/2.0"
    material_id: str = Field(pattern=r"^material_[0-9a-f]{32}$")
    material_revision_id: str = Field(pattern=r"^materialrev_[0-9a-f]{32}$")
    intake_manifest: MaterialArtifactMember
    profile_sha256: Sha256
    sources: tuple[MaterialPreparedSource, ...] = Field(min_length=2, max_length=2)
    native_bundle: MaterialArtifactMember
    prepared_sha256: Sha256

    @model_validator(mode="after")
    def exact_native_prepared_sources(self) -> Self:
        _require_native_bundle_pointer(self.native_bundle)
        if (
            tuple(source.source_role for source in self.sources) != ("MAIN", "SOLUTIONS")
            or any(source.actual_format not in {"HWP", "HWPX"} for source in self.sources)
            or len({source.document_revision_id for source in self.sources}) != 2
            or self.intake_manifest.schema_ref != MATERIAL_NATIVE_INTAKE_REF
            or self.intake_manifest.media_type != "application/json"
        ):
            raise ValueError("MATERIAL_NATIVE_PREPARED_SOURCE_MISMATCH")
        if self.prepared_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"prepared_sha256"})
        ):
            raise ValueError("MATERIAL_LEARNING_PREPARATION_HASH_MISMATCH")
        validate_contract("material-learning-prepared-v2", self.model_dump(mode="json"))
        return self


type MaterialLearningCreate = CreateMaterialLearningCommand | CreateNativeMaterialLearningCommand
type MaterialIntake = MaterialLearningIntakeManifest | MaterialNativeLearningIntakeManifest
type MaterialPreparation = MaterialPreparationInput | MaterialNativePreparationInput
type MaterialPrepared = MaterialPreparedArtifact | MaterialNativePreparedArtifact


def parse_material_learning_create(value: Mapping[str, object]) -> MaterialLearningCreate:
    """Keep the historical V1 default; a declared invalid family never falls back."""
    version = value.get("schema_version", "material-learning-create/1.0")
    if version == "material-learning-create/1.0":
        return CreateMaterialLearningCommand.model_validate(value)
    if version == "material-learning-create/2.0":
        return CreateNativeMaterialLearningCommand.model_validate(value)
    raise ValueError("MATERIAL_LEARNING_CREATE_SCHEMA_UNSUPPORTED")


def require_native_material_checkpoint_chain(
    intake: MaterialIntake,
    *,
    preparation: MaterialPreparation | None = None,
    prepared: MaterialPrepared | None = None,
    intake_pointer: MaterialArtifactMember | None = None,
) -> None:
    """Keep one version family, exact intake and native bundle across restart checkpoints."""
    native = isinstance(intake, MaterialNativeLearningIntakeManifest)
    expected_ref = (
        MATERIAL_NATIVE_INTAKE_REF if native else "eom://schemas/material-learning/intake/1.0"
    )
    if intake_pointer is not None and (
        intake_pointer.schema_ref != expected_ref
        or intake_pointer.media_type != "application/json"
        or intake_pointer.member_path != "material/intake.json"
    ):
        raise ValueError("MATERIAL_LEARNING_CHECKPOINT_CHAIN_MISMATCH")
    checkpoints = tuple(value for value in (preparation, prepared) if value is not None)
    expected_pointer = intake_pointer or (checkpoints[0].intake_manifest if checkpoints else None)
    for checkpoint in checkpoints:
        checkpoint_native = isinstance(
            checkpoint, (MaterialNativePreparationInput, MaterialNativePreparedArtifact)
        )
        if (
            checkpoint_native != native
            or checkpoint.material_id != intake.material_id
            or checkpoint.material_revision_id != intake.material_revision_id
            or checkpoint.intake_manifest.schema_ref != expected_ref
            or checkpoint.intake_manifest != expected_pointer
        ):
            raise ValueError("MATERIAL_LEARNING_CHECKPOINT_CHAIN_MISMATCH")
        if (
            isinstance(intake, MaterialNativeLearningIntakeManifest)
            and isinstance(
                checkpoint, (MaterialNativePreparationInput, MaterialNativePreparedArtifact)
            )
            and checkpoint.native_bundle != intake.native_bundle
        ):
            raise ValueError("MATERIAL_NATIVE_CHECKPOINT_BUNDLE_MISMATCH")
