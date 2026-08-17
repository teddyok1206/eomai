"""Sanitized cross-domain event feed DTOs."""

from eom_api_contracts.common import ApiModel, OpaqueId, UtcDatetime


class EventView(ApiModel):
    event_id: str
    aggregate_type: str
    aggregate_id: OpaqueId
    event_type: str
    prior_state: str | None = None
    new_state: str | None = None
    actor_id: str
    created_at: UtcDatetime
    summary: str
