"""Deterministic Item, Revision, Deliverable, and Usage Plan lifecycles."""

from __future__ import annotations

from enum import StrEnum

from eom_item_registry.errors import RegistryError, RegistryErrorCode


class ItemState(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"
    DELETED_SOFT = "DELETED_SOFT"


class ItemRevisionState(StrEnum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
    RETIRED = "RETIRED"


class DeliverableState(StrEnum):
    PLANNED = "PLANNED"
    IN_PRODUCTION = "IN_PRODUCTION"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"
    ARCHIVED = "ARCHIVED"


class UsagePlanState(StrEnum):
    PLANNED = "PLANNED"
    RESERVED = "RESERVED"
    CANCELLED = "CANCELLED"
    FULFILLED = "FULFILLED"


REVISION_TRANSITIONS = {
    ItemRevisionState.DRAFT: frozenset({ItemRevisionState.IN_REVIEW, ItemRevisionState.REJECTED}),
    ItemRevisionState.IN_REVIEW: frozenset(
        {ItemRevisionState.APPROVED, ItemRevisionState.REJECTED}
    ),
    ItemRevisionState.APPROVED: frozenset(
        {ItemRevisionState.SUPERSEDED, ItemRevisionState.RETIRED}
    ),
    ItemRevisionState.REJECTED: frozenset(),
    ItemRevisionState.SUPERSEDED: frozenset(),
    ItemRevisionState.RETIRED: frozenset(),
}

USAGE_PLAN_TRANSITIONS = {
    UsagePlanState.PLANNED: frozenset({UsagePlanState.RESERVED, UsagePlanState.CANCELLED}),
    UsagePlanState.RESERVED: frozenset({UsagePlanState.FULFILLED, UsagePlanState.CANCELLED}),
    UsagePlanState.CANCELLED: frozenset(),
    UsagePlanState.FULFILLED: frozenset(),
}


def require_revision_transition(current: ItemRevisionState, target: ItemRevisionState) -> None:
    if target not in REVISION_TRANSITIONS[current]:
        raise RegistryError(
            RegistryErrorCode.ITEM_REVISION_CONFLICT,
            f"invalid item revision transition: {current.value} -> {target.value}",
        )


def require_usage_plan_transition(current: UsagePlanState, target: UsagePlanState) -> None:
    if target not in USAGE_PLAN_TRANSITIONS[current]:
        raise RegistryError(
            RegistryErrorCode.USAGE_PLAN_CONFLICT,
            f"invalid usage plan transition: {current.value} -> {target.value}",
        )
