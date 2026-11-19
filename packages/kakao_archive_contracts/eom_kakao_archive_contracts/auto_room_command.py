"""Allow only one pinned collection command and three scope keys inside an AUTO epoch."""

import json
from functools import lru_cache
from importlib.resources import files
from typing import Annotated, Literal, Self

from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from pydantic import Field, TypeAdapter, model_validator
from referencing import Registry, Resource

from .capture import SCHEMA_SHA256, CaptureCommand
from .kakao_remote import ProfileFence
from .render import FrozenModel, canonical_bytes, sha256

MAX_AUTO_ROOM_COMMAND_BYTES = 16384
AUTO_ROOM_SCHEMA_SHA256 = "sha256:cb935287af1f2024e3c0140694ea5a12919b78c900ab08749794f570804b4e36"
POPUP_ROOM_SCHEMA_SHA256 = "sha256:ce55e05ce212e13c354083f3a9a9126f98d6575962c80a0c88f45ff48f75fc93"
ProviderKey = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")]
RoomNavigation = Literal["LIST", "VERIFIED_POPUP"]
_SCHEMAS = {
    "kakao-auto-room-command/1.0": ("auto-room-command-v1.schema.json", AUTO_ROOM_SCHEMA_SHA256),
    "kakao-auto-room-command/2.0": ("auto-room-command-v2.schema.json", POPUP_ROOM_SCHEMA_SHA256),
}


@lru_cache(maxsize=2)
def _validator(version: str) -> Draft202012Validator:
    directory = files("eom_kakao_archive_contracts").joinpath("schemas")
    name, expected = _SCHEMAS[version]
    raw = directory.joinpath(name).read_bytes()
    capture = directory.joinpath("worker-collection-v1.schema.json").read_bytes()
    if sha256(raw) != expected or sha256(capture) != SCHEMA_SHA256:
        raise ValueError("KAKAO_AUTO_ROOM_SCHEMA_MISMATCH")
    schema = json.loads(raw)
    prior = json.loads(capture)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(
        schema,
        registry=Registry().with_resource(prior["$id"], Resource.from_contents(prior)),
        format_checker=FormatChecker(),
    )


class _AutoRoomScope(FrozenModel):
    command: CaptureCommand
    space_key: ProviderKey = Field(repr=False)
    channel_key: ProviderKey = Field(repr=False)
    room_key: ProviderKey = Field(repr=False)

    def validate_schema(self, version: str) -> None:
        try:
            _validator(version).validate(self.model_dump(mode="json"))
        except ValidationError:
            raise ValueError("KAKAO_AUTO_ROOM_COMMAND_INVALID") from None

    def encoded(self) -> bytes:
        return canonical_bytes(self.model_dump(mode="json"))

    def verify_fence(self, raw: bytes, fence: ProfileFence) -> Self:
        command = self.command
        if (
            self.encoded() != raw
            or fence.mode != "AUTO"
            or command.profile_id != fence.profile_id
            or command.browser_run_id != fence.browser_run_id
            or command.execution.fence != fence.fence_epoch
        ):
            raise ValueError("KAKAO_AUTO_ROOM_FENCE_MISMATCH")
        return self


class AutoRoomCommand(_AutoRoomScope):
    schema_version: Literal["kakao-auto-room-command/1.0"] = "kakao-auto-room-command/1.0"

    @model_validator(mode="after")
    def closed(self) -> Self:
        self.validate_schema(self.schema_version)
        return self

    @classmethod
    def decode(cls, raw: bytes, fence: ProfileFence) -> Self:
        if not 0 < len(raw) <= MAX_AUTO_ROOM_COMMAND_BYTES:
            raise ValueError("KAKAO_AUTO_ROOM_COMMAND_INVALID")
        return cls.model_validate_json(raw).verify_fence(raw, fence)


class AutoRoomPopupCommand(_AutoRoomScope):
    schema_version: Literal["kakao-auto-room-command/2.0"] = "kakao-auto-room-command/2.0"

    @model_validator(mode="after")
    def closed(self) -> Self:
        self.validate_schema(self.schema_version)
        return self


type AutoRoomInput = AutoRoomCommand | AutoRoomPopupCommand
_AUTO_ROOM_INPUT: TypeAdapter[AutoRoomInput] = TypeAdapter(
    Annotated[AutoRoomCommand | AutoRoomPopupCommand, Field(discriminator="schema_version")]
)


def decode_auto_room_input(raw: bytes, fence: ProfileFence) -> AutoRoomInput:
    if not 0 < len(raw) <= MAX_AUTO_ROOM_COMMAND_BYTES:
        raise ValueError("KAKAO_AUTO_ROOM_COMMAND_INVALID")
    return _AUTO_ROOM_INPUT.validate_json(raw).verify_fence(raw, fence)
