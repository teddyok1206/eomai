"""Composition selectors reuse the source-aware rules; no DB, network or private input."""

from dataclasses import replace
from pathlib import Path

import pytest
from eom_catalog_contracts.kakao_question import KakaoDisplayOverride, KakaoQuestionText
from eom_catalog_contracts.kakao_question_composition import (
    KakaoCompositionInput,
    KakaoQuestionComposition,
    KakaoQuestionMerge,
    KakaoQuestionSplit,
    KakaoTextSpanSelection,
    KakaoWholeBlockSelection,
)
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES, validate_contract
from eom_catalog_service.kakao_question_editing import (
    question_final_blockers,
    resolve_question_text,
)
from eom_catalog_service.kakao_question_selections import (
    ResolvedKakaoCompositionQuestion,
    prepare_question_composition,
)
from eom_identifiers import canonical_json_bytes, sha256_bytes
from pydantic import TypeAdapter

from tests.unit.test_kakao_question_editing import (
    ACTOR,
    NOW,
    identity,
    image,
    question,
    source,
    student,
)

COMMAND = TypeAdapter(KakaoQuestionComposition)


def input_ref(value, version=1):
    return KakaoCompositionInput(
        question_id=value.question_id,
        question_revision_id=value.question_revision_id,
        resource_version=version,
    )


def reserved(*numbers):
    return tuple(
        (identity("kakaoquestion", number), identity("kakaoquestionrev", number))
        for number in numbers
    )


def split_case(text="질문A 질문B"):
    resolved = source((text,), ("student",))
    value = question(resolved)
    block_id = value.ordered_blocks[0].block_id
    command = KakaoQuestionSplit(
        source_binding_id=value.source_binding_id,
        room_id=value.room_id,
        input=input_ref(value),
        partitions=(
            (KakaoTextSpanSelection(block_id=block_id, start_codepoint=0, end_codepoint=4),),
            (
                KakaoTextSpanSelection(
                    block_id=block_id, start_codepoint=4, end_codepoint=len(text)
                ),
            ),
        ),
    )
    return command, ResolvedKakaoCompositionQuestion(value, 1), resolved


def prepare(command, inputs, sources, ids=None):
    return prepare_question_composition(
        command,
        inputs,
        new_ids=ids if ids is not None else reserved(10, 11),
        actor_id=ACTOR,
        created_at=NOW,
        sources=sources,
    )


def merge_case():
    first_source, second_source = source(number=1), source(number=2)
    first, second = question(first_source), question(second_source, number=2)
    command = KakaoQuestionMerge(
        source_binding_id=first.source_binding_id,
        room_id=first.room_id,
        inputs=(input_ref(first), input_ref(second)),
    )
    return (
        command,
        (ResolvedKakaoCompositionQuestion(first, 1), ResolvedKakaoCompositionQuestion(second, 1)),
        (first_source, second_source),
    )


def test_schema_is_pinned_and_mirrored_with_wire_roundtrip():
    root = Path(__file__).resolve().parents[2]
    entry = CATALOG_SCHEMA_RESOURCES["kakao-question-compose-v1"]
    raw = (root / entry.canonical_path).read_bytes()
    assert sha256_bytes(raw) == entry.sha256
    assert (
        raw
        == (
            root / "packages/catalog_contracts/eom_catalog_contracts" / entry.resource_path
        ).read_bytes()
    )
    for command in (split_case()[0], merge_case()[0]):
        payload = command.model_dump(mode="json")
        validate_contract("kakao-question-compose-v1", payload)
        assert COMMAND.validate_json(canonical_json_bytes(payload)) == command


@pytest.mark.parametrize(
    "field,value",
    [
        ("owner_operator_id", identity("operator", 9)),
        ("actor_id", identity("operator", 9)),
        ("approved", True),
        ("raw_text", "client text"),
        ("source_pointer", {}),
        ("question_id", identity("kakaoquestion", 9)),
        ("new_ids", reserved(4, 5)),
        ("created_at", NOW.isoformat()),
        ("room_id", "latest"),
        ("operation", "EDIT"),
    ],
)
def test_wire_rejects_authority_new_id_source_content_or_latest(field, value):
    payload = split_case()[0].model_dump(mode="json") | {field: value}
    with pytest.raises(ValueError):
        COMMAND.validate_python(payload)


@pytest.mark.parametrize("version", [True, "1", 1.5, 0, 2147483647])
def test_input_version_is_a_bounded_integer(version):
    payload = split_case()[0].model_dump(mode="json")
    payload["input"]["resource_version"] = version
    with pytest.raises(ValueError):
        COMMAND.validate_python(payload)


