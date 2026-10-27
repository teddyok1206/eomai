"""Pinned, authority-free HTTP selection for one creative source learning request."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from eom_api_contracts.common import ApiModel


class ExternalItemLearningStartV1(ApiModel):
    schema_version: Literal["external-item-learning-start/1.0"] = "external-item-learning-start/1.0"
    import_id: str = Field(pattern=r"^extimport_[0-9a-f]{32}$")
    external_number: str = Field(pattern=r"^[0-9]{5}$")
    source_revision_id: str = Field(pattern=r"^extitemrev_[0-9a-f]{32}$")
    observation_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    selected_edition: Literal[2, 3]
