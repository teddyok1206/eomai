"""Small immutable model selection; not a Workflow, prompt or permission grant."""

import json
from functools import lru_cache
from importlib.resources import files
from typing import Literal, Self

from eom_identifiers import canonical_json_bytes, sha256_bytes
from jsonschema import Draft202012Validator
from pydantic import Field, model_validator

from eom_protocol.general_chat import ChatBoundaryValue
from eom_protocol.models import UtcDatetime

ReasoningEffort = Literal["minimal", "low", "medium", "high", "xhigh"]


class ChatModelSettingsPin(ChatBoundaryValue):
    revision_id: str = Field(pattern=r"^chatmodelrev_[0-9a-f]{32}$")
    sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class ChatModelSettings(ChatBoundaryValue):
    schema_version: Literal["general-chat-model-settings/1.0"] = "general-chat-model-settings/1.0"
    settings_id: Literal["general-chat"] = "general-chat"
    revision_id: str = Field(pattern=r"^chatmodelrev_[0-9a-f]{32}$")
    revision_number: int = Field(ge=1, strict=True)
    model: str = Field(pattern=r"^[A-Za-z0-9._-]{1,128}$")
    reasoning_effort: ReasoningEffort
    created_by: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    created_at: UtcDatetime
    sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def exact_hash(self) -> Self:
        if self.sha256 != sha256_bytes(
            canonical_json_bytes(self.model_dump(mode="json", exclude={"sha256"}))
        ):
            raise ValueError("chat model settings hash differs")
        return self

    @property
    def pin(self) -> ChatModelSettingsPin:
        return ChatModelSettingsPin(revision_id=self.revision_id, sha256=self.sha256)


@lru_cache(maxsize=1)
def _settings_validator() -> Draft202012Validator:
    schema = json.loads(
        files("eom_protocol")
        .joinpath("schemas/general-chat-model-settings.schema.json")
        .read_bytes()
    )
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def read_chat_model_settings(document: object) -> ChatModelSettings:
    _settings_validator().validate(document)
    return ChatModelSettings.model_validate(document)
