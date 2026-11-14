"""Native question/solution inventory constrains model discovery before task creation."""

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from types import MappingProxyType, SimpleNamespace

import pytest
from eom_catalog_contracts.material_learning import MaterialExtractionWork
from eom_catalog_contracts.material_learning_intake import MaterialLearningIntakeManifest
from eom_catalog_contracts.material_native_intake import (
    MaterialNativeExamBundle,
    MaterialNativeLearningIntakeManifest,
)
from eom_catalog_service import material_learning_coordinator as owner
from eom_catalog_service.material_learning_coordinator import (
    MaterialDiscoveryPlan,
    MaterialLearningCoordinator,
    bind_native_material_discovery_plan,
)
from eom_identifiers import content_sha256
from eom_workflow.material_learning_plan import PlannedMaterialUnit

from tests.unit.test_material_native_files import native_work
from tests.unit.test_material_native_intake import native_exam_bundle, native_intake


def plan():
    work = MaterialExtractionWork.model_validate(native_work())
    source = bundle()
    sources = (
        work.sources[0].model_copy(update={"original": source.main_original}),
        work.sources[1].model_copy(update={"original": source.solutions_original}),
    )
    question = PlannedMaterialUnit(
        "question-one", 1, "discovery-main", sources[0], work.question, ("solution-one",), ()
    )
    solution = PlannedMaterialUnit(
        "solution-one", 2, "discovery-solutions", sources[1], work.solutions[0], (), ()
    )
    return MaterialDiscoveryPlan(
        "materialrun_" + "1" * 32,
        (),
        MappingProxyType({question.unit_key: question, solution.unit_key: solution}),
        MappingProxyType({}),
    )


def bundle():
    return MaterialNativeExamBundle.model_validate(native_exam_bundle())


def test_exact_native_pair_accepts_numeric_label_variants_not_external_numbers():
    value = plan()
    values = dict(value.by_unit)
    question = values["question-one"]
    values[question.unit_key] = replace(
        question, unit=question.unit.model_copy(update={"printed_label": "1번"})
    )
    bound = bind_native_material_discovery_plan(replace(value, by_unit=values), bundle())
    assert bound.by_unit[question.unit_key].solution_unit_keys == ("solution-one",)
    assert bundle().items[0].source_metadata.external_number is None


def test_answer_heading_is_not_accepted_as_a_question_printed_label():
    value = plan()
    values = dict(value.by_unit)
    question = values["question-one"]
    values[question.unit_key] = replace(
        question,
        unit=question.unit.model_copy(update={"printed_label": "1. 정답 : ③ (ㄱ, ㄴ)"}),
    )
    with pytest.raises(ValueError, match="MATERIAL_NATIVE_DISCOVERY_NUMBER_INVALID"):
        bind_native_material_discovery_plan(replace(value, by_unit=values), bundle())


