"""Synthetic occurrence fixtures shaped like the inspected channel popup."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from eom_catalog_service.kakao_csv_parser import read_kakao_csv_messages
from eom_catalog_service.kakao_photo_alignment import infer_kakao_photo_occurrence
from eom_kakao_archive_contracts.manual_download import ManualDownloadResult
from eom_kakao_archive_contracts.manual_observation import ManualPageObservation

from tests.unit.test_kakao_archive_rules import csv_bytes

PATH = "/space/scope/channel/channel1/chats"
TARGET = "/api/profiles/channel1/chats/room1/log1/attach1/image"
OTHER_PHOTO = "/api/profiles/channel1/chats/room1/log2/attach2/image"
OTHER_ROOM = "/api/profiles/channel1/chats/room2/log1/attach1/image"
NOW = datetime(2026, 11, 18, 13, tzinfo=UTC)


def document(groups, *, truncated=False, path=PATH):
    nodes = []

    def add(parent, tag, *classes, text=None, link=None):
        index = len(nodes)
        nodes.append(
            dict(
                index=index,
                parent_index=parent,
                tag=tag,
                classes=classes,
                role=None,
                label=None,
                text=text,
                identities={
                    f"data-{name}": None for name in ("id", "chat-id", "message-id", "log-id")
                },
                link_path=link,
                is_image=tag == "img",
            )
        )
        return index

    popup = add(None, "div", "chat_popup")
    for kind, value in groups:
        message = add(popup, "div", "item_chat")
        container = add(message, "div", "set_chat")
        if kind == "photo":
            add(container, "a", "link_pic", "item_expiry")
            add(container, "a", "btn_save", link=value)
        elif kind == "album":
            album = add(container, "div", "box_package")
            add(album, "a", "link_pic")
            add(album, "a", "link_pic")
            add(album, "a", "btn_save", link=value)
        else:
            wrapped = kind in {"wrapped", "split"}
            body = add(container, "p", "txt_chat", text=None if wrapped else value)
            if wrapped:
                add(body, "span", text=value)
                if kind == "split":
                    add(body, "span", text="이어지는 내용")
            if kind == "collapsed":
                add(body, "a", "link_more", text="더보기")
            if kind == "mixed":
                add(body, "span", text="이어지는 내용")
    return dict(origin="https://business.kakao.com", path=path, truncated=truncated, nodes=nodes)


def inputs(messages, groups, *, csv_groups=None, photo_document=None, photo_changes=None):
    rows = [["2026-11-18 20:01:00", "synthetic", text] for text in messages]
    normalization = read_kakao_csv_messages(csv_bytes(rows))

    def observed(index, doc, target, member):
        identity = dict(
            capture_id="kakaodownload_" + index * 32,
            profile_id="kakaoprofile_" + "1" * 32,
            browser_run_id="kakaobrowserrun_" + "2" * 32,
            fence_epoch=2,
            page_instance_id="kakaopage_" + "3" * 32,
        )
        receipt = ManualDownloadResult.model_validate(
            dict(
                **identity,
                phase="RECEIVED",
                started_at=NOW,
                completed_at=NOW + timedelta(seconds=2),
                member=member,
                suggested_filename="misleading-file.name",
                error_code=None,
            )
        )
        value = dict(
            **identity,
            observed_at=NOW + timedelta(seconds=1),
            status="OBSERVED",
            target=target,
            document=doc,
            error_code=None,
        )
        if index == "b" and photo_changes:
            value.update(photo_changes)
        return receipt, ManualPageObservation.model_validate(value)

    csv_result, csv_obs = observed(
        "a",
        document(groups if csv_groups is None else csv_groups),
        dict(kind="BLOB", path=None),
        dict(sha256=normalization.source_sha256, size_bytes=normalization.source_bytes),
    )
    photo_result, photo_obs = observed(
        "b",
        document(groups) if photo_document is None else photo_document,
        dict(kind="SAME_ORIGIN_PATH", path=TARGET),
        dict(sha256="sha256:" + "b" * 64, size_bytes=22),
    )
    return normalization, dict(
        csv_receipt=csv_result,
        csv_observation=csv_obs,
        photo_receipt=photo_result,
        photo_observation=photo_obs,
    )


GROUPS = [("text", "질문\n이어서"), ("photo", TARGET), ("photo", OTHER_PHOTO), ("text", "답변")]


@pytest.mark.parametrize(
    "messages,ordinal",
    [
        (["이전", "질문\r\n이어서", "사진", "사진", "답변", "다음"], 3),
        (["다음", "답변", "사진", "사진", "질문\r\n이어서", "이전"], 4),
    ],
)
@pytest.mark.parametrize("wrapped", [False, True])
def test_exact_window_maps_one_of_two_identical_photo_rows(messages, ordinal, wrapped):
    groups = [("wrapped" if wrapped and kind == "text" else kind, value) for kind, value in GROUPS]
    parsed, evidence = inputs(messages, groups, csv_groups=[("photo", OTHER_PHOTO)])
    answer = infer_kakao_photo_occurrence(parsed, **evidence)
    assert answer is not None
    assert (answer.row_ordinal, answer.album_ordinal, answer.association) == (
        ordinal,
        1,
        "SEQUENCE_INFERRED",
    )


END_GROUPS = [
    ("text", "첫 질문"),
    ("text", "추가 설명"),
    ("photo", TARGET),
    ("photo", OTHER_PHOTO),
]
END_MESSAGES = ["사진", "첫 질문", "추가 설명", "사진", "사진"]


@pytest.mark.parametrize("reverse_dom", [False, True])
@pytest.mark.parametrize("reverse_csv", [False, True])
def test_stable_latest_photo_run_aligns_even_with_an_older_unloaded_photo(reverse_dom, reverse_csv):
    parsed, evidence = inputs(
        END_MESSAGES[::-1] if reverse_csv else END_MESSAGES,
        END_GROUPS[::-1] if reverse_dom else END_GROUPS,
    )
    answer = infer_kakao_photo_occurrence(parsed, **evidence)
    assert answer is not None
    assert (answer.row_ordinal, answer.association) == (
        2 if reverse_csv else 4,
        "SEQUENCE_INFERRED",
    )


@pytest.mark.parametrize(
    "messages,groups,changes",
    [
        ([*END_MESSAGES, "사진"], END_GROUPS, {}),
        ([*END_MESSAGES, "이후의 새 답변"], END_GROUPS, {}),
        (END_MESSAGES + END_MESSAGES[1:], END_GROUPS, {}),
        (
            ["사진", "첫 질문", "첫 질문", "사진", "사진"],
            [END_GROUPS[0], END_GROUPS[0], *END_GROUPS[2:]],
            {},
        ),
        (END_MESSAGES, [END_GROUPS[0], ("collapsed", "추가 설명"), *END_GROUPS[2:]], {}),
        (END_MESSAGES, [*END_GROUPS[:3], ("album", OTHER_PHOTO)], {}),
        (END_MESSAGES, END_GROUPS, {"csv_groups": [*END_GROUPS[:2], *END_GROUPS[2:][::-1]]}),
        (END_MESSAGES, END_GROUPS, {"csv_groups": END_GROUPS[:-1]}),
        (
            END_MESSAGES,
            END_GROUPS,
            {
                "photo_changes": dict(target=dict(kind="UNAVAILABLE", path=None)),
            },
        ),
    ],
)
def test_photo_run_never_guesses_from_count_or_end_position(messages, groups, changes):
    parsed, evidence = inputs(messages, groups, **changes)
    assert infer_kakao_photo_occurrence(parsed, **evidence) is None


@pytest.mark.parametrize(
    "messages",
    [
        ["질문\n이어서", "사진", "사진", "답변"] * 2,
        ["질문\n이어서", "사진", "사진", "답변", "사진", "사진", "질문\n이어서"],
        ["질문\n이어서", "사진", "추가 행", "사진", "답변"],
        ["질문\n이어서 ", "사진", "사진", "답변"],
    ],
)
def test_ambiguous_or_not_exact_never_picks_first_row(messages):
    parsed, evidence = inputs(messages, GROUPS)
    assert infer_kakao_photo_occurrence(parsed, **evidence) is None


@pytest.mark.parametrize(
    "groups",
    [
        [("text", "질문\n이어서"), ("album", TARGET), ("photo", OTHER_PHOTO), ("text", "답변")],
        [("mixed", "질문\n이어서"), *GROUPS[1:]],
        [("split", "질문\n이어서"), *GROUPS[1:]],
        [("collapsed", "질문\n이어서"), *GROUPS[1:]],
        [*GROUPS[:2], ("photo", TARGET), GROUPS[-1]],
        [*GROUPS[:2], ("photo", OTHER_ROOM), GROUPS[-1]],
        [*GROUPS[:2], ("text", "사진"), GROUPS[-1]],
        GROUPS[1:],
    ],
)
def test_unavailable_dom_shapes_never_turn_into_a_known_photo_row(groups):
    parsed, evidence = inputs(["질문\n이어서", "사진", "사진", "답변"], groups)
    assert infer_kakao_photo_occurrence(parsed, **evidence) is None


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(csv_groups=[("photo", OTHER_ROOM)]),
        dict(csv_groups=[("text", "질문\n이어서")]),
        dict(photo_document=document(GROUPS, truncated=True)),
        dict(photo_document=document(GROUPS, path=PATH + "/unknown")),
        dict(photo_changes=dict(page_instance_id="kakaopage_" + "f" * 32)),
        dict(photo_changes=dict(observed_at=NOW + timedelta(seconds=3))),
        dict(photo_changes=dict(target=dict(kind="UNAVAILABLE", path=None))),
    ],
)
def test_fence_transfer_and_independent_csv_room_observation_are_required(kwargs):
    parsed, evidence = inputs(["질문\n이어서", "사진", "사진", "답변"], GROUPS, **kwargs)
    assert infer_kakao_photo_occurrence(parsed, **evidence) is None


def test_csv_hash_cannot_be_substituted_even_when_message_window_matches():
    parsed, evidence = inputs(["질문\n이어서", "사진", "사진", "답변"], GROUPS)
    different = replace(parsed, source_sha256="sha256:" + "0" * 64)
    assert infer_kakao_photo_occurrence(different, **evidence) is None