@pytest.mark.parametrize("start,end", [(True, 4), (0, True), (-1, 4), (0, 65537), (4, 4), (5, 4)])
def test_span_is_nonempty_bounded_codepoints(start, end):
    with pytest.raises(ValueError):
        KakaoTextSpanSelection(block_id="text", start_codepoint=start, end_codepoint=end)


@pytest.mark.parametrize("partitions", [[], [[{"kind": "BLOCK", "block_id": "a"}]], [[], []]])
def test_split_requires_at_least_two_nonempty_partitions(partitions):
    payload = split_case()[0].model_dump(mode="json") | {"partitions": partitions}
    with pytest.raises(ValueError):
        COMMAND.validate_python(payload)


def test_split_and_merge_have_no_hidden_block_or_question_truncation():
    payload = split_case()[0].model_dump(mode="json")
    for partitions in (
        [[{"kind": "BLOCK", "block_id": "a"}]] * 101,
        [[{"kind": "BLOCK", "block_id": "a"}]] + [[{"kind": "BLOCK", "block_id": "b"}]] * 230,
        [[{"kind": "BLOCK", "block_id": "a"}] * 231, [{"kind": "BLOCK", "block_id": "b"}]],
    ):
        with pytest.raises(ValueError):
            COMMAND.validate_python(payload | {"partitions": partitions})
    merge = merge_case()[0].model_dump(mode="json")
    for inputs in ([], merge["inputs"][:1], merge["inputs"] * 51):
        with pytest.raises(ValueError):
            COMMAND.validate_python(merge | {"inputs": inputs})


def test_merge_rejects_same_logical_question_even_with_different_revision():
    payload = merge_case()[0].model_dump(mode="json")
    payload["inputs"][1]["question_id"] = payload["inputs"][0]["question_id"]
    with pytest.raises(ValueError, match="COMPOSITION_INPUT_DUPLICATED"):
        COMMAND.validate_python(payload)


def test_split_exact_text_and_merge_back_preserve_source_bytes_and_provenance():
    command, current, resolved = split_case()
    before = canonical_json_bytes(current.manifest.model_dump(mode="json"))
    parts = prepare(command, (current,), (resolved,))
    assert [resolve_question_text(item.ordered_blocks[0], resolved) for item in parts] == [
        "질문A ",
        "질문B",
    ]
    assert all(item.review_state == "UNREVIEWED" for item in parts)
    assert all(
        item.provenance[0].question_revision_id == current.manifest.question_revision_id
        for item in parts
    )
    assert canonical_json_bytes(current.manifest.model_dump(mode="json")) == before
    assert (
        prepare(command, (current,), (resolved,)) == parts
    )  # Same reserved output identities/time.
    merge = KakaoQuestionMerge(
        source_binding_id=command.source_binding_id,
        room_id=command.room_id,
        inputs=tuple(input_ref(item) for item in parts),
    )
    result = prepare(
        merge,
        tuple(ResolvedKakaoCompositionQuestion(item, 1) for item in reversed(parts)),
        (resolved,),
        reserved(12),
    )[0]
    assert result.ordered_blocks == tuple(block for part in parts for block in part.ordered_blocks)
    assert result.sources == current.manifest.sources


@pytest.mark.parametrize(
    "difference", ["revision", "version", "bool_version", "missing", "duplicate", "extra"]
)
def test_resolved_inputs_must_match_all_expected_pins(difference):
    command, current, resolved = split_case()
    inputs = (current,)
    if difference == "revision":
        inputs = (
            replace(
                current,
                manifest=current.manifest.model_copy(
                    update={"question_revision_id": identity("kakaoquestionrev", 99)}
                ),
            ),
        )
    elif difference == "version":
        inputs = (replace(current, resource_version=2),)
    elif difference == "bool_version":
        inputs = (replace(current, resource_version=True),)
    elif difference == "missing":
        inputs = ()
    elif difference == "duplicate":
        inputs = (current, current)
    else:
        inputs = (current, ResolvedKakaoCompositionQuestion(question(resolved, number=9), 1))
    with pytest.raises(ValueError, match="PRECONDITION_FAILED"):
        prepare(command, inputs, (resolved,))


@pytest.mark.parametrize("field", ["source_binding_id", "room_id"])
def test_command_scope_is_checked_even_for_correct_question_identity(field):
    command, current, resolved = split_case()
    prefix = "kakaobinding" if field == "source_binding_id" else "kakaoroom"
    command = command.model_copy(update={field: identity(prefix, 2)})
    with pytest.raises(ValueError, match="COMPOSITION_SCOPE_INVALID"):
        prepare(command, (current,), (resolved,))


