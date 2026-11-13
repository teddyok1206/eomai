"""Native files bind original sources and row evidence without inventing external numbers."""

from copy import deepcopy
from pathlib import Path

import pytest
from eom_catalog_contracts.material_item_lineage import MaterialImportedItemMetadata
from eom_catalog_contracts.material_learning import MaterialExtractionWork
from eom_catalog_contracts.material_native_files import (
    MATERIAL_NATIVE_BINDING_REF,
    MATERIAL_NATIVE_METADATA_REF,
    NATIVE_ITEM_DOCUMENT_REF,
    NATIVE_ITEM_SPLIT_EVIDENCE_REF,
    NATIVE_WORKBOOK_MANIFEST_REF,
    MaterialImportedNativeItemMetadata,
    MaterialNativeItemBinding,
    material_native_printed_number,
    material_native_source_identity,
    require_material_native_binding_for_work,
    require_material_native_metadata_binding,
    require_material_native_split_result,
    require_material_native_workbook_rows,
)
from eom_catalog_contracts.native_exam_intake import NativeExamWorkbookDocument
from eom_catalog_contracts.validation import validate_contract
from eom_hwpx_contracts.native_item_split import NativeItemSplitResult
from eom_identifiers import content_sha256
from jsonschema import ValidationError as SchemaError
from pydantic import ValidationError

from tests.unit.test_material_learning_contracts import (
    extraction_work,
    member,
    rehash,
    source,
    unit,
)

ROOT = Path(__file__).resolve().parents[2]


def pointer(path, media, schema):
    return {**member(path, media), "schema_ref": schema}


def binding_data():
    question = dict(
        source_role="MAIN",
        original_source_sha256="sha256:" + "a" * 64,
        native_source_sha256="sha256:" + "b" * 64,
        document=pointer(
            "items/1/question.hwpx", "application/vnd.hancom.hwpx", NATIVE_ITEM_DOCUMENT_REF
        ),
        split_evidence=pointer(
            "items/1/question.json", "application/json", NATIVE_ITEM_SPLIT_EVIDENCE_REF
        ),
        split_plan_sha256="sha256:" + "c" * 64,
        ranges=[
            dict(
                section_member="Contents/section0.xml",
                start_paragraph=10,
                end_paragraph=15,
                subtree_sha256="sha256:" + "d" * 64,
            )
        ],
    )
    solution = deepcopy(question)
    solution.update(source_role="SOLUTIONS", original_source_sha256="sha256:" + "e" * 64)
    solution["document"]["member_path"] = "items/1/solution.hwpx"
    solution["split_evidence"]["member_path"] = "items/1/solution.json"
    value = dict(
        schema_version="material-native-item-binding/1.0",
        material_id="material_" + "5" * 32,
        material_revision_id="materialrev_" + "6" * 32,
        unit_key="materialunit_" + "8" * 32,
        source_namespace="native-exam-corpus",
        exam_key="exam-01",
        item_number=1,
        printed_label="01번",
        question=question,
        solution=solution,
        workbook=dict(
            workbook=pointer(
                "source/metadata.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "eom://schemas/material-learning/native-exam-workbook-source/1.0",
            ),
            parsed_workbook=pointer(
                "workbook/manifest.json", "application/json", NATIVE_WORKBOOK_MANIFEST_REF
            ),
            worksheet_name="실장님_등록용",
            row_number=3,
            row_sha256="sha256:" + "f" * 64,
        ),
        source_metadata=dict(
            external_number=None,
            original_unit=" 단원 원문 ",
            original_classification="통합과학 - 창작",
            source_name="예시_01회_01번",
        ),
    )
    return rehash(value, "binding_sha256")


def native_work():
    value = extraction_work()
    main = source("MAIN")
    solution = source("SOLUTIONS")
    for target, letter in ((main, "a"), (solution, "e")):
        target.update(actual_format="HWP", original_filename=letter + ".hwp")
        target["original"] = member("source/original.hwp", "application/vnd.hancom.hwp")
        target["original"]["sha256"] = "sha256:" + letter * 64
        target["office_catalog"] = member(
            "office/catalog.json", "application/json", "office-picture-use-catalog/1.0"
        )
    value["sources"] = [main, solution]
    value["pages"][1]["source_role"] = "SOLUTIONS"
    value["solutions"] = [unit("SOLUTION", "1.", 32)]
    value["solutions"][0]["anchors"][0]["source_role"] = "SOLUTIONS"
    return rehash(value)


