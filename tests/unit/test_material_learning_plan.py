"""Source-local sparse joins, complete coverage, and terminal history invariants."""

from __future__ import annotations

import pytest
from eom_catalog_contracts.material_learning import (
    MaterialDiscoveredUnit,
    MaterialDiscoveryResult,
    MaterialDiscoveryWork,
)
from eom_workflow.material_learning_plan import (
    DiscoveredMaterialRange,
    material_discovery_windows,
    material_unit_key,
    plan_material_learning_units,
)
from eom_workflow.material_learning_state import (
    MATERIAL_TRANSITIONS,
    TASK_TRANSITIONS,
    MaterialLearningState,
    MaterialTaskState,
    require_material_task_transition,
    require_material_transition,
)

from tests.unit.test_material_learning_contracts import rehash, source, unit, work


def discovered(units=None):
    request = work()
    request["sources"][0]["page_count"] = 2
    request["core_pages"] = [{"source_role": "MAIN", "physical_page": n} for n in (1, 2)]
    for index, page in enumerate(request["pages"], 1):
        page["physical_page"] = index
    rehash(request)
    if units is None:
        units = [unit(page=1), unit("SOLUTION", page=2)]
    # All declared roles really have observed regions, including mixed pages.
    coverage = []
    for page in (1, 2):
        kinds = sorted(
            {
                value["kind"]
                for value in units
                if any(anchor["physical_page"] == page for anchor in value["anchors"])
            }
        )
        coverage.append(
            {
                "source_role": "MAIN",
                "physical_page": page,
                "roles": kinds or ["NON_CONTENT"],
                "note": "",
            }
        )
    result = {
        "schema_version": "material-learning-discovery-result/1.0",
        "input_sha256": request["input_sha256"],
        "coverage": coverage,
        "units": units,
        "warnings": [],
    }
    return DiscoveredMaterialRange(
        MaterialDiscoveryWork.model_validate(request),
        MaterialDiscoveryResult.model_validate(result),
    )


def question(label="1", section="1장", top=100):
    value = unit(page=1, label=label)
    value["local_key"] = f"q-{section}-{label}-{top}".replace("장", "chapter")
    value["section_path"] = [section]
    value["anchors"][0]["bounding_box"]["top"] = top
    return value


def answer(label="1", section="1장", top=100):
    value = question(label, section, top)
    value["kind"] = "SOLUTION"
    value["local_key"] = "s-" + value["local_key"]
    value["anchors"][0]["physical_page"] = 2
    return value


@pytest.mark.parametrize("pages", [1, 2, 4, 5, 31, 1000, 2000])
def test_windows_own_each_page_once_with_bounded_visual_context(pages):
    windows = material_discovery_windows("MAIN", pages)
    assert tuple(
        page
        for window in windows
        for page in range(window.first_core_page, window.last_core_page + 1)
    ) == tuple(range(1, pages + 1))
    assert all(
        1
        <= window.first_input_page
        <= window.first_core_page
        <= window.last_core_page
        <= window.last_input_page
        <= pages
        for window in windows
    )
    assert all(window.last_input_page - window.first_input_page + 1 <= 6 for window in windows)


@pytest.mark.parametrize(
    "role,pages,size", [("other", 1, 4), ("MAIN", 0, 4), ("MAIN", 2001, 4), ("MAIN", 1, 0)]
)
def test_invalid_window_inputs_are_not_silently_clamped(role, pages, size):
    with pytest.raises(ValueError):
        material_discovery_windows(role, pages, core_size=size)


def test_question_links_to_original_solution_in_authored_order():
    plan = plan_material_learning_units((discovered(),))
    assert len(plan) == 2
    assert plan[0].unit.kind == "QUESTION"
    assert plan[0].solution_unit_keys == (plan[1].unit_key,)
    assert plan[0].issue_codes == ()


