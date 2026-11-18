"""Infer one observed photo's CSV occurrence, never authorize source admission."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Literal

from eom_catalog_contracts.kakao_archive import KakaoMessageNormalization
from eom_catalog_contracts.kakao_room_intake import observed_manual_room_keys
from eom_kakao_archive_contracts.manual_download import ManualDownloadResult
from eom_kakao_archive_contracts.manual_observation import (
    ManualDocument,
    ManualDocumentNode,
    ManualPageObservation,
)

_PHOTO_MARKER = "사진"
_FENCE_FIELDS = ("profile_id", "browser_run_id", "fence_epoch", "page_instance_id")


@dataclass(frozen=True, slots=True)
class KakaoPhotoOccurrence:
    row_ordinal: int
    album_ordinal: Literal[1] = 1
    association: Literal["SEQUENCE_INFERRED"] = "SEQUENCE_INFERRED"


@dataclass(slots=True)
class _Group:
    nodes: list[ManualDocumentNode] = field(default_factory=list, repr=False)

    def photo_links(self) -> Iterator[str]:
        return (
            node.link_path
            for node in self.nodes
            if node.tag == "a" and node.link_path is not None and "btn_save" in node.classes
        )

    def token(self) -> tuple[bool, str] | None:
        bodies, pictures = [], 0
        links = tuple(self.photo_links())
        for node in self.nodes:
            if "link_more" in node.classes or "box_package" in node.classes:
                return None  # A collapsed body or an album is not a one-row photo.
            if "txt_chat" in node.classes:
                bodies.append(node)
            if node.tag == "a" and "link_pic" in node.classes:
                pictures += 1
        if not bodies and len(links) == pictures == 1:
            return True, _PHOTO_MARKER
        if len(bodies) != 1 or pictures or links:
            return None
        body = bodies[0]
        # Only the body's direct text/BR can be safely read from v1. A retained
        # descendant with text can be interleaved with it in an unknown order.
        body_descendants = {body.index}
        for node in self.nodes:
            if node.parent_index in body_descendants:
                if node.text is not None or node.is_image or node.tag not in {"br", "span"}:
                    return None
                body_descendants.add(node.index)
        if body.text is None or body.text == _PHOTO_MARKER:
            return None
        return False, _line_endings(body.text)


def _line_endings(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _groups(document: ManualDocument) -> tuple[_Group, ...]:
    popups = [node.index for node in document.nodes if "chat_popup" in node.classes]
    if len(popups) != 1 or document.truncated:
        return ()
    memberships: dict[int, _Group | None] = {popups[0]: None}
    groups: list[_Group] = []
    for node in document.nodes[popups[0] + 1 :]:
        if node.parent_index not in memberships:
            continue
        group = memberships[node.parent_index]
        if "item_chat" in node.classes:
            if group is not None:
                return ()
            group = _Group()
            groups.append(group)
        elif group is not None:
            group.nodes.append(node)
        memberships[node.index] = group
    return tuple(groups)


def _room(groups: tuple[_Group, ...], path: str) -> tuple[str, str] | None:
    paths = (link for group in groups for link in group.photo_links())
    keys = {observed_manual_room_keys(path, link) for link in paths}
    return next(iter(keys)) if len(keys) == 1 else None


def _same_capture(receipt: ManualDownloadResult, observation: ManualPageObservation) -> bool:
    return (
        receipt.phase == "RECEIVED"
        and receipt.member is not None
        and observation.status == "OBSERVED"
        and receipt.started_at <= observation.observed_at <= receipt.completed_at
        and all(
            getattr(receipt, name) == getattr(observation, name)
            for name in (*_FENCE_FIELDS, "capture_id")
        )
    )


def _text_key(text: str) -> bytes:
    return sha256(_line_endings(text).encode()).digest()


def _matching_starts(rows: Iterable[bytes], pattern: tuple[bytes, ...]) -> Iterator[int]:
    # Failure links preserve overlapping repeated messages without a repeated CSV scan.
    failure = [0] * len(pattern)
    length = 0
    for index in range(1, len(pattern)):
        while length and pattern[index] != pattern[length]:
            length = failure[length - 1]
        if pattern[index] == pattern[length]:
            length += 1
        failure[index] = length
    length = 0
    for index, row in enumerate(rows):
        while length and row != pattern[length]:
            length = failure[length - 1]
        if row == pattern[length]:
            length += 1
        if length == len(pattern):
            yield index - length + 1
            length = failure[length - 1]


def infer_kakao_photo_occurrence(
    normalization: KakaoMessageNormalization,
    *,
    csv_receipt: ManualDownloadResult,
    csv_observation: ManualPageObservation,
    photo_receipt: ManualDownloadResult,
    photo_observation: ManualPageObservation,
) -> KakaoPhotoOccurrence | None:
    """Use only verified reader/parser results, not operator-supplied mappings.

    This does not assign a role, timezone, room authority or a canonical attachment.
    None means evidence is insufficient; the underlying photo must still be retained.
    """
    csv_doc, photo_doc = csv_observation.document, photo_observation.document
    target = photo_observation.target.path
    csv_member = csv_receipt.member
    if (
        csv_doc is None
        or photo_doc is None
        or csv_doc.path != photo_doc.path
        or csv_receipt.capture_id == photo_receipt.capture_id
        or csv_member is None
        or (csv_member.sha256, csv_member.size_bytes)
        != (normalization.source_sha256, normalization.source_bytes)
        or csv_observation.target.kind != "BLOB"
        or photo_observation.target.kind != "SAME_ORIGIN_PATH"
        or target is None
        or not _same_capture(csv_receipt, csv_observation)
        or not _same_capture(photo_receipt, photo_observation)
        or any(
            getattr(csv_observation, name) != getattr(photo_observation, name)
            for name in _FENCE_FIELDS
        )
    ):
        return None
    groups = _groups(photo_doc)
    keys = observed_manual_room_keys(photo_doc.path, target)
    if (
        keys is None
        or _room(groups, photo_doc.path) != keys
        or _room(_groups(csv_doc), csv_doc.path) != keys
    ):
        return None
    targets = [
        i for i, group in enumerate(groups) for link in group.photo_links() if link == target
    ]
    if len(targets) != 1:
        return None
    index = targets[0]
    tokens = tuple(group.token() for group in groups)
    if tokens[index] != (True, _PHOTO_MARKER):
        return None

    # Use the nearest complete text anchor in each direction; never skip a gap.
    def anchor(positions: Iterable[int]) -> int | None:
        for position in positions:
            token = tokens[position]
            if token is None:
                return None
            if not token[0]:
                return position
        return None

    before = anchor(range(index - 1, -1, -1))
    after = anchor(range(index + 1, len(groups)))
    if before is None or after is None or tokens[before] == tokens[after]:
        return None
    pattern = tuple(token[1] for token in tokens[before : after + 1] if token is not None)
    # Compare both orientations; a match in both is ambiguous even if dates sort.
    found = None
    for candidate, offset in (
        (pattern, index - before),
        (pattern[::-1], after - index),
    ):
        starts = _matching_starts(
            (_text_key(message.text) for message in normalization.messages),
            tuple(map(_text_key, candidate)),
        )
        for start in starts:
            if not all(
                _line_endings(normalization.messages[start + i].text) == text
                for i, text in enumerate(candidate)
            ):
                return None
            if found is not None:
                return None
            found = normalization.messages[start + offset].row_ordinal
    return None if found is None else KakaoPhotoOccurrence(found)
