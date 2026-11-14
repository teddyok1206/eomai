"""Native visual work changes only the catalog and deterministic bounded guidance."""

from copy import deepcopy
from math import ceil, log2
from types import SimpleNamespace

import pytest
from eom_catalog_contracts.material_learning import MaterialArtifactMember, MaterialExtractionWork
from eom_catalog_contracts.material_learning_intake import MaterialLearningIntakeManifest
from eom_catalog_contracts.material_learning_preparation import MaterialPreparedArtifact
from eom_catalog_contracts.material_native_intake import (
    MaterialNativeExamBundle,
    MaterialNativeLearningIntakeManifest,
)
from eom_catalog_contracts.material_native_visual_preparation import (
    MaterialNativeVisualPreparedArtifact,
)
from eom_catalog_contracts.material_native_visual_selection import material_native_visual_guidance
from eom_catalog_contracts.material_native_visual_work import (
    material_native_question_visual_scope,
    material_visual_work_instructions,
    material_visual_work_sources,
    require_material_native_visual_bundle,
)
from eom_catalog_service import material_learning_work as owner
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_workflow.material_learning_plan import MaterialDiscoveryWindow, PlannedMaterialUnit

from tests.unit.test_material_learning_contracts import member, rehash
from tests.unit.test_material_native_files import native_work
from tests.unit.test_material_native_intake import native_exam_bundle, native_intake
from tests.unit.test_material_native_visual_preparation import base_prepared, visual_prepared


def prepared_and_intake(version):
    intake = native_intake()
    if version == 3:
        prepared = MaterialNativeVisualPreparedArtifact.model_validate(visual_prepared())
    elif version == 2:
        prepared = base_prepared()
    else:
        value = base_prepared().model_dump(mode="json")
        value.pop("native_bundle")
        value["schema_version"] = "material-learning-prepared/1.0"
        value["intake_manifest"]["schema_ref"] = "eom://schemas/material-learning/intake/1.0"
        prepared = MaterialPreparedArtifact.model_validate(rehash(value, "prepared_sha256"))
        intake.pop("native_bundle")
        intake["schema_version"] = "material-learning-intake/1.0"
    intake["upload"]["additional_instructions"] = (
        "원본 요구를 빠뜨리지 않는다.\n끝 공백도 보존한다.  "
    )
    model = MaterialLearningIntakeManifest if version == 1 else MaterialNativeLearningIntakeManifest
    return prepared, model.model_validate(intake)


def work_service(monkeypatch, version=3):
    prepared, intake = prepared_and_intake(version)
    original = MaterialExtractionWork.model_validate(native_work())
    service = owner.MaterialLearningWorkService(object(), object())
    calls = []

    def read_pages(_artifacts, source, physical_pages):
        calls.append((source, physical_pages))
        expected = next(base for base in prepared.sources if base.source_role == source.source_role)
        assert source == expected
        selected = []
        for page in original.pages:
            if page.source_role != source.source_role or page.physical_page not in physical_pages:
                continue

            def input_page(*, input_index, source_role, actual=page):
                return actual.model_copy(
                    update={"input_index": input_index, "source_role": source_role}
                )

            selected.append(SimpleNamespace(page=page, input_page=input_page))
        return SimpleNamespace(
            bundle=SimpleNamespace(profile=SimpleNamespace(profile_sha256=prepared.profile_sha256)),
            pages=tuple(selected),
        )

    monkeypatch.setattr(owner, "read_material_source_pages", read_pages)
    question = PlannedMaterialUnit(
        unit_key=original.unit_key,
        ordinal=1,
        discovery_task_id="materialtask_" + "8" * 32,
        source=prepared.sources[0],
        unit=original.question,
        solution_unit_keys=(),
        issue_codes=(),
    )
    return service, prepared, intake, original, question, calls