def test_separate_solution_file_uses_its_actual_source_not_main_page_number():
    main = discovered([question()])
    sources = [value.model_dump(mode="json") for value in main.work.sources]
    second = source("SOLUTIONS")
    second.update(
        document_id="edudoc_" + "d" * 32,
        document_revision_id="edudocrev_" + "e" * 32,
        page_count=2,
    )
    sources.append(second)
    first_work = main.work.model_dump(mode="json")
    first_work["sources"] = sources
    rehash(first_work)
    first_result = main.result.model_dump(mode="json")
    first_result["input_sha256"] = first_work["input_sha256"]
    other_work = main.work.model_dump(mode="json")
    other_work["sources"] = sources
    other_work["task_id"] = "materialtask_" + "c" * 32
    for page in (*other_work["pages"], *other_work["core_pages"]):
        page["source_role"] = "SOLUTIONS"
    rehash(other_work)
    solution = answer()
    solution["anchors"][0]["source_role"] = "SOLUTIONS"
    other_result = {
        "schema_version": "material-learning-discovery-result/1.0",
        "input_sha256": other_work["input_sha256"],
        "coverage": [
            {"source_role": "SOLUTIONS", "physical_page": 1, "roles": ["NON_CONTENT"], "note": ""},
            {"source_role": "SOLUTIONS", "physical_page": 2, "roles": ["SOLUTION"], "note": ""},
        ],
        "units": [solution],
        "warnings": [],
    }
    ranges = (
        DiscoveredMaterialRange(
            MaterialDiscoveryWork.model_validate(first_work),
            MaterialDiscoveryResult.model_validate(first_result),
        ),
        DiscoveredMaterialRange(
            MaterialDiscoveryWork.model_validate(other_work),
            MaterialDiscoveryResult.model_validate(other_result),
        ),
    )
    plan = plan_material_learning_units(ranges)
    assert plan[0].source.source_role == "MAIN"
    assert plan[1].source.source_role == "SOLUTIONS"
    assert plan[0].solution_unit_keys == (plan[1].unit_key,)
    assert plan_material_learning_units(tuple(reversed(ranges))) == plan


def test_same_printed_number_in_two_chapters_is_not_same_item_or_solution():
    values = [
        question(section="A"),
        question(section="B", top=200),
        answer(section="A"),
        answer(section="B", top=200),
    ]
    plan = plan_material_learning_units((discovered(values),))
    indexed = {value.unit_key: value for value in plan}
    questions = [value for value in plan if value.unit.kind == "QUESTION"]
    assert len({value.unit_key for value in questions}) == 2
    for value in questions:
        assert len(value.solution_unit_keys) == 1
        assert indexed[value.solution_unit_keys[0]].unit.section_path == value.unit.section_path


def test_ambiguous_same_section_answers_remain_visible_not_first_match_wins():
    plan = plan_material_learning_units((discovered([question(), answer(), answer(top=200)]),))
    assert len(plan) == 3
    assert plan[0].solution_unit_keys == ()
    assert plan[0].issue_codes == ("AMBIGUOUS_SOURCE_SOLUTION",)


def test_unmatched_section_is_not_fuzzy_number_only_pairing():
    plan = plan_material_learning_units((discovered([question(section="A"), answer(section="B")]),))
    assert plan[0].solution_unit_keys == ()
    assert plan[0].issue_codes == ("NO_SOURCE_SOLUTION_INDEPENDENT_SOLUTION_REQUIRED",)


def test_incomplete_fragment_is_recorded_not_published_as_full_item():
    question_unit = question()
    question_unit["continuation"] = "TO_NEXT"
    plan = plan_material_learning_units((discovered([question_unit, answer()]),))
    assert plan[0].issue_codes == ("INCOMPLETE_SOURCE_REGION",)
    assert not plan[0].solution_unit_keys


