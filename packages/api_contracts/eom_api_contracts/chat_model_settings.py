"""Administrator-only ChatGPT model settings in the unified settings screen."""

from typing import Literal, Self

from pydantic import Field, model_validator

from eom_api_contracts.common import ApiModel, Sha256
from eom_api_contracts.control_plane import ModelCandidateInput


class ChatModelSettingsRequest(ModelCandidateInput):
    pass


class ChatModelSettingsView(ApiModel):
    current: ModelCandidateInput | None
    revision_id: str | None = Field(pattern=r"^chatmodelrev_[0-9a-f]{32}$")
    sha256: Sha256 | None
    resource_version: int = Field(ge=1)
    candidates: tuple[ModelCandidateInput, ...] = Field(max_length=320)
    applies_to: Literal["NEXT_TURN"] = "NEXT_TURN"
    dedicated_slot: Literal["06"] = "06"

    @model_validator(mode="after")
    def exact_current(self) -> Self:
        absent = self.current is None
        if (
            absent != (self.resource_version == 1)
            or absent != (self.revision_id is None)
            or absent != (self.sha256 is None)
        ):
            raise ValueError("chat settings current pin differs")
        return self
