"""Native attachments extend exact material contracts without reinterpreting released V1."""

from copy import deepcopy

import pytest
from eom_catalog_contracts.material_learning_intake import (
    CreateMaterialLearningCommand,
    MaterialLearningIntakeManifest,
)
from eom_catalog_contracts.material_learning_preparation import (
    MaterialPreparationInput,
    MaterialPreparedArtifact,
)
from eom_catalog_contracts.material_native_intake import (
    MATERIAL_NATIVE_BUNDLE_REF,
    MATERIAL_NATIVE_INTAKE_REF,
    CreateNativeMaterialLearningCommand,
    MaterialNativeExamBundle,
    MaterialNativeLearningIntakeManifest,
    MaterialNativePreparationInput,
    MaterialNativePreparedArtifact,
    bind_native_exam_items,
    require_native_exam_bundle_sources,
    require_native_exam_bundle_workbook,
    require_native_material_checkpoint_chain,
)
from eom_identifiers import content_sha256

from tests.unit.test_material_learning_contracts import member, rehash
from tests.unit.test_material_learning_intake import ACTOR, create_command, source_receipt
from tests.unit.test_material_learning_preparation import profile
from tests.unit.test_material_native_files import (
    binding_data,
    native_work,
    pointer,
    workbook_document,
)


def native_create():
    value = create_command()
    value["schema_version"] = "material-learning-create/2.0"
    value["native_bundle"] = pointer(
        "native/exam-bundle.json", "application/json", MATERIAL_NATIVE_BUNDLE_REF
    )
    first, second = source_receipt("HWP"), source_receipt("HWP")
    second["original"]["sha256"] = "sha256:" + "e" * 64
    second["original"]["artifact_id"] = "artifact_" + "e" * 32
    second["original"]["artifact_revision_id"] = "rev_" + "e" * 32
    second["manifest"]["artifact_id"] = "artifact_" + "e" * 32
    second["manifest"]["artifact_revision_id"] = "rev_" + "e" * 32
    value["sources"] = [
        dict(source_role="MAIN", source_upload=first),
        dict(source_role="SOLUTIONS", source_upload=second),
    ]
    return value


def native_intake():
    command = CreateNativeMaterialLearningCommand.model_validate(native_create())
    return dict(
        schema_version="material-learning-intake/2.0",
        material_id="material_" + "5" * 32,
        material_revision_id="materialrev_" + "6" * 32,
        requested_by=ACTOR,
        request_sha256=content_sha256(command.model_dump(mode="json")),
        upload=command.upload.model_dump(mode="json"),
        sources=[source.model_dump(mode="json") for source in command.sources],
        native_bundle=command.native_bundle.model_dump(mode="json"),
        rights_attestation=member(
            "rights/attestation.json", "application/json", "material-learning/rights/1.0"
        ),
    )


def native_exam_bundle():
    command = CreateNativeMaterialLearningCommand.model_validate(native_create())
    binding = binding_data()
    row = deepcopy(binding["workbook"])
    row.pop("row_number")
    row.pop("row_sha256")
    body = dict(
        schema_version="material-native-exam-bundle/1.0",
        uploaded_by=ACTOR,
        source_namespace="native-exam-corpus",
        exam_key="exam-01",
        main_original=command.sources[0].source_upload.original.model_dump(mode="json"),
        solutions_original=command.sources[1].source_upload.original.model_dump(mode="json"),
        workbook=row,
        items=[
            dict(
                item_number=1,
                printed_label="01번",
                question=binding["question"],
                solution=binding["solution"],
                row_number=3,
                row_sha256=binding["workbook"]["row_sha256"],
                source_metadata=binding["source_metadata"],
            )
        ],
    )
    return rehash(body, "bundle_sha256")


def native_preparation():
    body = dict(
        schema_version="material-learning-preparation-input/2.0",
        task_id="materialtask_" + "7" * 32,
        material_id="material_" + "5" * 32,
        material_revision_id="materialrev_" + "6" * 32,
        intake_manifest=pointer(
            "material/intake.json", "application/json", MATERIAL_NATIVE_INTAKE_REF
        ),
        profile=profile(),
        native_bundle=native_create()["native_bundle"],
    )
    return rehash(body)