@pytest.mark.parametrize("ids", [(), reserved(10), reserved(10, 11, 12)])
def test_split_rejects_wrong_reservation_count(ids):
    command, current, resolved = split_case()
    with pytest.raises(ValueError, match="COMPOSITION_RESERVATION_INVALID"):
        prepare(command, (current,), (resolved,), ids)


@pytest.mark.parametrize("ids", [(), reserved(10, 11)])
def test_merge_rejects_wrong_reservation_count(ids):
    command, inputs, sources = merge_case()
    with pytest.raises(ValueError, match="COMPOSITION_RESERVATION_INVALID"):
        prepare(command, inputs, sources, ids)


@pytest.mark.parametrize("ids", [reserved(10, 10), reserved(1, 11)])
def test_reserved_output_cannot_reuse_an_identity(ids):
    command, current, resolved = split_case()
    with pytest.raises(ValueError, match="REVISION_REUSED"):
        prepare(command, (current,), (resolved,), ids)


@pytest.mark.parametrize("start,end", [(3, 7), (5, 7), (4, 8)])
def test_gap_overlap_or_outside_selected_source_is_not_accepted(start, end):
    command, current, resolved = split_case()
    second = command.partitions[1][0].model_copy(
        update={"start_codepoint": start, "end_codepoint": end}
    )
    command = command.model_copy(update={"partitions": (command.partitions[0], (second,))})
    with pytest.raises(ValueError, match=r"SPAN|COVERAGE"):
        prepare(command, (current,), (resolved,))


def test_unknown_block_does_not_resolve_from_another_source():
    command, current, resolved = split_case()
    command = command.model_copy(
        update={
            "partitions": ((KakaoWholeBlockSelection(block_id="missing"),), command.partitions[1])
        }
    )
    with pytest.raises(ValueError, match="COMPOSITION_BLOCK_MISSING"):
        prepare(command, (current,), (resolved,))


@pytest.mark.parametrize("text,cut", [("A🙂BCDEF", 2), ("ABC각D", 4), ("ABCx́DE", 4)])
def test_non_ascii_and_grapheme_splits_use_existing_unicode_validation(text, cut):
    command, current, resolved = split_case(text)
    block_id = current.manifest.ordered_blocks[0].block_id
    command = command.model_copy(
        update={
            "partitions": (
                (KakaoTextSpanSelection(block_id=block_id, start_codepoint=0, end_codepoint=cut),),
                (
                    KakaoTextSpanSelection(
                        block_id=block_id, start_codepoint=cut, end_codepoint=len(text)
                    ),
                ),
            )
        }
    )
    if text == "A🙂BCDEF":
        parts = prepare(command, (current,), (resolved,))
        assert resolve_question_text(parts[0].ordered_blocks[0], resolved) == "A🙂"
    else:
        with pytest.raises(ValueError, match="TEXT_SPAN_INVALID"):
            prepare(command, (current,), (resolved,))


def test_display_override_cannot_be_sliced_using_original_offsets():
    command, current, resolved = split_case()
    block = current.manifest.ordered_blocks[0].model_copy(
        update={
            "display_override": KakaoDisplayOverride(
                text="다른 길이의 표시문", reason="오타 표시 수정"
            )
        }
    )
    current = replace(
        current, manifest=current.manifest.model_copy(update={"ordered_blocks": (block,)})
    )
    with pytest.raises(ValueError, match="SPLIT_DISPLAY_OVERRIDE"):
        prepare(command, (current,), (resolved,))


@pytest.mark.parametrize("whole_span", [False, True])
def test_whole_display_override_is_preserved_without_copying_source_text(whole_span):
    resolved = source(("첫 질문", "다음 질문"), ("student", "student"))
    value = question(resolved)
    first, second = value.ordered_blocks
    first = first.model_copy(
        update={
            "display_override": KakaoDisplayOverride(text="표시만 고친 질문", reason="오타 수정")
        }
    )
    value = value.model_copy(update={"ordered_blocks": (first, second)})
    selected = (
        KakaoTextSpanSelection(block_id=first.block_id, start_codepoint=0, end_codepoint=4)
        if whole_span
        else KakaoWholeBlockSelection(block_id=first.block_id)
    )
    command = KakaoQuestionSplit(
        source_binding_id=value.source_binding_id,
        room_id=value.room_id,
        input=input_ref(value),
        partitions=((selected,), (KakaoWholeBlockSelection(block_id=second.block_id),)),
    )
    parts = prepare(command, (ResolvedKakaoCompositionQuestion(value, 1),), (resolved,))
    assert parts[0].ordered_blocks == (first,)
    assert first.display_override.text == "표시만 고친 질문"