def test_twenty_five_native_pairs_accept_twenty_one_answer_headings_and_four_plain_labels():
    # Actual heading forms from the first exam; no question text or model result is copied.
    labels = (
        "1. 정답 : ③ (ㄱ, ㄴ)",
        "2. 정답 : ② (ㄴ)",
        "3. 정답 : ⑤ (ㄱ, ㄴ, ㄷ)",
        "4. 정답 : ③ (ㄷ)",
        "5. 정답 : ② (ㄴ)",
        "6. 정답 : ③ (ㄱ, ㄴ)",
        "7. 정답 : ④ (ㄴ, ㄷ)",
        "8. 정답 : ⑤ (ㄴ, ㄷ)",
        "9. 정답 : ③ (ㄱ, ㄴ)",
        "10. 정답 : ③ (ㄱ, ㄴ)",
        "11. 정답 : ② (ㄴ)",
        "12. 정답 : ① (ㄱ)",
        "13. 정답 : ④ (ㄴ, ㄷ)",
        "14. 정답 : ① (ㄱ)",
        "15. 정답 : ① (ㄱ)",
        "16. 정답 : ① (ㄴ)",
        "17. 정답 : ① (ㄱ, ㄷ)",
        "18. 정답 : ⑤ (ㄴ, ㄷ)",
        "19. 정답 : ③ (ㄷ)",
        "20. 정답 : ③ (ㄱ, ㄴ)",
        "21. 정답 : ④ (ㄴ, ㄷ)",
        "22.",
        "23.",
        "24.",
        "25.",
    )
    value = plan()
    question, solution = value.by_unit["question-one"], value.by_unit["solution-one"]
    items, units = [], {}
    original = native_exam_bundle()
    for number, label in enumerate(labels, 1):
        item = deepcopy(original["items"][0])
        item.update(item_number=number, printed_label=f"{number}.", row_number=number + 2)
        for role, filename in (("question", "question.hwpx"), ("solution", "solution.hwpx")):
            item[role]["document"]["member_path"] = f"items/{number}/{filename}"
        items.append(item)
        for base, key, printed_label in (
            (question, f"question-{number}", f"{number}."),
            (solution, f"solution-{number}", label),
        ):
            units[key] = replace(
                base,
                unit_key=key,
                ordinal=number * 2 - (base is question),
                unit=base.unit.model_copy(update={"printed_label": printed_label}),
                solution_unit_keys=(),
            )
    original["items"] = items
    original["bundle_sha256"] = content_sha256(
        {key: child for key, child in original.items() if key != "bundle_sha256"}
    )
    native = MaterialNativeExamBundle.model_validate(original)
    # Pair by explicit source+number, not arrival order or label-string equality.
    discovered = replace(value, by_unit=dict(reversed(tuple(units.items()))))
    before = {key: unit.unit.model_dump(mode="json") for key, unit in discovered.by_unit.items()}
    bound = bind_native_material_discovery_plan(discovered, native)
    for number, label in enumerate(labels, 1):
        assert bound.by_unit[f"question-{number}"].solution_unit_keys == (f"solution-{number}",)
        assert bound.by_unit[f"solution-{number}"].unit.printed_label == label
    assert {key: unit.unit.model_dump(mode="json") for key, unit in bound.by_unit.items()} == before


@pytest.mark.parametrize("missing", ["question-one", "solution-one"])
def test_missing_model_question_or_solution_never_becomes_partial_success(missing):
    value = plan()
    values = dict(value.by_unit)
    values.pop(missing)
    with pytest.raises(ValueError, match="MATERIAL_NATIVE_DISCOVERY_COVERAGE_MISMATCH"):
        bind_native_material_discovery_plan(replace(value, by_unit=values), bundle())


@pytest.mark.parametrize("duplicate", ["question-one", "solution-one"])
def test_different_regions_with_same_printed_number_are_not_two_source_items(duplicate):
    value = plan()
    values = dict(value.by_unit)
    original = values[duplicate]
    values["duplicate"] = replace(original, unit_key="duplicate", ordinal=3)
    with pytest.raises(ValueError, match="MATERIAL_NATIVE_DISCOVERY_NUMBER_DUPLICATED"):
        bind_native_material_discovery_plan(replace(value, by_unit=values), bundle())


@pytest.mark.parametrize(
    "links", [(), ("question-one",), ("unknown",), ("solution-one", "solution-one")]
)
def test_native_original_pair_replaces_obsolete_generic_pairing_only_after_exact_coverage(links):
    value = plan()
    values = dict(value.by_unit)
    question = values["question-one"]
    values[question.unit_key] = replace(
        question,
        solution_unit_keys=links,
        issue_codes=(
            "AMBIGUOUS_SOURCE_SOLUTION",
            "NO_SOURCE_SOLUTION_INDEPENDENT_SOLUTION_REQUIRED",
            "OTHER_WARNING",
        ),
    )
    bound = bind_native_material_discovery_plan(replace(value, by_unit=values), bundle())
    assert bound.by_unit[question.unit_key].solution_unit_keys == ("solution-one",)
    assert bound.by_unit[question.unit_key].issue_codes == ("OTHER_WARNING",)
    assert bound.by_unit[question.unit_key].unit == question.unit
    assert bound.by_unit["solution-one"] == values["solution-one"]