def native_prepared():
    sources = native_work()["sources"]
    sources[1]["document_revision_id"] = "edudocrev_" + "e" * 32
    body = dict(
        schema_version="material-learning-prepared/2.0",
        material_id="material_" + "5" * 32,
        material_revision_id="materialrev_" + "6" * 32,
        intake_manifest=native_preparation()["intake_manifest"],
        profile_sha256=profile()["profile_sha256"],
        sources=sources,
        native_bundle=native_create()["native_bundle"],
    )
    return rehash(body, "prepared_sha256")


def test_native_create_intake_and_preparation_are_explicit_successors_not_v1():
    cases = (
        (native_create(), CreateNativeMaterialLearningCommand, CreateMaterialLearningCommand),
        (native_intake(), MaterialNativeLearningIntakeManifest, MaterialLearningIntakeManifest),
        (native_preparation(), MaterialNativePreparationInput, MaterialPreparationInput),
        (native_prepared(), MaterialNativePreparedArtifact, MaterialPreparedArtifact),
    )
    for data, model, predecessor in cases:
        assert model.model_validate(data).native_bundle.schema_ref == MATERIAL_NATIVE_BUNDLE_REF
        with pytest.raises(ValueError):
            predecessor.model_validate(data)


@pytest.mark.parametrize("mismatch", ["owner", "pdf", "role", "same_original"])
def test_native_submission_requires_the_actual_native_pair_and_original_upload_owner(mismatch):
    value = native_create()
    if mismatch == "owner":
        value["sources"][1]["source_upload"]["uploaded_by"] = "operator_" + "e" * 32
    elif mismatch == "pdf":
        value["sources"][1]["source_upload"] = source_receipt("PDF")
    elif mismatch == "role":
        value["sources"].reverse()
    else:
        value["sources"][1]["source_upload"] = deepcopy(value["sources"][0]["source_upload"])
    with pytest.raises(ValueError):
        CreateNativeMaterialLearningCommand.model_validate(value)


def test_exam_bundle_matches_exact_operator_and_source_members_not_hash_only():
    command = CreateNativeMaterialLearningCommand.model_validate(native_create())
    bundle = MaterialNativeExamBundle.model_validate(native_exam_bundle())
    require_native_exam_bundle_sources(bundle, command.sources, operator_id=ACTOR)
    changed = native_exam_bundle()
    changed["main_original"]["artifact_revision_id"] = "rev_" + "f" * 32
    wrong_member = MaterialNativeExamBundle.model_validate(rehash(changed, "bundle_sha256"))
    with pytest.raises(ValueError, match="OWNER_OR_SOURCE_MISMATCH"):
        require_native_exam_bundle_sources(wrong_member, command.sources, operator_id=ACTOR)
    with pytest.raises(ValueError, match="OWNER_MISMATCH"):
        require_native_exam_bundle_sources(
            bundle, command.sources, operator_id="operator_" + "f" * 32
        )


def test_bundle_item_binding_requires_explicit_discovered_number_and_retains_null_external_id():
    bundle = MaterialNativeExamBundle.model_validate(native_exam_bundle())
    values = bind_native_exam_items(
        bundle,
        material_id="material_" + "5" * 32,
        material_revision_id="materialrev_" + "6" * 32,
        units={1: ("materialunit_" + "8" * 32, "1.")},
    )
    assert len(values) == 1
    value = values[0]
    assert value.printed_label == "1."
    assert value.source_metadata.external_number is None
    assert value.source_metadata.original_unit == " 단원 원문 "
    assert value.workbook.row_number == 3
    assert value.workbook.workbook == bundle.workbook.workbook
    with pytest.raises(ValueError, match="UNIT_NUMBER_MISSING"):
        bind_native_exam_items(
            bundle,
            material_id=value.material_id,
            material_revision_id=value.material_revision_id,
            units={2: (value.unit_key, "2")},
        )
    with pytest.raises(ValueError, match="PRINTED_NUMBER_INVALID"):
        bind_native_exam_items(
            bundle,
            material_id=value.material_id,
            material_revision_id=value.material_revision_id,
            units={1: (value.unit_key, "예제1")},
        )