def extracted_work(monkeypatch, version=3):
    service, prepared, intake, original, question, calls = work_service(monkeypatch, version)
    work = service.extraction(
        task_id=original.task_id,
        prepared=prepared,
        intake=intake,
        question=question,
        solutions=original.solutions,
    )
    return service, prepared, intake, work, calls


@pytest.mark.parametrize("version", [1, 2])
def test_legacy_sources_and_instructions_are_exact_original_values(monkeypatch, version):
    _, prepared, intake, work, calls = extracted_work(monkeypatch, version)
    assert material_visual_work_sources(prepared) is prepared.sources
    assert work.sources == prepared.sources
    assert work.additional_instructions == intake.upload.additional_instructions
    assert material_native_question_visual_scope(prepared, printed_label=None) is None
    assert len(calls) == 2


def test_native3_changes_only_catalog_and_preserves_base_page_resolution(monkeypatch):
    _, prepared, intake, work, calls = extracted_work(monkeypatch)
    assert work.pages == MaterialExtractionWork.model_validate(native_work()).pages
    for actual, base in zip(work.sources, prepared.sources, strict=True):
        before, after = base.model_dump(mode="json"), actual.model_dump(mode="json")
        before.pop("office_catalog")
        after.pop("office_catalog")
        assert after == before
    assert work.sources[0].office_catalog == prepared.catalog_supplements[0].catalog
    assert work.sources[0].office_catalog != prepared.sources[0].office_catalog
    assert work.sources[1] == prepared.sources[1]
    assert [source for source, _ in calls] == list(prepared.sources)
    assert work.additional_instructions == (
        intake.upload.additional_instructions
        + "\n\n"
        + material_native_visual_guidance(prepared.question_visual_scopes[0])
    )
    assert work.input_sha256 == content_sha256(
        work.model_dump(mode="json", exclude={"input_sha256"})
    )


def test_discovery_has_no_question_hint_and_still_reads_base_pages(monkeypatch):
    service, prepared, intake, original, _, calls = work_service(monkeypatch)
    work = service.discovery(
        task_id=original.task_id,
        prepared=prepared,
        intake=intake,
        window=MaterialDiscoveryWindow("MAIN", 31, 31, 31, 31),
    )
    assert work.additional_instructions == intake.upload.additional_instructions
    assert work.sources == material_visual_work_sources(prepared)
    assert calls == [(prepared.sources[0], (31,))]


@pytest.mark.parametrize("count", [1, 25, 10000])
def test_scope_lookup_is_indexed_not_a_linear_scan(count):
    prepared = MaterialNativeVisualPreparedArtifact.model_validate(visual_prepared())
    prototype = prepared.question_visual_scopes[0]
    reads = []

    class IndexedScopes(tuple):
        def __iter__(self):
            raise AssertionError("scope lookup must not scan the tuple")

        def __getitem__(self, index):
            reads.append(index)
            return super().__getitem__(index)

    scopes = IndexedScopes(
        tuple(
            prototype.model_copy(update={"item_number": number}) for number in range(1, count + 1)
        )
    )
    instrumented = prepared.model_copy(update={"question_visual_scopes": scopes})
    assert (
        material_native_question_visual_scope(instrumented, printed_label=f"{count}번").item_number
        == count
    )
    assert len(reads) <= ceil(log2(count + 1)) + 2


@pytest.mark.parametrize("label", [None, "", "문항 1", "1. 정답 : ③ (ㄱ)", "2"])
def test_missing_question_number_or_scope_does_not_fall_back_to_another_picture(label):
    prepared = MaterialNativeVisualPreparedArtifact.model_validate(visual_prepared())
    with pytest.raises(ValueError, match=r"PRINTED_NUMBER_INVALID|QUESTION_SCOPE_MISSING"):
        material_native_question_visual_scope(prepared, printed_label=label)


