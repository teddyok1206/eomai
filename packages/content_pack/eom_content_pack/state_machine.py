"""Deterministic Content Pack release lifecycle."""

from enum import StrEnum

from eom_content_pack.errors import ContentPackError, ContentPackErrorCode


class ContentPackState(StrEnum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    RELEASED = "RELEASED"
    DEPRECATED = "DEPRECATED"
    RETIRED = "RETIRED"
    REJECTED = "REJECTED"


TRANSITIONS: dict[ContentPackState, frozenset[ContentPackState]] = {
    ContentPackState.DRAFT: frozenset({ContentPackState.VALIDATED}),
    ContentPackState.VALIDATED: frozenset({ContentPackState.RELEASED, ContentPackState.REJECTED}),
    ContentPackState.RELEASED: frozenset({ContentPackState.DEPRECATED}),
    ContentPackState.DEPRECATED: frozenset({ContentPackState.RETIRED}),
    ContentPackState.RETIRED: frozenset(),
    ContentPackState.REJECTED: frozenset(),
}


def require_transition(current: ContentPackState, target: ContentPackState) -> None:
    if target not in TRANSITIONS[current]:
        raise ContentPackError(
            ContentPackErrorCode.CONTENT_PACK_RELEASE_IMMUTABLE,
            f"invalid content pack transition: {current.value} -> {target.value}",
        )