def split_result(binding):
    file = binding.question
    return NativeItemSplitResult(
        source_sha256=file.native_source_sha256,
        plan_sha256=file.split_plan_sha256,
        source_role="MAIN",
        item_number=1,
        ranges=file.ranges,
        paragraph_sha256=("sha256:" + "1" * 64,),
        context_sha256=(),
        binary_sha256=(),
        counts=dict(paragraphs=1, tables=0, equations=0, pictures=0),
        output_sha256=file.document.sha256,
        output_size_bytes=file.document.bytes,
    )


def metadata_data():
    value = dict(
        schema_version="material-imported-native-item-metadata/2.0",
        item_type_key="uploaded-material-item",
        source_kind="EXTERNAL",
        material_id="material_" + "5" * 32,
        material_revision_id="materialrev_" + "6" * 32,
        unit_key="materialunit_" + "8" * 32,
        title="원문 문항",
        source_filename="시험지.hwp",
        printed_label="1",
        section_path=["원본 단원"],
        physical_pages=[31],
        lineage_sha256="sha256:" + "3" * 64,
        approval_basis="SOURCE_IMPORT_AUTOMATION_NOT_SCIENTIFIC_VERIFICATION",
        native_binding=pointer(
            "native/binding.json", "application/json", MATERIAL_NATIVE_BINDING_REF
        ),
        item_number=1,
        **binding_data()["source_metadata"],
    )
    return value


def test_binding_is_schema_valid_frozen_pointer_only_and_preserves_raw_metadata():
    value = binding_data()
    validate_contract("material-native-item-binding-v1", value)
    parsed = MaterialNativeItemBinding.model_validate(value)
    assert parsed.source_metadata.external_number is None
    assert parsed.source_metadata.original_unit == " 단원 원문 "
    assert parsed.source_metadata.original_classification == "통합과학 - 창작"
    assert len(parsed.model_dump_json()) < 8000
    assert {"cells", "body", "image_bytes", "password"}.isdisjoint(parsed.model_dump())
    with pytest.raises(ValidationError):
        parsed.item_number = 2


@pytest.mark.parametrize("label", ["1", "01", "1.", "1)", "1번", " 01 번 "])
def test_explicit_numeric_label_variants(label):
    assert material_native_printed_number(label) == 1


@pytest.mark.parametrize(
    "label", [None, "", "예제1", "문항 1", "1. 제목", "1-2", "0", "10001", "\uff11"]
)
def test_unrelated_labels_are_not_guessed(label):
    with pytest.raises(ValueError, match="PRINTED_NUMBER_INVALID"):
        material_native_printed_number(label)


@pytest.mark.parametrize(
    "field,value",
    [
        ("material_revision_id", "materialrev_" + "0" * 32),
        ("unit_key", "materialunit_" + "0" * 32),
        ("printed_label", "2"),
    ],
)
def test_work_binding_rejects_wrong_material_revision_unit_and_number(field, value):
    binding = MaterialNativeItemBinding.model_validate(binding_data())
    work = native_work()
    work[field] = value if field != "printed_label" else work.get(field)
    if field == "printed_label":
        work.pop(field)
        work["question"]["printed_label"] = value
    with pytest.raises(ValueError, match="WORK_BINDING_MISMATCH"):
        require_material_native_binding_for_work(
            binding, MaterialExtractionWork.model_validate(rehash(work))
        )


def test_work_binding_requires_exact_original_native_question_and_solution():
    binding = MaterialNativeItemBinding.model_validate(binding_data())
    work = native_work()
    require_material_native_binding_for_work(binding, MaterialExtractionWork.model_validate(work))
    work["sources"][1]["original"]["sha256"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="ORIGINAL_SOURCE_MISMATCH"):
        require_material_native_binding_for_work(
            binding, MaterialExtractionWork.model_validate(rehash(work))
        )


