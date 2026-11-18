"""Local download handoff; no execution or source admission authority."""

import json
from functools import lru_cache
from importlib.resources import files
from typing import Literal, Self

from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from pydantic import Field, model_validator
from pydantic import ValidationError as PydanticValidationError
from referencing import Registry, Resource

from .capture import CsvMember
from .kakao_remote import UtcDatetime
from .manual_observation import MAX_OBSERVATION_BYTES, ManualDocument
from .render import FrozenModel, Sha256, canonical_bytes, sha256

OPEN_ROOM_RECEIPT_NAME = "open-room.json"
MAX_OPEN_ROOM_RECEIPT_BYTES = 7 * MAX_OBSERVATION_BYTES + 4096
_SCHEMAS = (
    (
        "open-room-download-v1.schema.json",
        "732d08e28170cab5ea9db16fed28b2c667d58631b0fa87857a224967e95da0ec",
    ),
    (
        "worker-collection-v1.schema.json",
        "9c9cd7cc4438a194acd157775261b4ac846e0b7ab12ee2aa05e79560777746ce",
    ),
    (
        "manual-page-observation-v1.schema.json",
        "d5a0016a7208ea6c7a6c23a0a6cb0cb266c15ace7ceed608dcf4715e52ae559f",
    ),
)


class InvalidOpenRoomDownloadReceipt(ValueError):
    """The supplied bytes fail the receipt contract, not installed schema integrity."""


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    schemas = files("eom_kakao_archive_contracts").joinpath("schemas")
    resources = []
    for name, digest in _SCHEMAS:
        raw = schemas.joinpath(name).read_bytes()
        if sha256(raw) != f"sha256:{digest}":
            raise ValueError("KAKAO_OPEN_ROOM_SCHEMA_MISMATCH")
        resource = Resource.from_contents(json.loads(raw))
        Draft202012Validator.check_schema(resource.contents)
        resources.append(resource)
    return Draft202012Validator(
        resources[0].contents,
        registry=Registry().with_resources(
            (resource.contents["$id"], resource) for resource in resources
        ),
        format_checker=FormatChecker(),
    )


class RoomPhotoReceipt(FrozenModel):
    relative_path: str
    sha256: Sha256
    size_bytes: int = Field(strict=True, ge=1, le=32 * 1024 * 1024)
    target: str = Field(repr=False)
    document: ManualDocument | None = Field(repr=False)


class OpenRoomDownloadReceipt(FrozenModel):
    schema_version: Literal["kakao-open-room-download/1.0"] = "kakao-open-room-download/1.0"
    command_sha256: Sha256
    started_at: UtcDatetime
    ended_at: UtcDatetime
    raw_csv: CsvMember
    csv_document: ManualDocument | None = Field(repr=False)
    photos: tuple[RoomPhotoReceipt, ...] = Field(max_length=6, repr=False)
    unresolved_visible_bubbles: int = Field(strict=True, ge=0, le=2048)

    @model_validator(mode="after")
    def validate_receipt(self) -> Self:
        if self.started_at > self.ended_at or len(
            {photo.relative_path for photo in self.photos}
        ) != len(self.photos):
            raise ValueError("KAKAO_OPEN_ROOM_RECEIPT_INVALID")
        for document in (self.csv_document, *(photo.document for photo in self.photos)):
            if (
                document is not None
                and len(canonical_bytes(document.model_dump(mode="json"))) > MAX_OBSERVATION_BYTES
            ):
                raise ValueError("KAKAO_OPEN_ROOM_RECEIPT_TOO_LARGE")
        value = self.model_dump(mode="json")
        try:
            _validator().validate(value)
        except ValidationError:
            raise ValueError("KAKAO_OPEN_ROOM_RECEIPT_INVALID") from None
        return self

    def encoded(self) -> bytes:
        return canonical_bytes(self.model_dump(mode="json"))

    @classmethod
    def decode(cls, raw: bytes) -> Self:
        if not 0 < len(raw) <= MAX_OPEN_ROOM_RECEIPT_BYTES:
            raise InvalidOpenRoomDownloadReceipt("KAKAO_OPEN_ROOM_RECEIPT_TOO_LARGE")
        _validator()  # Installed schema errors are not attributable to this attempt's bytes.
        try:
            receipt = cls.model_validate_json(raw)
        except PydanticValidationError:
            raise InvalidOpenRoomDownloadReceipt("KAKAO_OPEN_ROOM_RECEIPT_INVALID") from None
        if receipt.encoded() != raw:
            raise InvalidOpenRoomDownloadReceipt("KAKAO_OPEN_ROOM_RECEIPT_INVALID")
        return receipt