@pytest.mark.parametrize(
    "case,code",
    [
        ("label", "NUMBER_INVALID"),
        ("continuation", "REGION_INCOMPLETE"),
        ("role", "ROLE_MISMATCH"),
        ("unexpected_number", "COVERAGE_MISMATCH"),
    ],
)
def test_native_coverage_rejects_incomplete_unexpected_or_wrong_role_model_units(case, code):
    value = plan()
    values = dict(value.by_unit)
    question = values["question-one"]
    if case == "role":
        changed = replace(question, source=values["solution-one"].source)
    else:
        update = {
            "label": {"printed_label": "문항 하나"},
            "continuation": {"continuation": "TO_NEXT"},
            "unexpected_number": {"printed_label": "2"},
        }[case]
        changed = replace(question, unit=question.unit.model_copy(update=update))
    values[question.unit_key] = changed
    with pytest.raises(ValueError, match="MATERIAL_NATIVE_DISCOVERY_" + code):
        bind_native_material_discovery_plan(replace(value, by_unit=values), bundle())


def test_answer_key_can_supplement_but_not_replace_native_detailed_solution():
    value = plan()
    values = dict(value.by_unit)
    solution = values["solution-one"]
    answer = replace(
        solution,
        unit_key="answer-key",
        ordinal=3,
        unit=solution.unit.model_copy(update={"kind": "ANSWER_KEY"}),
    )
    values[answer.unit_key] = answer
    question = values["question-one"]
    values[question.unit_key] = replace(question, solution_unit_keys=("answer-key", "solution-one"))
    bound = bind_native_material_discovery_plan(replace(value, by_unit=values), bundle())
    assert bound.by_unit[question.unit_key].solution_unit_keys == ("solution-one",)


def test_native_pair_is_one_verified_exam_not_generic_section_heading_or_literal_label_match():
    value = plan()
    values = dict(value.by_unit)
    question, solution = values["question-one"], values["solution-one"]
    values[question.unit_key] = replace(
        question,
        solution_unit_keys=(),
        unit=question.unit.model_copy(
            update={"section_path": ("제1회 문제",), "printed_label": "1번"}
        ),
    )
    values[solution.unit_key] = replace(
        solution,
        unit=solution.unit.model_copy(
            update={"section_path": ("제1회 정답 및 해설",), "printed_label": "1."}
        ),
    )
    bound = bind_native_material_discovery_plan(replace(value, by_unit=values), bundle())
    assert bound.by_unit[question.unit_key].solution_unit_keys == (solution.unit_key,)
    assert bound.by_unit[question.unit_key].unit == values[question.unit_key].unit
    assert bound.by_unit[solution.unit_key] == values[solution.unit_key]


def test_coordinator_validates_native_bundle_once_per_run_restart_and_before_tasks(monkeypatch):
    writes = []

    class Sessions:
        @contextmanager
        def __call__(self):
            yield SimpleNamespace(scalar=lambda *args: None)

        begin = __call__

    coordinator = object.__new__(MaterialLearningCoordinator)
    coordinator.sessions = Sessions()
    coordinator.artifacts = object()
    coordinator.authorize = lambda claim: None
    value = plan()
    broken = replace(value, by_unit={"question-one": value.by_unit["question-one"]})
    coordinator._plan = None
    checks = []

    def read(*args, **kwargs):
        checks.append(kwargs["operator_id"])
        kwargs["authorize"]()
        return bundle()

    monkeypatch.setattr(owner, "read_material_native_bundle", read)
    monkeypatch.setattr(owner, "read_material_discovery_plan", lambda *a, **k: broken)
    monkeypatch.setattr(owner, "add_material_task", lambda *args, **kwargs: writes.append(True))
    intake = MaterialNativeLearningIntakeManifest.model_validate(native_intake())
    with pytest.raises(ValueError, match="MATERIAL_NATIVE_DISCOVERY_COVERAGE_MISMATCH"):
        coordinator.discovery_plan(
            SimpleNamespace(run_id=value.run_id),
            SimpleNamespace(operator_id=intake.requested_by, intake=intake),
        )
    assert checks == [intake.requested_by] and not writes


