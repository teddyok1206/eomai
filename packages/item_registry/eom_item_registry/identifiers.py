"""Opaque registry identifiers."""

from uuid import uuid4


def _new(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def new_item_id() -> str:
    return _new("item")


def new_item_revision_id() -> str:
    return _new("itemrev")


def new_item_component_id() -> str:
    return _new("itemcomponent")


def new_item_metadata_id() -> str:
    return _new("itemmeta")


def new_item_provenance_id() -> str:
    return _new("provenance")


def new_item_relationship_id() -> str:
    return _new("relationship")


def new_deliverable_id() -> str:
    return _new("deliverable")


def new_deliverable_revision_id() -> str:
    return _new("delivrev")


def new_usage_plan_id() -> str:
    return _new("usageplan")


def new_usage_record_id() -> str:
    return _new("usagerecord")