def test_guidance_preserves_all_original_instructions_with_exact_character_boundary():
    scope = MaterialNativeVisualPreparedArtifact.model_validate(
        visual_prepared()
    ).question_visual_scopes[0]
    suffix = "\n\n" + material_native_visual_guidance(scope)
    original = "가" * (8000 - len(suffix))
    result = material_visual_work_instructions(source_instructions=original, scope=scope)
    assert result == original + suffix and len(result) == 8000
    with pytest.raises(ValueError, match="GUIDANCE_TOO_LONG"):
        material_visual_work_instructions(source_instructions=original + "나", scope=scope)
    assert material_visual_work_instructions(source_instructions=original, scope=None) == original


def test_published_work_pins_scope_guidance_in_its_canonical_content_hash(monkeypatch):
    service, _, _, work, _ = extracted_work(monkeypatch)
    captures, authorized = [], []

    def publish(_artifacts, _settings, actual, **kwargs):
        encoded = canonical_json_bytes(actual.model_dump(mode="json"))
        captures.append((actual, encoded, kwargs))
        return MaterialArtifactMember.model_validate(
            {
                **member("material/work.json", "application/json"),
                "schema_ref": kwargs["schema_ref"],
                "sha256": content_sha256(actual.model_dump(mode="json")),
                "bytes": len(encoded),
            }
        )

    monkeypatch.setattr(owner, "publish_material_metadata", publish)
    pointer = service.publish(work, authorize=lambda: authorized.append(True))
    assert captures[0][0] == work
    assert captures[0][2]["idempotency_key"] == "material-task-input:" + work.task_id
    assert pointer.sha256 == content_sha256(work.model_dump(mode="json"))
    assert pointer.bytes == len(captures[0][1]) and len(authorized) == 2
    changed = deepcopy(work.model_dump(mode="json"))
    changed["additional_instructions"] += "other use"
    assert content_sha256(rehash(changed)) != pointer.sha256


@pytest.mark.parametrize("count", [1, 25])
def test_scope_bundle_check_pins_every_number_document_and_receipt(count):
    prepared = MaterialNativeVisualPreparedArtifact.model_validate(visual_prepared(count))
    body = native_exam_bundle()
    prototype = body["items"][0]
    body["items"] = []
    for scope in prepared.question_visual_scopes:
        item = deepcopy(prototype)
        item.update(
            item_number=scope.item_number,
            printed_label=str(scope.item_number),
            row_number=scope.item_number + 2,
        )
        item["question"]["document"] = scope.question_document.model_dump(mode="json")
        item["question"]["split_evidence"] = scope.split_evidence.model_dump(mode="json")
        body["items"].append(item)
    bundle = MaterialNativeExamBundle.model_validate(rehash(body, "bundle_sha256"))
    require_material_native_visual_bundle(prepared, bundle)


@pytest.mark.parametrize(
    "case",
    [
        "number",
        "question_hash",
        "question_revision",
        "evidence_hash",
        "evidence_revision",
        "missing_item",
    ],
)
def test_scope_cannot_redirect_question_or_receipt_inside_a_valid_native_bundle(case):
    body = native_exam_bundle()
    if case == "missing_item":
        prepared_body = visual_prepared(2)
    else:
        prepared_body = visual_prepared()
        scope = prepared_body["question_visual_scopes"][0]
        if case == "number":
            scope["item_number"] = 2
        else:
            pointer_name = "question_document" if case.startswith("question") else "split_evidence"
            field = "sha256" if case.endswith("hash") else "artifact_revision_id"
            scope[pointer_name][field] = (
                "sha256:" + "0" * 64 if field == "sha256" else "rev_" + "0" * 32
            )
    prepared = MaterialNativeVisualPreparedArtifact.model_validate(
        rehash(prepared_body, "prepared_sha256")
    )
    bundle = MaterialNativeExamBundle.model_validate(body)
    with pytest.raises(ValueError, match="BUNDLE_SCOPE_MISMATCH"):
        require_material_native_visual_bundle(prepared, bundle)
