"""Web wire projection; no dependency on owner DB or API source packages."""

from typing import Literal, Self

from pydantic import Field, model_validator

from eom_web_gui.contracts import (
    ExecutionPresetLifecycleCommand,
    PresetModelCandidateDraft,
    WebModel,
)


class ChatModelSettingsSubmission(ExecutionPresetLifecycleCommand, PresetModelCandidateDraft):
    pass


class ChatModelSettingsView(WebModel):
    current: PresetModelCandidateDraft | None
    revision_id: str | None = Field(pattern=r"^chatmodelrev_[0-9a-f]{32}$")
    sha256: str | None = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    resource_version: int = Field(ge=1)
    candidates: tuple[PresetModelCandidateDraft, ...] = Field(max_length=320)
    applies_to: Literal["NEXT_TURN"] = "NEXT_TURN"
    dedicated_slot: Literal["06"] = "06"

    @model_validator(mode="after")
    def exact_current(self) -> Self:
        if (
            (self.current is None) != (self.resource_version == 1)
            or (self.current is None) != (self.revision_id is None)
            or (self.current is None) != (self.sha256 is None)
        ):
            raise ValueError("chat settings current pin differs")
        return self