def test_work_binding_never_treats_answer_key_or_other_question_solution_as_selected():
    binding = MaterialNativeItemBinding.model_validate(binding_data())
    work = native_work()
    work["solutions"][0]["printed_label"] = "2"
    with pytest.raises(ValueError, match="SOLUTION_BINDING_MISMATCH"):
        require_material_native_binding_for_work(
            binding, MaterialExtractionWork.model_validate(rehash(work))
        )
    work["solutions"][0]["kind"] = "ANSWER_KEY"
    with pytest.raises(ValueError, match="SOLUTION_BINDING_MISMATCH"):
        require_material_native_binding_for_work(
            binding, MaterialExtractionWork.model_validate(rehash(work))
        )


@pytest.mark.parametrize("field", ["source_sha256", "plan_sha256", "output_sha256"])
def test_split_receipt_requires_exact_source_plan_and_output_hash(field):
    binding = MaterialNativeItemBinding.model_validate(binding_data())
    result = split_result(binding)
    require_material_native_split_result(binding.question, result, item_number=1)
    bad = result.model_dump(mode="json")
    bad[field] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="SPLIT_EVIDENCE_MISMATCH"):
        require_material_native_split_result(
            binding.question, NativeItemSplitResult.model_validate(bad), item_number=1
        )


def test_identity_ignores_later_workbook_revision_number_and_metadata_but_not_source():
    first = MaterialNativeItemBinding.model_validate(binding_data())
    changed = binding_data()
    changed["workbook"]["workbook"]["sha256"] = "sha256:" + "0" * 64
    changed["workbook"]["row_sha256"] = "sha256:" + "0" * 64
    changed["source_metadata"]["external_number"] = "12345"
    changed["source_metadata"]["original_unit"] = "정정된 소속 단원"
    changed["material_revision_id"] = "materialrev_" + "0" * 32
    second = MaterialNativeItemBinding.model_validate(rehash(changed, "binding_sha256"))
    assert first.binding_sha256 != second.binding_sha256
    assert material_native_source_identity(first) == material_native_source_identity(second)
    changed["source_namespace"] = "other-corpus"
    third = MaterialNativeItemBinding.model_validate(rehash(changed, "binding_sha256"))
    assert material_native_source_identity(first) != material_native_source_identity(third)


@pytest.mark.parametrize("location", ["document", "split_evidence"])
def test_binding_rejects_unsafe_or_mislabeled_members(location):
    value = binding_data()
    value["question"][location]["member_path"] = "../escape.hwpx"
    with pytest.raises(ValueError):
        MaterialNativeItemBinding.model_validate(rehash(value, "binding_sha256"))
    value = binding_data()
    value["question"][location]["media_type"] = "application/pdf"
    with pytest.raises(ValueError, match="FILE_BINDING_INVALID"):
        MaterialNativeItemBinding.model_validate(rehash(value, "binding_sha256"))


def test_native_metadata_is_separate_from_v1_and_exactly_matches_binding():
    binding = MaterialNativeItemBinding.model_validate(binding_data())
    value = metadata_data()
    validate_contract("material-learning-item-metadata-v2", value)
    metadata = MaterialImportedNativeItemMetadata.model_validate(value)
    require_material_native_metadata_binding(metadata, binding)
    assert metadata.source_kind == "EXTERNAL"
    assert metadata.original_classification == "통합과학 - 창작"
    with pytest.raises(ValueError):
        MaterialImportedItemMetadata.model_validate(value)
    with pytest.raises(SchemaError):
        validate_contract("material-learning-item-metadata-v1", value)
    value["original_unit"] = "다른 단원"
    with pytest.raises(ValueError, match="METADATA_BINDING_MISMATCH"):
        require_material_native_metadata_binding(
            MaterialImportedNativeItemMetadata.model_validate(value), binding
        )
    assert MATERIAL_NATIVE_METADATA_REF.endswith("/2.0")


