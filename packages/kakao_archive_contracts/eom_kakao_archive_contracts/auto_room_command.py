"""Allow only one pinned collection command and three scope keys inside an AUTO epoch."""

import json
from functools import lru_cache
from importlib.resources import files
from typing import Annotated, Literal, Self

from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from pydantic import Field, model_validator
from referencing import Registry, Resource

from .capture import SCHEMA_SHA256, CaptureCommand
from .kakao_remote import ProfileFence
from .render import FrozenModel, canonical_bytes, sha256

MAX_AUTO_ROOM_COMMAND_BYTES = 16384
AUTO_ROOM_SCHEMA_SHA256 = "sha256:cb935287af1f2024e3c0140694ea5a12919b78c900ab08749794f570804b4e36"
ProviderKey = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")]


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    directory = files("eom_kakao_archive_contracts").joinpath("schemas")
    raw = directory.joinpath("auto-room-command-v1.schema.json").read_bytes()
    capture = directory.joinpath("worker-collection-v1.schema.json").read_bytes()
    if sha256(raw) != AUTO_ROOM_SCHEMA_SHA256 or sha256(capture) != SCHEMA_SHA256:
        raise ValueError("KAKAO_AUTO_ROOM_SCHEMA_MISMATCH")
    schema = json.loads(raw)
    prior = json.loads(capture)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(
        schema,
        registry=Registry().with_resource(prior["$id"], Resource.from_contents(prior)),
        format_checker=FormatChecker(),
    )


class AutoRoomCommand(FrozenModel):
    schema_version: Literal["kakao-auto-room-command/1.0"] = "kakao-auto-room-command/1.0"
    command: CaptureCommand
    space_key: ProviderKey = Field(repr=False)
    channel_key: ProviderKey = Field(repr=False)
    room_key: ProviderKey = Field(repr=False)

    @model_validator(mode="after")
    def closed(self) -> Self:
        try:
            _validator().validate(self.model_dump(mode="json"))
        except ValidationError:
            raise ValueError("KAKAO_AUTO_ROOM_COMMAND_INVALID") from None
        return self

    def encoded(self) -> bytes:
        return canonical_bytes(self.model_dump(mode="json"))

    @classmethod
    def decode(cls, raw: bytes, fence: ProfileFence) -> Self:
        if not 0 < len(raw) <= MAX_AUTO_ROOM_COMMAND_BYTES:
            raise ValueError("KAKAO_AUTO_ROOM_COMMAND_INVALID")
        selected = cls.model_validate_json(raw)
        command = selected.command
        if (
            selected.encoded() != raw
            or fence.mode != "AUTO"
            or command.profile_id != fence.profile_id
            or command.browser_run_id != fence.browser_run_id
            or command.execution.fence != fence.fence_epoch
        ):
            raise ValueError("KAKAO_AUTO_ROOM_FENCE_MISMATCH")
        return selected
