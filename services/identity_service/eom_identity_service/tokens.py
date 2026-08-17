"""Opaque token encoding and DB-backed session operations."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from eom_operator_identity.contracts import OperatorProjection, PermissionKey
from eom_operator_identity.errors import IdentityError, IdentityErrorCode
from eom_operator_identity.identifiers import (
    new_api_session_id,
    new_api_token_id,
    new_token_family_id,
)
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from eom_identity_service.models import ApiSessionRecord, ApiTokenRecord, OperatorRecord
from eom_identity_service.repository import effective_permissions, operator_projection

TOKEN_PATTERN = re.compile(
    r"^(?P<prefix>eom_(?:at|rt)_)(?P<selector>[A-Za-z0-9_-]{22})\."
    r"(?P<verifier>[A-Za-z0-9_-]{43})$"
)


class TokenType(StrEnum):
    ACCESS = "ACCESS"
    REFRESH = "REFRESH"


@dataclass(frozen=True)
class TokenPolicy:
    access_seconds: int = 1800
    refresh_seconds: int = 2_592_000
    session_absolute_seconds: int = 2_592_000
    session_idle_seconds: int = 604_800


@dataclass(frozen=True)
class EncodedToken:
    raw: str
    selector: str
    verifier_hash: str
    token_type: TokenType


@dataclass(frozen=True)
class IssuedTokenPair:
    access_token: str
    refresh_token: str
    access_expires_at: datetime
    refresh_expires_at: datetime
    session_id: str
    password_change_required: bool


@dataclass(frozen=True)
class AccessAuthentication:
    operator: OperatorProjection
    session_id: str
    authenticated_at: datetime
    access_expires_at: datetime
    permissions: frozenset[PermissionKey]
    password_change_required: bool


@dataclass(frozen=True)
class RefreshOutcome:
    pair: IssuedTokenPair | None
    error: IdentityErrorCode | None
    reused: bool = False


class TokenCodec:
    def __init__(self, hash_key: str | bytes) -> None:
        key = hash_key.encode("utf-8") if isinstance(hash_key, str) else hash_key
        if len(key) < 32:
            raise ValueError("token hash key must contain at least 32 bytes")
        self._key = key

    def issue(self, token_type: TokenType) -> EncodedToken:
        selector = self._urlsafe(secrets.token_bytes(16))
        verifier = self._urlsafe(secrets.token_bytes(32))
        prefix = "eom_at_" if token_type is TokenType.ACCESS else "eom_rt_"
        return EncodedToken(
            raw=f"{prefix}{selector}.{verifier}",
            selector=selector,
            verifier_hash=self.hash_verifier(verifier),
            token_type=token_type,
        )

    def parse(self, raw: str, expected_type: TokenType) -> tuple[str, str] | None:
        match = TOKEN_PATTERN.fullmatch(raw)
        if match is None:
            return None
        expected_prefix = "eom_at_" if expected_type is TokenType.ACCESS else "eom_rt_"
        if match.group("prefix") != expected_prefix:
            return None
        return match.group("selector"), match.group("verifier")

    def hash_verifier(self, verifier: str) -> str:
        digest = hmac.new(self._key, verifier.encode("ascii"), hashlib.sha256).hexdigest()
        return f"sha256:{digest}"

    def matches(self, verifier: str, expected_hash: str) -> bool:
        return hmac.compare_digest(self.hash_verifier(verifier), expected_hash)

    @staticmethod
    def _urlsafe(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


class SessionTokenService:
    def __init__(self, codec: TokenCodec, policy: TokenPolicy | None = None) -> None:
        self.codec = codec
        self.policy = policy or TokenPolicy()

    def create_session(
        self,
        session: Session,
        operator: OperatorRecord,
        *,
        client_name: str,
        password_change_required: bool,
        now: datetime | None = None,
    ) -> IssuedTokenPair:
        timestamp = now or datetime.now(UTC)
        absolute = timestamp + timedelta(seconds=self.policy.session_absolute_seconds)
        api_session = ApiSessionRecord(
            api_session_id=new_api_session_id(),
            operator_id=operator.operator_id,
            token_family_id=new_token_family_id(),
            client_name=client_name,
            authenticated_at=timestamp,
            created_at=timestamp,
            last_seen_at=timestamp,
            absolute_expires_at=absolute,
            idle_expires_at=min(
                timestamp + timedelta(seconds=self.policy.session_idle_seconds), absolute
            ),
            refresh_generation=1,
            lock_version=1,
        )
        session.add(api_session)
        session.flush()
        return self._issue_pair(
            session,
            api_session,
            password_change_required=password_change_required,
            now=timestamp,
        )

    def authenticate_access(
        self, session: Session, raw_token: str, *, now: datetime | None = None
    ) -> AccessAuthentication:
        timestamp = now or datetime.now(UTC)
        parsed = self.codec.parse(raw_token, TokenType.ACCESS)
        if parsed is None:
            raise IdentityError(IdentityErrorCode.AUTH_TOKEN_INVALID, "access token is invalid")
        selector, verifier = parsed
        token = session.scalar(select(ApiTokenRecord).where(ApiTokenRecord.selector == selector))
        if (
            token is None
            or token.token_type != TokenType.ACCESS.value
            or not self.codec.matches(verifier, token.verifier_hash)
        ):
            raise IdentityError(IdentityErrorCode.AUTH_TOKEN_INVALID, "access token is invalid")
        if token.revoked_at is not None:
            raise IdentityError(IdentityErrorCode.AUTH_TOKEN_INVALID, "access token is revoked")
        if token.expires_at <= timestamp:
            raise IdentityError(IdentityErrorCode.AUTH_TOKEN_EXPIRED, "access token is expired")
        api_session = session.scalar(
            select(ApiSessionRecord)
            .where(ApiSessionRecord.api_session_id == token.api_session_id)
            .with_for_update()
        )
        if api_session is None or api_session.revoked_at is not None:
            raise IdentityError(IdentityErrorCode.AUTH_SESSION_REVOKED, "session is revoked")
        if api_session.absolute_expires_at <= timestamp or api_session.idle_expires_at <= timestamp:
            self._revoke(api_session, "SESSION_EXPIRED", "system", timestamp)
            raise IdentityError(IdentityErrorCode.AUTH_SESSION_REVOKED, "session is expired")
        operator = session.get(OperatorRecord, api_session.operator_id)
        if operator is None or operator.status != "ACTIVE":
            self._revoke(api_session, "OPERATOR_DISABLED", "system", timestamp)
            raise IdentityError(IdentityErrorCode.AUTH_SESSION_REVOKED, "session is revoked")
        projection = operator_projection(session, operator)
        api_session.last_seen_at = timestamp
        api_session.idle_expires_at = min(
            timestamp + timedelta(seconds=self.policy.session_idle_seconds),
            api_session.absolute_expires_at,
        )
        token.last_used_at = timestamp
        return AccessAuthentication(
            operator=projection,
            session_id=api_session.api_session_id,
            authenticated_at=api_session.authenticated_at,
            access_expires_at=token.expires_at,
            permissions=effective_permissions(session, operator.operator_id),
            password_change_required=projection.must_change_password,
        )

    def rotate_refresh(
        self, session: Session, raw_token: str, *, now: datetime | None = None
    ) -> RefreshOutcome:
        timestamp = now or datetime.now(UTC)
        parsed = self.codec.parse(raw_token, TokenType.REFRESH)
        if parsed is None:
            return RefreshOutcome(None, IdentityErrorCode.AUTH_REFRESH_TOKEN_INVALID)
        selector, verifier = parsed
        token = session.scalar(
            select(ApiTokenRecord).where(ApiTokenRecord.selector == selector).with_for_update()
        )
        if (
            token is None
            or token.token_type != TokenType.REFRESH.value
            or not self.codec.matches(verifier, token.verifier_hash)
        ):
            return RefreshOutcome(None, IdentityErrorCode.AUTH_REFRESH_TOKEN_INVALID)
        api_session = session.scalar(
            select(ApiSessionRecord)
            .where(ApiSessionRecord.api_session_id == token.api_session_id)
            .with_for_update()
        )
        if api_session is None:
            return RefreshOutcome(None, IdentityErrorCode.AUTH_REFRESH_TOKEN_INVALID)
        if token.consumed_at is not None:
            self._revoke(api_session, "REFRESH_TOKEN_REUSED", "system", timestamp)
            return RefreshOutcome(None, IdentityErrorCode.AUTH_REFRESH_TOKEN_REUSED, reused=True)
        if token.revoked_at is not None or api_session.revoked_at is not None:
            return RefreshOutcome(None, IdentityErrorCode.AUTH_SESSION_REVOKED)
        if (
            token.expires_at <= timestamp
            or api_session.absolute_expires_at <= timestamp
            or api_session.idle_expires_at <= timestamp
        ):
            self._revoke(api_session, "SESSION_EXPIRED", "system", timestamp)
            return RefreshOutcome(None, IdentityErrorCode.AUTH_REFRESH_TOKEN_INVALID)
        operator = session.get(OperatorRecord, api_session.operator_id)
        if operator is None or operator.status != "ACTIVE":
            self._revoke(api_session, "OPERATOR_DISABLED", "system", timestamp)
            return RefreshOutcome(None, IdentityErrorCode.AUTH_SESSION_REVOKED)
        token.consumed_at = timestamp
        token.last_used_at = timestamp
        session.execute(
            update(ApiTokenRecord)
            .where(
                ApiTokenRecord.api_session_id == api_session.api_session_id,
                ApiTokenRecord.token_type == TokenType.ACCESS.value,
                ApiTokenRecord.revoked_at.is_(None),
            )
            .values(revoked_at=timestamp)
        )
        api_session.refresh_generation += 1
        api_session.lock_version += 1
        api_session.last_seen_at = timestamp
        api_session.idle_expires_at = min(
            timestamp + timedelta(seconds=self.policy.session_idle_seconds),
            api_session.absolute_expires_at,
        )
        pair = self._issue_pair(
            session,
            api_session,
            password_change_required=operator.must_change_password,
            now=timestamp,
        )
        parsed_replacement = self.codec.parse(pair.refresh_token, TokenType.REFRESH)
        if parsed_replacement is None:
            raise RuntimeError("issued refresh token could not be parsed")
        replacement_selector, _ = parsed_replacement
        replacement = session.scalar(
            select(ApiTokenRecord).where(
                ApiTokenRecord.api_session_id == api_session.api_session_id,
                ApiTokenRecord.selector == replacement_selector,
            )
        )
        if replacement is None:
            raise RuntimeError("replacement refresh token was not persisted")
        token.replaced_by_token_id = replacement.api_token_id
        return RefreshOutcome(pair, None)

    def rotate_current_session(
        self,
        session: Session,
        api_session_id: str,
        *,
        password_change_required: bool,
        now: datetime | None = None,
    ) -> IssuedTokenPair:
        timestamp = now or datetime.now(UTC)
        api_session = session.scalar(
            select(ApiSessionRecord)
            .where(ApiSessionRecord.api_session_id == api_session_id)
            .with_for_update()
        )
        if api_session is None or api_session.revoked_at is not None:
            raise IdentityError(IdentityErrorCode.AUTH_SESSION_REVOKED, "session is revoked")
        session.execute(
            update(ApiTokenRecord)
            .where(
                ApiTokenRecord.api_session_id == api_session_id,
                ApiTokenRecord.revoked_at.is_(None),
            )
            .values(revoked_at=timestamp)
        )
        api_session.refresh_generation += 1
        api_session.lock_version += 1
        return self._issue_pair(
            session,
            api_session,
            password_change_required=password_change_required,
            now=timestamp,
        )

    def _issue_pair(
        self,
        session: Session,
        api_session: ApiSessionRecord,
        *,
        password_change_required: bool,
        now: datetime,
    ) -> IssuedTokenPair:
        access = self.codec.issue(TokenType.ACCESS)
        refresh = self.codec.issue(TokenType.REFRESH)
        access_expires = min(
            now + timedelta(seconds=self.policy.access_seconds), api_session.absolute_expires_at
        )
        refresh_expires = min(
            now + timedelta(seconds=self.policy.refresh_seconds), api_session.absolute_expires_at
        )
        session.add_all(
            [
                self._record(api_session.api_session_id, access, now, access_expires),
                self._record(api_session.api_session_id, refresh, now, refresh_expires),
            ]
        )
        session.flush()
        return IssuedTokenPair(
            access_token=access.raw,
            refresh_token=refresh.raw,
            access_expires_at=access_expires,
            refresh_expires_at=refresh_expires,
            session_id=api_session.api_session_id,
            password_change_required=password_change_required,
        )

    @staticmethod
    def _record(
        api_session_id: str, token: EncodedToken, issued_at: datetime, expires_at: datetime
    ) -> ApiTokenRecord:
        return ApiTokenRecord(
            api_token_id=new_api_token_id(),
            api_session_id=api_session_id,
            token_type=token.token_type.value,
            selector=token.selector,
            verifier_hash=token.verifier_hash,
            issued_at=issued_at,
            expires_at=expires_at,
            created_at=issued_at,
        )

    @staticmethod
    def _revoke(api_session: ApiSessionRecord, reason: str, actor_id: str, now: datetime) -> None:
        if api_session.revoked_at is None:
            api_session.revoked_at = now
            api_session.revoked_by = actor_id
            api_session.revoke_reason = reason
            api_session.lock_version += 1