def test_unit_key_uses_source_revision_and_region_not_model_prose():
    selected = discovered()
    original = selected.result.units[0]
    changed = original.model_copy(update={"local_key": "other", "summary": "다른 설명 문구"})
    assert material_unit_key(selected.work.sources[0], original) == material_unit_key(
        selected.work.sources[0], changed
    )
    different = selected.work.sources[0].model_copy(
        update={"document_revision_id": "edudocrev_" + "e" * 32}
    )
    assert material_unit_key(selected.work.sources[0], original) != material_unit_key(
        different, original
    )


def test_missing_whole_book_pages_and_duplicate_core_are_explicit_errors():
    selected = discovered()
    with pytest.raises(ValueError, match="CORE_OVERLAP"):
        plan_material_learning_units((selected, selected))
    value = selected.work.model_dump(mode="json")
    value["sources"][0]["page_count"] = 3
    rehash(value)
    result = selected.result.model_dump(mode="json")
    result["input_sha256"] = value["input_sha256"]
    missing = DiscoveredMaterialRange(
        MaterialDiscoveryWork.model_validate(value), MaterialDiscoveryResult.model_validate(result)
    )
    with pytest.raises(ValueError, match="BOOK_COVERAGE_INCOMPLETE"):
        plan_material_learning_units((missing,))


def test_source_revision_and_rights_cannot_change_between_windows():
    selected = discovered()
    request = selected.work.model_dump(mode="json")
    request["sources"][0]["document_revision_id"] = "edudocrev_" + "f" * 32
    rehash(request)
    result = selected.result.model_dump(mode="json")
    result["input_sha256"] = request["input_sha256"]
    changed = DiscoveredMaterialRange(
        MaterialDiscoveryWork.model_validate(request),
        MaterialDiscoveryResult.model_validate(result),
    )
    with pytest.raises(ValueError, match="SOURCE_MIXED"):
        plan_material_learning_units((selected, changed))


def test_no_fabricated_global_external_number_needed_for_general_book():
    selected = discovered()
    value = selected.result.units[0].model_dump(mode="json")
    value["printed_label"] = None
    anonymous = MaterialDiscoveredUnit.model_validate(value)
    assert material_unit_key(selected.work.sources[0], anonymous).startswith("materialunit_")


@pytest.mark.parametrize(
    "terminal", ["COMPLETED", "COMPLETED_WITH_EXCEPTIONS", "FAILED", "CANCELLED"]
)
def test_material_terminal_history_has_no_rewrite_transition(terminal):
    state = MaterialLearningState(terminal)
    assert MATERIAL_TRANSITIONS[state] == frozenset()
    with pytest.raises(ValueError, match="TRANSITION_INVALID"):
        require_material_transition(state, MaterialLearningState.PROCESSING)


@pytest.mark.parametrize("terminal", ["COMPLETED", "EXCEPTION", "FAILED", "CANCELLED"])
def test_failed_task_retry_requires_new_attempt_not_history_reinterpretation(terminal):
    state = MaterialTaskState(terminal)
    assert TASK_TRANSITIONS[state] == frozenset()
    with pytest.raises(ValueError, match="TRANSITION_INVALID"):
        require_material_task_transition(state, MaterialTaskState.RUNNING)


def test_capacity_wait_can_resume_without_marking_failure():
    require_material_transition(
        MaterialLearningState.PROCESSING, MaterialLearningState.WAITING_FOR_CAPACITY
    )
    require_material_transition(
        MaterialLearningState.WAITING_FOR_CAPACITY, MaterialLearningState.PROCESSING
    )


def test_state_tables_are_closed_immutable_and_cover_all_states():
    assert set(MATERIAL_TRANSITIONS) == set(MaterialLearningState)
    assert set(TASK_TRANSITIONS) == set(MaterialTaskState)
    with pytest.raises(TypeError):
        MATERIAL_TRANSITIONS[MaterialLearningState.FAILED] = frozenset(
            {MaterialLearningState.PROCESSING}
        )
