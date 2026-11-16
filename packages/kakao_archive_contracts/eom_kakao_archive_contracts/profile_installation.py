"""A root-installed empty profile receipt, not current runtime or account authority."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from importlib.resources import files
from typing import Annotated, Literal

from jsonschema import Draft202012Validator, ValidationError
from pydantic import Field

from .execution import FrozenModel
from .kakao_remote import ProfileId

SCHEMA_SHA256 = "8c45cfc7bb58dbee779834bae89ed2d86265c203eca3f0603832ce8138f9fcc7"
Nonnegative = Annotated[int, Field(strict=True, ge=0)]


class FreshProfileInstallation(FrozenModel):
    schema_version: Literal["kakao-profile-fresh-install/1.0"]
    profile_id: ProfileId
    profile_device: Nonnegative
    profile_inode: int = Field(strict=True, ge=1)
    profile_mtime_ns: Nonnegative
    profile_ctime_ns: Nonnegative
    install_manifest_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    raw = (
        files("eom_kakao_archive_contracts")
        .joinpath("schemas/fresh-profile-v1.schema.json")
        .read_bytes()
    )
    if hashlib.sha256(raw).hexdigest() != SCHEMA_SHA256:
        raise ValueError("KAKAO_PROFILE_INSTALL_SCHEMA_INVALID")
    schema = json.loads(raw)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def parse_fresh_profile_installation(raw: bytes) -> FreshProfileInstallation:
    if not 0 < len(raw) <= 4096:
        raise ValueError("KAKAO_PROFILE_INSTALL_RECEIPT_INVALID")

    # Reject duplicate JSON fields; the protected receipt has one unambiguous identity.
    def pairs(entries: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in entries:
            if key in value:
                raise ValueError("KAKAO_PROFILE_INSTALL_RECEIPT_INVALID")
            value[key] = item
        return value

    try:
        value = json.loads(raw, object_pairs_hook=pairs)
        _validator().validate(value)
        return FreshProfileInstallation.model_validate(value)
    except (ValueError, ValidationError):
        raise ValueError("KAKAO_PROFILE_INSTALL_RECEIPT_INVALID") from None