def test_hash_changes_are_not_accepted_and_resource_mirrors_are_exact():
    value = binding_data()
    value["source_metadata"]["external_number"] = "12345"
    with pytest.raises(ValueError, match="ITEM_BINDING_INVALID"):
        MaterialNativeItemBinding.model_validate(value)
    for name in ("native-item-binding-v1", "item-metadata-v2"):
        canonical = ROOT / "schemas/material-learning" / (name + ".schema.json")
        resource = (
            ROOT
            / "packages/catalog_contracts/eom_catalog_contracts/resources/material-learning"
            / (name + ".schema.json")
        )
        assert canonical.read_bytes() == resource.read_bytes()


def workbook_document():
    row = dict(
        row_number=3,
        question_number=1,
        external_number=None,
        unit_raw=" 단원 원문 ",
        unit_normalized="단원 원문",
        source_label="예시_01회_01번",
    )
    columns = (
        ("A", "문항번호", "QUESTION_NUMBER", "1"),
        ("B", "단원", "UNIT", row["unit_raw"]),
        ("C", "출처(파일명)", "SOURCE_LABEL", row["source_label"]),
        ("D", "분류", "CLASSIFICATION", "통합과학 - 창작"),
    )
    cells = []
    for column, header, _, value in columns:
        for number, text in ((2, header), (3, value)):
            cells.append(
                dict(
                    reference=f"{column}{number}",
                    value=text,
                    raw_value=text,
                    storage_type="inlineStr",
                    formula=None,
                    formula_attributes=[],
                )
            )
    return NativeExamWorkbookDocument.model_validate(
        dict(
            sha256="sha256:" + "a" * 64,
            bytes=100,
            worksheets=[
                dict(
                    name="실장님_등록용",
                    member_path="xl/worksheets/sheet1.xml",
                    header_row=2,
                    external_number_basis="ABSENT",
                    columns=[dict(column=c, header=h, semantic=s) for c, h, s, _ in columns],
                    cells=cells,
                    rows=[row],
                )
            ],
        )
    )


def workbook_binding():
    document = workbook_document()
    value = binding_data()
    value["workbook"]["row_sha256"] = content_sha256(
        document.worksheets[0].rows[0].model_dump(mode="json")
    )
    return MaterialNativeItemBinding.model_validate(rehash(value, "binding_sha256")), document


def test_exact_workbook_row_uses_original_units_and_classification_not_inference():
    binding, workbook = workbook_binding()
    require_material_native_workbook_rows((binding,), workbook)
    changed = binding.model_dump(mode="json")
    changed["source_metadata"]["original_classification"] = "AI"
    with pytest.raises(ValueError, match="WORKBOOK_CLASSIFICATION_MISMATCH"):
        require_material_native_workbook_rows(
            (MaterialNativeItemBinding.model_validate(rehash(changed, "binding_sha256")),), workbook
        )


@pytest.mark.parametrize(
    "field,value",
    [("row_number", 4), ("worksheet_name", "다른 시트"), ("row_sha256", "sha256:" + "0" * 64)],
)
def test_workbook_row_pointer_cannot_silently_resolve_another_row(field, value):
    binding, workbook = workbook_binding()
    changed = binding.model_dump(mode="json")
    changed["workbook"][field] = value
    with pytest.raises(ValueError, match="WORKBOOK_ROW_MISMATCH"):
        require_material_native_workbook_rows(
            (MaterialNativeItemBinding.model_validate(rehash(changed, "binding_sha256")),), workbook
        )


def test_workbook_duplicate_unit_and_changed_original_bytes_fail_closed():
    binding, workbook = workbook_binding()
    with pytest.raises(ValueError, match="WORKBOOK_UNIT_DUPLICATED"):
        require_material_native_workbook_rows((binding, binding), workbook)
    changed = binding.model_dump(mode="json")
    changed["workbook"]["workbook"]["sha256"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="WORKBOOK_ROW_MISMATCH"):
        require_material_native_workbook_rows(
            (MaterialNativeItemBinding.model_validate(rehash(changed, "binding_sha256")),), workbook
        )
