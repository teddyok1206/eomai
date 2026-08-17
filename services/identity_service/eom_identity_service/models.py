"""SQLAlchemy persistence records for Operator identity and API security state."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from eom_orchestrator.models import Base
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class OperatorRecord(Base):
    __tablename__ = "operators"
    __table_args__ = (
        CheckConstraint("status IN ('ACTIVE','DISABLED')", name="ck_operators_status"),
        Index("ix_operators_status", "status"),
        Index("ix_operators_keyset", "created_at", "operator_id"),
    )

    operator_id: Mapped[str] = mapped_column(String(41), primary_key=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    normalized_username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False)
    role_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    disabled_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    disable_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lock_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class OperatorCredentialRecord(Base):
    __tablename__ = "operator_credentials"

    operator_credential_id: Mapped[str] = mapped_column(String(39), primary_key=True)
    operator_id: Mapped[str] = mapped_column(
        ForeignKey("operators.operator_id"), unique=True, nullable=False
    )
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    password_algorithm: Mapped[str] = mapped_column(String(32), nullable=False)
    password_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False)
    password_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    first_failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class RoleRecord(Base):
    __tablename__ = "roles"

    role_id: Mapped[str] = mapped_column(String(37), primary_key=True)
    role_key: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    built_in: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PermissionRecord(Base):
    __tablename__ = "permissions"

    permission_id: Mapped[str] = mapped_column(String(43), primary_key=True)
    permission_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RolePermissionRecord(Base):
    __tablename__ = "role_permissions"

    role_id: Mapped[str] = mapped_column(ForeignKey("roles.role_id"), primary_key=True)
    permission_id: Mapped[str] = mapped_column(
        ForeignKey("permissions.permission_id"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class OperatorRoleAssignmentRecord(Base):
    __tablename__ = "operator_role_assignments"
    __table_args__ = (
        Index(
            "uq_operator_active_role",
            "operator_id",
            "role_id",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
        Index("ix_operator_role_active_lookup", "operator_id", "revoked_at"),
    )

    operator_role_assignment_id: Mapped[str] = mapped_column(String(43), primary_key=True)
    operator_id: Mapped[str] = mapped_column(ForeignKey("operators.operator_id"), nullable=False)
    role_id: Mapped[str] = mapped_column(ForeignKey("roles.role_id"), nullable=False)
    assigned_by: Mapped[str] = mapped_column(String(128), nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoke_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class OperatorEventRecord(Base):
    __tablename__ = "operator_events"
    __table_args__ = (
        UniqueConstraint("operator_id", "sequence", name="uq_operator_event_sequence"),
        Index("ix_operator_events_keyset", "created_at", "operator_event_id"),
    )

    operator_event_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    operator_id: Mapped[str] = mapped_column(ForeignKey("operators.operator_id"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ApiSessionRecord(Base):
    __tablename__ = "api_sessions"
    __table_args__ = (
        UniqueConstraint("token_family_id", name="uq_api_sessions_token_family"),
        Index("ix_api_sessions_operator_revoked", "operator_id", "revoked_at"),
        Index("ix_api_sessions_idle_expires", "idle_expires_at"),
    )

    api_session_id: Mapped[str] = mapped_column(String(43), primary_key=True)
    operator_id: Mapped[str] = mapped_column(ForeignKey("operators.operator_id"), nullable=False)
    token_family_id: Mapped[str] = mapped_column(String(44), nullable=False)
    client_name: Mapped[str] = mapped_column(String(128), nullable=False)
    authenticated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    absolute_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    idle_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    revoke_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    refresh_generation: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    lock_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class ApiTokenRecord(Base):
    __tablename__ = "api_tokens"
    __table_args__ = (
        CheckConstraint("token_type IN ('ACCESS','REFRESH')", name="ck_api_tokens_type"),
        Index("ix_api_tokens_session_type", "api_session_id", "token_type"),
        Index("ix_api_tokens_expires_at", "expires_at"),
    )

    api_token_id: Mapped[str] = mapped_column(String(41), primary_key=True)
    api_session_id: Mapped[str] = mapped_column(
        ForeignKey("api_sessions.api_session_id"), nullable=False
    )
    token_type: Mapped[str] = mapped_column(String(16), nullable=False)
    selector: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    verifier_hash: Mapped[str] = mapped_column(String(71), unique=True, nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    replaced_by_token_id: Mapped[str | None] = mapped_column(
        ForeignKey("api_tokens.api_token_id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ApiIdempotencyRecord(Base):
    __tablename__ = "api_idempotency_records"
    __table_args__ = (
        CheckConstraint(
            "state IN ('PROCESSING','COMPLETED','FAILED_FINAL')",
            name="ck_api_idempotency_state",
        ),
        UniqueConstraint(
            "operator_id",
            "endpoint_key",
            "idempotency_key_hash",
            name="uq_api_idempotency_claim",
        ),
        Index("ix_api_idempotency_expires", "expires_at"),
    )

    api_idempotency_record_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    operator_id: Mapped[str] = mapped_column(ForeignKey("operators.operator_id"), nullable=False)
    endpoint_key: Mapped[str] = mapped_column(String(128), nullable=False)
    idempotency_key_hash: Mapped[str] = mapped_column(String(71), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_body: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    resource_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ApiAuditEventRecord(Base):
    __tablename__ = "api_audit_events"
    __table_args__ = (
        Index("ix_api_audit_created", "created_at", "api_audit_event_id"),
        Index("ix_api_audit_operator_created", "operator_id", "created_at"),
    )

    api_audit_event_id: Mapped[str] = mapped_column(String(41), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    operator_id: Mapped[str | None] = mapped_column(
        ForeignKey("operators.operator_id"), nullable=True
    )
    api_session_id: Mapped[str | None] = mapped_column(
        ForeignKey("api_sessions.api_session_id"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    operation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    http_method: Mapped[str] = mapped_column(String(16), nullable=False)
    route_template: Mapped[str] = mapped_column(String(256), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    http_status: Mapped[int] = mapped_column(Integer, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    client_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_address_hash: Mapped[str | None] = mapped_column(String(71), nullable=True)
    user_agent_hash: Mapped[str | None] = mapped_column(String(71), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
