"""Opaque identifiers for content pack persistence."""

from uuid import uuid4


def new_content_pack_id() -> str:
    return f"contentpack_{uuid4().hex}"


def new_content_pack_release_id() -> str:
    return f"packrel_{uuid4().hex}"


def new_content_pack_file_id() -> str:
    return f"packfile_{uuid4().hex}"


def new_content_pack_profile_id() -> str:
    return f"packprofile_{uuid4().hex}"


def new_activation_id() -> str:
    return f"activation_{uuid4().hex}"
