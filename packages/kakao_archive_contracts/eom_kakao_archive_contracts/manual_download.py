"""Local untrusted download observations; no provider room or admission authority."""

import json
from functools import lru_cache
from importlib.resources import files
from typing import Literal, Self

from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from pydantic import Field, model_validator

from .kakao_remote import BrowserRunId, Epoch, ProfileId, UtcDatetime
from .render import FrozenModel, sha256

SCHEMA_SHA256 = "sha256:7d03e8e61e77c1d87ef252ffee51bc61dd6a7239fe7d7ba5dd39f29d0ec9d380"


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    raw = (
        files("eom_kakao_archive_contracts")
        .joinpath("schemas/manual-download-v1.schema.json")
        .read_bytes()
    )
    if sha256(raw) != SCHEMA_SHA256:
        raise ValueError("KAKAO_DOWNLOAD_SCHEMA_HASH_MISMATCH")
    schema = json.loads(raw)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


class _Identity(FrozenModel):
    schema_version: Literal["kakao-manual-download/1.0"] = "kakao-manual-download/1.0"
    capture_id: str = Field(pattern=r"^kakaodownload_[0-9a-f]{32}$")
    profile_id: ProfileId
    browser_run_id: BrowserRunId
    fence_epoch: Epoch
    page_instance_id: str = Field(pattern=r"^kakaopage_[0-9a-f]{32}$")
    started_at: UtcDatetime

    @model_validator(mode="after")
    def schema_valid(self) -> Self:
        try:
            _validator().validate(self.model_dump(mode="json"))
        except ValidationError:
            raise ValueError("KAKAO_DOWNLOAD_RECEIPT_INVALID") from None
        return self


class ManualDownloadStart(_Identity):
    phase: Literal["STARTED"] = "STARTED"


class ManualDownloadMember(FrozenModel):
    relative_path: Literal["payload.bin"] = "payload.bin"
    size_bytes: int = Field(strict=True, ge=1, le=32 * 1024 * 1024)
    sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class ManualDownloadResult(_Identity):
    phase: Literal["RECEIVED", "FAILED"]
    completed_at: UtcDatetime
    suggested_filename: str | None = Field(min_length=1, max_length=1024)
    member: ManualDownloadMember | None
    error_code: (
        Literal[
            "DOWNLOAD_FAILED",
            "DOWNLOAD_CANCELLED",
            "DOWNLOAD_TIMEOUT",
            "DOWNLOAD_LIMIT",
            "DOWNLOAD_EMPTY",
            "DOWNLOAD_FILE_INVALID",
        ]
        | None
    )

    @model_validator(mode="after")
    def time_order(self) -> Self:
        if self.completed_at < self.started_at:
            raise ValueError("KAKAO_DOWNLOAD_RECEIPT_INVALID")
        return self
