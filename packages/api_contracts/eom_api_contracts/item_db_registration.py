"""DB-specific registration views; source category is independent of approval."""

from typing import Literal

from pydantic import Field

from eom_api_contracts.common import ApiModel
from eom_api_contracts.external_item_db import ExternalItemDbEntryView

ApprovalState = Literal[
    "UNREGISTERED", "DRAFT", "IN_REVIEW", "APPROVED", "REJECTED", "SUPERSEDED", "RETIRED"
]


class ItemDbRegistrationView(ApiModel):
    item_id: str = Field(pattern=r"^item_[0-9a-f]{32}$")
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    item_manifest_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    approval_state: Literal["DRAFT", "IN_REVIEW", "APPROVED", "REJECTED", "SUPERSEDED", "RETIRED"]
    difficulty_band: str | None = Field(default=None, max_length=64)
    item_type_key: str = Field(min_length=1, max_length=128)


class CreativeItemDbEntryView(ApiModel):
    source: ExternalItemDbEntryView
    registration: ItemDbRegistrationView | None


class AiItemDbEntryView(ApiModel):
    registration: ItemDbRegistrationView
    title: str = Field(min_length=1, max_length=512)
