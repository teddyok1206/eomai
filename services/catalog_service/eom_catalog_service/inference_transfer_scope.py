"""Immutable population restrictions shared by inference-transfer read boundaries."""

import re
from enum import StrEnum


def require_item_revision_selection(values: tuple[str, ...]) -> None:
    """Bounded immutable selection only; empty means the existing full population."""
    if (
        type(values) is not tuple
        or len(values) > 1024
        or any(
            type(value) is not str or re.fullmatch(r"itemrev_[0-9a-f]{32}", value) is None
            for value in values
        )
        or values != tuple(sorted(set(values)))
    ):
        raise ValueError("exact Item revision selection must be bounded, sorted and unique")


class InferenceTransferPopulationScope(StrEnum):
    """Selection limits only: never substitutes actor or pinned policy authority."""

    ALL_ADMITTED_GRAPH_ITEMS = "ALL_ADMITTED_GRAPH_ITEMS"
    OCCURRENCE_BACKED_PAST_EXAM = "OCCURRENCE_BACKED_PAST_EXAM"