@pytest.mark.parametrize("native", [False, True])
def test_adjusted_native_plan_is_cached_and_rebound_after_restart_without_changing_v1(
    monkeypatch, native
):
    class Sessions:
        @contextmanager
        def __call__(self):
            yield object()

    coordinator = object.__new__(MaterialLearningCoordinator)
    coordinator.sessions = Sessions()
    coordinator.artifacts = object()
    coordinator.authorize = lambda claim: None
    coordinator._plan = None
    value = plan()
    values = dict(value.by_unit)
    values["question-one"] = replace(values["question-one"], solution_unit_keys=())
    original = replace(value, by_unit=values)
    monkeypatch.setattr(owner, "read_material_discovery_plan", lambda *a, **k: original)
    calls = []

    def read(*args, **kwargs):
        calls.append(True)
        return bundle()

    monkeypatch.setattr(owner, "read_material_native_bundle", read)
    data = native_intake()
    if native:
        intake = MaterialNativeLearningIntakeManifest.model_validate(data)
    else:
        data.pop("native_bundle")
        data["schema_version"] = "material-learning-intake/1.0"
        intake = MaterialLearningIntakeManifest.model_validate(data)
    claim = SimpleNamespace(run_id=value.run_id)
    context = SimpleNamespace(intake=intake, operator_id=intake.requested_by)
    first = coordinator.discovery_plan(claim, context)
    assert coordinator.discovery_plan(claim, context) is first
    assert calls == ([True] if native else [])
    assert first.by_unit["question-one"].solution_unit_keys == (("solution-one",) if native else ())
    coordinator._plan = None
    assert coordinator.discovery_plan(claim, context) == first
    assert len(calls) == (2 if native else 0)


def test_native_pairing_never_uses_only_number_when_the_original_pointer_differs():
    value = plan()
    values = dict(value.by_unit)
    question = values["question-one"]
    pointer = question.source.original.model_copy(update={"sha256": "sha256:" + "f" * 64})
    values[question.unit_key] = replace(
        question, source=question.source.model_copy(update={"original": pointer})
    )
    with pytest.raises(ValueError, match="MATERIAL_NATIVE_DISCOVERY_SOURCE_MISMATCH"):
        bind_native_material_discovery_plan(replace(value, by_unit=values), bundle())


@pytest.mark.parametrize(
    "code,source_failure",
    [
        ("MATERIAL_NATIVE_DISCOVERY_COVERAGE_MISMATCH", True),
        ("MATERIAL_NATIVE_DISCOVERY_SOURCE_MISMATCH", False),
    ],
)
def test_only_native_source_quality_failure_finishes_one_run_not_the_whole_owner(
    monkeypatch, code, source_failure
):
    class Sessions:
        @contextmanager
        def __call__(self):
            yield SimpleNamespace(scalar=lambda *args: None)

        begin = __call__

    coordinator = object.__new__(MaterialLearningCoordinator)
    coordinator.sessions = Sessions()
    coordinator.discovery_plan = lambda *args: (_ for _ in ()).throw(ValueError(code))
    transitions = []
    monkeypatch.setattr(
        owner, "lock_material_run", lambda *a, **k: SimpleNamespace(state="DISCOVERING")
    )
    monkeypatch.setattr(
        owner,
        "transition_material_run",
        lambda *a, **k: transitions.append((a[2].value, k["error_code"])),
    )
    intake = MaterialNativeLearningIntakeManifest.model_validate(native_intake())
    args = (SimpleNamespace(run_id="materialrun_" + "1" * 32), SimpleNamespace(intake=intake))
    if source_failure:
        result = coordinator.discovery_step(*args)
        assert result.phase == "FAILED"
        assert transitions == [("FAILED", code)]
    else:
        with pytest.raises(ValueError, match=code):
            coordinator.discovery_step(*args)
        assert not transitions
