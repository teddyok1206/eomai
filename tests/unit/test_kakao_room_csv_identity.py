"""Accept independently scoped popup evidence without attributing a photo file."""

import pytest
from eom_catalog_service.kakao_room_csv_identity import observed_csv_popup_room_keys
from eom_kakao_archive_contracts.manual_observation import ManualDocument, ManualPageObservation

from tests.unit.test_kakao_photo_alignment import GROUPS, OTHER_ROOM, TARGET, inputs

POPUP = "/space/scope/channel/channel1/chats/room1"


def observation(**options):
    _, evidence = inputs(["사진", "사진"], options.pop("groups", GROUPS))
    original = evidence["csv_observation"].model_dump(mode="json", by_alias=True)
    original["document"]["path"] = options.pop("path", POPUP)
    if options.pop("truncated", False):
        original["document"]["truncated"] = True
    if options.pop("listing", False):
        original["document"]["nodes"][0]["classes"].append("list_chat")
    if options.pop("multiple_popups", False):
        original["document"]["nodes"][1]["classes"].append("chat_popup")
    if options.pop("wrong_popup_identity", False):
        original["document"]["nodes"][0]["identities"]["data-chat-id"] = "room2"
    if "target" in options:
        original["target"] = options.pop("target")
    assert not options
    return ManualPageObservation.model_validate(original)


def test_selected_room_is_confirmed_by_two_distinct_bubbles():
    assert observed_csv_popup_room_keys(observation()) == ("channel1", "room1")


@pytest.mark.parametrize(
    "changes",
    [
        {"path": POPUP.rsplit("/", 1)[0]},
        {"path": POPUP + "/extra"},
        {"path": POPUP.replace("room1", "room2")},
        {"groups": [("photo", TARGET)]},
        {"groups": [("photo", TARGET), ("photo", TARGET)]},
        {"groups": [*GROUPS, ("photo", OTHER_ROOM)]},
        {"listing": True},
        {"truncated": True},
        {"multiple_popups": True},
        {"wrong_popup_identity": True},
        {"target": {"kind": "UNAVAILABLE", "path": None}},
        {"target": {"kind": "SAME_ORIGIN_PATH", "path": TARGET}},
    ],
)
def test_no_inference_from_file_kind_path_or_name_alone(changes):
    assert observed_csv_popup_room_keys(observation(**changes)) is None


def test_two_distinct_links_in_the_same_bubble_do_not_corroborate():
    value = observation()
    raw = value.document.model_dump(mode="json", by_alias=True)
    first, second = [node for node in raw["nodes"] if "btn_save" in node["classes"]]
    second["parent_index"] = first["parent_index"]
    doc = ManualDocument.model_validate(raw)
    assert observed_csv_popup_room_keys(value.model_copy(update={"document": doc})) is None