def test_repeated_text_is_not_deduplicated_as_if_it_were_one_message():
    resolved = source(("같은 질문", "같은 질문"), ("student", "student"))
    value = question(resolved)
    command = KakaoQuestionSplit(
        source_binding_id=value.source_binding_id,
        room_id=value.room_id,
        input=input_ref(value),
        partitions=tuple(
            (KakaoWholeBlockSelection(block_id=block.block_id),) for block in value.ordered_blocks
        ),
    )
    parts = prepare(command, (ResolvedKakaoCompositionQuestion(value, 1),), (resolved,))
    assert len(parts) == 2
    assert len({part.ordered_blocks[0].source_occurrence_id for part in parts}) == 2
    assert [resolve_question_text(part.ordered_blocks[0], resolved) for part in parts] == [
        "같은 질문",
        "같은 질문",
    ]


@pytest.mark.parametrize("availability", [True, False])
def test_split_moves_every_photo_once_without_changing_pointer_quality_or_occurrence(availability):
    resolved = source(
        ("첫 질문", "다음 질문"),
        ("student", "student"),
        attachments={1: (image(available=availability),)},
    )
    value = question(resolved)
    first, photo, second = value.ordered_blocks
    command = KakaoQuestionSplit(
        source_binding_id=value.source_binding_id,
        room_id=value.room_id,
        input=input_ref(value),
        partitions=(
            (
                KakaoWholeBlockSelection(block_id=first.block_id),
                KakaoWholeBlockSelection(block_id=photo.block_id),
            ),
            (KakaoWholeBlockSelection(block_id=second.block_id),),
        ),
    )
    current = ResolvedKakaoCompositionQuestion(value, 1)
    parts = prepare(command, (current,), (resolved,))
    assert parts[0].ordered_blocks[1] == photo
    if not availability:
        assert "MISSING_ATTACHMENT" in question_final_blockers(parts[0])
    for partitions in (
        ((command.partitions[0][0],), command.partitions[1]),
        (command.partitions[0], command.partitions[1] + (command.partitions[0][1],)),
    ):
        with pytest.raises(ValueError, match="COVERAGE_INVALID"):
            prepare(command.model_copy(update={"partitions": partitions}), (current,), (resolved,))
    forged = command.model_copy(
        update={
            "partitions": (
                (
                    KakaoTextSpanSelection(
                        block_id=photo.block_id, start_codepoint=0, end_codepoint=1
                    ),
                ),
                command.partitions[1],
            )
        }
    )
    with pytest.raises(ValueError, match="TEXT_SPAN_INVALID"):
        prepare(forged, (current,), (resolved,))


def test_merge_preserves_requested_order_not_resolver_order_and_does_not_mix_students():
    command, inputs, sources = merge_case()
    result = prepare(command, tuple(reversed(inputs)), sources, reserved(10))[0]
    assert result.ordered_blocks == tuple(
        block for item in inputs for block in item.manifest.ordered_blocks
    )
    different_student = replace(
        inputs[1], manifest=inputs[1].manifest.model_copy(update={"student": student(2)})
    )
    with pytest.raises(ValueError, match="COMPOSITION_SCOPE_INVALID"):
        prepare(command, (inputs[0], different_student), sources, reserved(10))


def test_no_student_or_unresolved_source_does_not_become_a_new_question():
    command, current, resolved = split_case()
    with pytest.raises(ValueError, match="COMPOSITION_SCOPE_INVALID"):
        prepare(
            command,
            (replace(current, manifest=current.manifest.model_copy(update={"student": None})),),
            (resolved,),
        )
    with pytest.raises(ValueError, match="SOURCE_REFERENCE_INVALID"):
        prepare(command, (current,), ())


def test_source_hash_validation_is_still_required_for_whole_blocks():
    command, current, resolved = split_case()
    bad_block = current.manifest.ordered_blocks[0].model_copy(
        update={"source_text_sha256": "sha256:" + "0" * 64}
    )
    assert isinstance(bad_block, KakaoQuestionText)
    current = replace(
        current, manifest=current.manifest.model_copy(update={"ordered_blocks": (bad_block,)})
    )
    with pytest.raises(ValueError, match="TEXT_HASH_MISMATCH"):
        prepare(command, (current,), (resolved,))
