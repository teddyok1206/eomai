"""Immutable population restrictions shared by inference-transfer read boundaries."""

from enum import StrEnum


class InferenceTransferPopulationScope(StrEnum):
    """Selection limits only: never substitutes actor or pinned policy authority."""

    ALL_ADMITTED_GRAPH_ITEMS = "ALL_ADMITTED_GRAPH_ITEMS"
    OCCURRENCE_BACKED_PAST_EXAM = "OCCURRENCE_BACKED_PAST_EXAM"