@pytest.mark.parametrize("mismatch", ["number", "row", "source", "hash", "role"])
def test_bundle_cannot_hide_duplicate_or_unrelated_native_item_files(mismatch):
    value = native_exam_bundle()
    if mismatch in {"number", "row"}:
        value["items"].append(deepcopy(value["items"][0]))
        if mismatch == "row":
            value["items"][1]["item_number"] = 2
            value["items"][1]["printed_label"] = "2"
    elif mismatch == "source":
        value["items"][0]["question"]["original_source_sha256"] = "sha256:" + "0" * 64
    elif mismatch == "role":
        value["items"][0]["question"]["source_role"] = "SOLUTIONS"
    else:
        value["bundle_sha256"] = "sha256:" + "0" * 64
    if mismatch != "hash":
        rehash(value, "bundle_sha256")
    with pytest.raises(ValueError):
        MaterialNativeExamBundle.model_validate(value)


def test_native_prepared_rejects_lost_bundle_changed_hash_and_legacy_intake():
    value = native_prepared()
    value["intake_manifest"]["schema_ref"] = "eom://schemas/material-learning/intake/1.0"
    with pytest.raises(ValueError, match="PREPARED_SOURCE_MISMATCH"):
        MaterialNativePreparedArtifact.model_validate(rehash(value, "prepared_sha256"))
    value = native_prepared()
    value["native_bundle"]["sha256"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="HASH_MISMATCH"):
        MaterialNativePreparedArtifact.model_validate(value)


def test_checkpoint_chain_pins_one_material_intake_and_native_bundle_across_restart():
    intake = MaterialNativeLearningIntakeManifest.model_validate(native_intake())
    preparation = MaterialNativePreparationInput.model_validate(native_preparation())
    prepared = MaterialNativePreparedArtifact.model_validate(native_prepared())
    require_native_material_checkpoint_chain(
        intake,
        preparation=preparation,
        prepared=prepared,
        intake_pointer=preparation.intake_manifest,
    )
    value = native_prepared()
    value["native_bundle"]["artifact_revision_id"] = "rev_" + "0" * 32
    wrong = MaterialNativePreparedArtifact.model_validate(rehash(value, "prepared_sha256"))
    with pytest.raises(ValueError, match="CHECKPOINT_BUNDLE_MISMATCH"):
        require_native_material_checkpoint_chain(intake, preparation=preparation, prepared=wrong)
    value = native_preparation()
    value["material_revision_id"] = "materialrev_" + "0" * 32
    wrong = MaterialNativePreparationInput.model_validate(rehash(value))
    with pytest.raises(ValueError, match="CHECKPOINT_CHAIN_MISMATCH"):
        require_native_material_checkpoint_chain(intake, preparation=wrong)


def test_workbook_bundle_is_checked_before_any_discovery_identity_exists():
    workbook = workbook_document()
    data = native_exam_bundle()
    data["items"][0]["row_sha256"] = content_sha256(
        workbook.worksheets[0].rows[0].model_dump(mode="json")
    )
    bundle = MaterialNativeExamBundle.model_validate(rehash(data, "bundle_sha256"))
    require_native_exam_bundle_workbook(bundle, workbook)
    assert not {"material_id", "unit_key"}.intersection(bundle.model_dump())
    data["items"][0]["source_metadata"]["external_number"] = "12345"
    invalid = MaterialNativeExamBundle.model_validate(rehash(data, "bundle_sha256"))
    with pytest.raises(ValueError, match="WORKBOOK_ROW_MISMATCH"):
        require_native_exam_bundle_workbook(invalid, workbook)
