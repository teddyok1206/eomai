"""Administrator settings and exact revision reads; no runtime/auth mutation."""

import re
from datetime import datetime
from uuid import uuid4

from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_protocol.general_chat_model_settings import ChatModelSettings, read_chat_model_settings
from eom_workflow.control_plane import ModelCandidate
from jsonschema import ValidationError as SchemaError
from sqlalchemy import select
from sqlalchemy.orm import Session

from eom_orchestrator.chat_slot_reservation import reserved_chat_slot_id
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.general_chat_model_settings_store import (
    ChatModelSettingsRecord,
    ChatModelSettingsRevisionRecord,
)
from eom_orchestrator.preset_model_selection import slot_model_candidates


def current_chat_model_settings(session: Session) -> ChatModelSettings | None:
    logical = session.get(ChatModelSettingsRecord, "general-chat")
    if logical is None:
        raise ControlPlaneError("CONTROL_CHAT_MODEL_SETTINGS_MISSING", "settings not installed")
    if logical.current_revision_id is None:
        if logical.resource_version != 1:
            raise ControlPlaneError(
                "CONTROL_CHAT_MODEL_SETTINGS_INVALID", "settings pointer differs"
            )
        return None
    row = session.get(ChatModelSettingsRevisionRecord, logical.current_revision_id)
    try:
        if row is None:
            raise ValueError()
        value = read_chat_model_settings(row.canonical_document)
        if (value.revision_id, value.revision_number, value.sha256) != (
            row.revision_id,
            row.revision_number,
            row.sha256,
        ) or value.revision_number != logical.resource_version:
            raise ValueError()
        return value
    except (ValueError, SchemaError) as exc:
        raise ControlPlaneError(
            "CONTROL_CHAT_MODEL_SETTINGS_INVALID", "settings revision differs"
        ) from exc


def chat_model_candidates(session: Session, *, observed_at: datetime) -> tuple[ModelCandidate, ...]:
    slot = reserved_chat_slot_id(session)
    if slot != "06":
        return ()
    return tuple(
        v
        for v in slot_model_candidates(session, slot_id=slot, observed_at=observed_at)
        if re.fullmatch(r"[A-Za-z0-9._-]{1,128}", v.model)
    )


def change_chat_model_settings(
    session: Session,
    *,
    model: str,
    reasoning_effort: str,
    expected_version: int,
    requested_by: str,
    request_key: str,
    requested_at: datetime,
) -> ChatModelSettings:
    """Caller authorizes ADMIN and owns transaction; exact replay precedes CAS."""
    logical = session.scalar(
        select(ChatModelSettingsRecord)
        .where(ChatModelSettingsRecord.settings_id == "general-chat")
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if logical is None:
        raise ControlPlaneError("CONTROL_CHAT_MODEL_SETTINGS_MISSING", "settings not installed")
    key_hash = sha256_bytes(canonical_json_bytes({"operator": requested_by, "key": request_key}))
    request_hash = sha256_bytes(
        canonical_json_bytes(
            {
                "model": model,
                "reasoning_effort": reasoning_effort,
                "expected_version": expected_version,
            }
        )
    )
    prior = session.scalar(
        select(ChatModelSettingsRevisionRecord).where(
            ChatModelSettingsRevisionRecord.request_key_sha256 == key_hash
        )
    )
    if prior is not None:
        if prior.request_sha256 != request_hash:
            raise ControlPlaneError("CONTROL_CHAT_MODEL_REPLAY_CONFLICT", "request intent differs")
        return read_chat_model_settings(prior.canonical_document)
    current_chat_model_settings(session)
    if logical.resource_version != expected_version:
        raise ControlPlaneError("CONTROL_CHAT_MODEL_VERSION_STALE", "settings changed")
    if (model, reasoning_effort) not in {
        (v.model, str(v.reasoning_effort))
        for v in chat_model_candidates(session, observed_at=requested_at)
    }:
        raise ControlPlaneError(
            "CONTROL_CHAT_MODEL_UNAVAILABLE", "model/effort not admitted on reserved slot"
        )
    body = dict(
        schema_version="general-chat-model-settings/1.0",
        settings_id="general-chat",
        revision_id="chatmodelrev_" + uuid4().hex,
        revision_number=expected_version + 1,
        model=model,
        reasoning_effort=reasoning_effort,
        created_by=requested_by,
        created_at=requested_at.isoformat().replace("+00:00", "Z"),
    )
    document = body | {"sha256": sha256_bytes(canonical_json_bytes(body))}
    settings = read_chat_model_settings(document)
    session.add(
        ChatModelSettingsRevisionRecord(
            revision_id=settings.revision_id,
            revision_number=settings.revision_number,
            sha256=settings.sha256,
            request_key_sha256=key_hash,
            request_sha256=request_hash,
            canonical_document=settings.model_dump(mode="json"),
        )
    )
    session.flush()
    logical.current_revision_id = settings.revision_id
    logical.resource_version = settings.revision_number
    session.flush()
    return settings
