"""Recognize the observed, independently corroborated MANUAL CSV popup.

This is room identity evidence, not an attachment or CSV admission decision.
"""

import re

from eom_catalog_contracts.kakao_room_intake import observed_manual_room_keys
from eom_kakao_archive_contracts.manual_observation import ManualPageObservation

_KEY = r"[A-Za-z0-9_-]{1,128}"
_POPUP_PATH = re.compile(rf"/space/{_KEY}/channel/({_KEY})/chats/({_KEY})")


def observed_csv_popup_room_keys(observation: ManualPageObservation) -> tuple[str, str] | None:
    document = observation.document
    if (
        observation.status != "OBSERVED"
        or observation.target.kind != "BLOB"
        or document is None
        or document.truncated
        or (route := _POPUP_PATH.fullmatch(document.path)) is None
    ):
        return None
    channel, room = route.groups()
    popups = [node.index for node in document.nodes if "chat_popup" in node.classes]
    if len(popups) != 1 or any("list_chat" in node.classes for node in document.nodes):
        return None
    popup = document.nodes[popups[0]]
    if popup.identities.data_chat_id not in (None, room):
        return None
    branches: dict[int, int | None] = {popup.index: None}
    corroborating_bubbles: set[int] = set()
    used_paths: set[str] = set()
    for node in document.nodes[popup.index + 1 :]:
        if node.parent_index is None or node.parent_index not in branches:
            continue
        bubble = branches[node.parent_index]
        if "item_chat" in node.classes:
            if bubble is not None:
                return None
            bubble = node.index
        branches[node.index] = bubble
        if bubble is None or node.tag != "a" or "btn_save" not in node.classes:
            continue
        path = node.link_path
        if (
            path is None
            or observed_manual_room_keys(document.path, path) != (channel, room)
            or path in used_paths
        ):
            return None
        used_paths.add(path)
        corroborating_bubbles.add(bubble)
    return (channel, room) if len(corroborating_bubbles) >= 2 else None
