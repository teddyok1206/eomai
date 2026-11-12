"""Indexed current pointer and immutable small chat-model configuration revisions."""

from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from eom_orchestrator.models import Base


class ChatModelSettingsRevisionRecord(Base):
    __tablename__ = "general_chat_model_setting_revisions"
    __table_args__ = (
        UniqueConstraint("revision_number", name="uq_chat_model_revision_number"),
        UniqueConstraint("request_key_sha256", name="uq_chat_model_request_key"),
        CheckConstraint("revision_number >= 1", name="ck_chat_model_revision_number"),
        CheckConstraint(
            "revision_id ~ '^chatmodelrev_[0-9a-f]{32}$'", name="ck_chat_model_revision_id"
        ),
    )
    revision_id: Mapped[str] = mapped_column(String(45), primary_key=True)
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    request_key_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    canonical_document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class ChatModelSettingsRecord(Base):
    __tablename__ = "general_chat_model_settings"
    __table_args__ = (
        CheckConstraint("settings_id = 'general-chat'", name="ck_chat_model_singleton"),
        CheckConstraint(
            "resource_version >= 1 AND ((resource_version = 1 AND current_revision_id IS NULL) "
            "OR (resource_version > 1 AND current_revision_id IS NOT NULL))",
            name="ck_chat_model_current",
        ),
    )
    settings_id: Mapped[str] = mapped_column(String(12), primary_key=True)
    current_revision_id: Mapped[str | None] = mapped_column(
        String(45),
        ForeignKey("general_chat_model_setting_revisions.revision_id", ondelete="RESTRICT"),
    )
    resource_version: Mapped[int] = mapped_column(Integer, nullable=False)
