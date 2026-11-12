"""Current feature-oriented model settings read contract."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from eom_api_contracts.common import ApiModel
from eom_api_contracts.control_plane import ExecutionPresetView


class FeatureModelStageView(ApiModel):
    stage_key: str = Field(pattern=r"^[a-z][a-z0-9-]{1,63}$")
    label: str = Field(min_length=1, max_length=80)
    preset: ExecutionPresetView


class FeatureModelSettingsView(ApiModel):
    model_config = ApiModel.model_config | {
        "json_schema_extra": {
            "allOf": [
                {
                    "if": {"properties": {"feature_key": {"const": "chat"}}},
                    "then": {"properties": {"kind": {"const": "CHAT"}, "stages": {"maxItems": 0}}},
                    "else": {
                        "properties": {"kind": {"const": "WORKFLOW"}, "stages": {"minItems": 1}}
                    },
                }
            ]
        }
    }
    feature_key: Literal[
        "item-authoring",
        "material-review",
        "material-learning",
        "item-registration",
        "similarity-comparison",
        "customer-support",
        "chat",
    ]
    label: str = Field(min_length=1, max_length=80)
    kind: Literal["WORKFLOW", "CHAT"]
    stages: tuple[FeatureModelStageView, ...] = Field(max_length=8)

    @model_validator(mode="after")
    def unique_current_stages(self) -> FeatureModelSettingsView:
        chat = self.feature_key == "chat"
        if (self.kind == "CHAT") != chat or bool(self.stages) == chat:
            raise ValueError("feature kind and stages differ")
        if len({v.stage_key for v in self.stages}) != len(self.stages) or len(
            {v.preset.preset_id for v in self.stages}
        ) != len(self.stages):
            raise ValueError("feature stages must be unique")
        for stage in self.stages:
            preset = stage.preset
            if preset.state != "ACTIVE":
                raise ValueError("feature exposes only a current active preset")
            revisions = {v.preset_revision_id: v for v in preset.revisions}
            current = revisions.get(preset.current_revision_id or "")
            if (
                current is None
                or current.state != "RELEASED"
                or current.preset_id != preset.preset_id
            ):
                raise ValueError("feature current revision owner differs")
            if len(revisions) != len(preset.revisions) or any(
                v.preset_id != preset.preset_id
                or (
                    v.preset_revision_id != current.preset_revision_id
                    and (v.state != "DRAFT" or v.revision_number <= current.revision_number)
                )
                for v in preset.revisions
            ):
                raise ValueError("feature cannot expose historical revisions")
        return self
