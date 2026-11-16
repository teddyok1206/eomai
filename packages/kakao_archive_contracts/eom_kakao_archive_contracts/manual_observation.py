"""Bounded read-only document evidence, never a click plan or source permission."""

from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from typing import Literal, Self

from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from pydantic import ConfigDict, Field, StrictBool, model_validator

from .kakao_remote import BrowserRunId, Epoch, ProfileId, UtcDatetime
from .render import FrozenModel, canonical_bytes, sha256

SCHEMA_SHA256 = "sha256:d5a0016a7208ea6c7a6c23a0a6cb0cb266c15ace7ceed608dcf4715e52ae559f"
MAX_OBSERVATION_BYTES = 1024 * 1024
MAX_TEXT_CODEPOINTS = 65536


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    raw = (
        files("eom_kakao_archive_contracts")
        .joinpath("schemas/manual-page-observation-v1.schema.json")
        .read_bytes()
    )
    if sha256(raw) != SCHEMA_SHA256:
        raise ValueError("KAKAO_OBSERVATION_SCHEMA_HASH_MISMATCH")
    schema = json.loads(raw)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


class ManualDownloadTarget(FrozenModel):
    kind: Literal["SAME_ORIGIN_PATH", "BLOB", "UNAVAILABLE"]
    path: str | None


class ManualIdentityAttributes(FrozenModel):
    model_config = ConfigDict(serialize_by_alias=True)

    data_id: str | None = Field(alias="data-id")
    data_chat_id: str | None = Field(alias="data-chat-id")
    data_message_id: str | None = Field(alias="data-message-id")
    data_log_id: str | None = Field(alias="data-log-id")


class ManualDocumentNode(FrozenModel):
    index: int = Field(strict=True, ge=0, le=2047)
    parent_index: int | None = Field(strict=True, ge=0, le=2047)
    tag: str = Field(pattern=r"^[a-z][a-z0-9-]{0,31}$")
    classes: tuple[str, ...] = Field(max_length=8)
    role: str | None
    label: str | None
    text: str | None
    identities: ManualIdentityAttributes
    link_path: str | None
    is_image: StrictBool


class ManualDocument(FrozenModel):
    origin: Literal["https://business.kakao.com"]
    path: str
    truncated: StrictBool
    nodes: tuple[ManualDocumentNode, ...] = Field(max_length=2048)

    @model_validator(mode="after")
    def ordered_tree(self) -> Self:
        text_size = 0
        for index, node in enumerate(self.nodes):
            if node.index != index or (
                node.parent_index is not None and node.parent_index >= index
            ):
                raise ValueError("KAKAO_OBSERVATION_NODE_ORDER_INVALID")
            text_size += len(node.text or "") + len(node.label or "")
        if text_size > MAX_TEXT_CODEPOINTS:
            raise ValueError("KAKAO_OBSERVATION_TEXT_LIMIT")
        return self


class ManualPageObservation(FrozenModel):
    schema_version: Literal["kakao-manual-page-observation/1.0"] = (
        "kakao-manual-page-observation/1.0"
    )
    capture_id: str = Field(pattern=r"^kakaodownload_[0-9a-f]{32}$")
    profile_id: ProfileId
    browser_run_id: BrowserRunId
    fence_epoch: Epoch
    page_instance_id: str = Field(pattern=r"^kakaopage_[0-9a-f]{32}$")
    observed_at: UtcDatetime
    status: Literal["OBSERVED", "UNAVAILABLE"]
    target: ManualDownloadTarget
    document: ManualDocument | None
    error_code: (
        Literal[
            "UNSUPPORTED_ORIGIN", "OBSERVATION_TIMEOUT", "OBSERVATION_FAILED", "OBSERVATION_INVALID"
        ]
        | None
    )

    @model_validator(mode="after")
    def closed_evidence(self) -> Self:
        value = self.model_dump(mode="json", by_alias=True)
        try:
            _validator().validate(value)
        except ValidationError:
            raise ValueError("KAKAO_OBSERVATION_INVALID") from None
        if len(canonical_bytes(value)) > MAX_OBSERVATION_BYTES:
            raise ValueError("KAKAO_OBSERVATION_SIZE_LIMIT")
        return self
