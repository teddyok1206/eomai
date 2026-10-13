from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from eom_identity_service.models import (
    ApiTokenRecord,
    OperatorCredentialRecord,
    OperatorEventRecord,
)
from eom_identity_service.tokens import SessionTokenService, TokenCodec, TokenType
from eom_operator_identity.errors import IdentityError, IdentityErrorCode
from sqlalchemy.orm import Session

from tests.unit.test_authenticated_session_fence import SyntheticSession, verified_capture

TOKEN_HASH_KEY = "TEST_ONLY_TOKEN_HASH_KEY_0123456789ABCDEF"


def test_opaque_token_shape_randomness_and_type() -> None:
    codec = TokenCodec(TOKEN_HASH_KEY)
    first = codec.issue(TokenType.ACCESS)
    second = codec.issue(TokenType.ACCESS)
    refresh = codec.issue(TokenType.REFRESH)
    assert first.raw != second.raw
    assert re.fullmatch(r"eom_at_[A-Za-z0-9_-]{22}\.[A-Za-z0-9_-]{43}", first.raw)
    assert re.fullmatch(r"eom_rt_[A-Za-z0-9_-]{22}\.[A-Za-z0-9_-]{43}", refresh.raw)
    assert codec.parse(first.raw, TokenType.ACCESS) is not None
    assert codec.parse(first.raw, TokenType.REFRESH) is None


def test_verifier_hmac_and_constant_time_comparison_contract() -> None:
    codec = TokenCodec(TOKEN_HASH_KEY)
    token = codec.issue(TokenType.ACCESS)
    parsed = codec.parse(token.raw, TokenType.ACCESS)
    assert parsed is not None
    _, verifier = parsed
    assert token.verifier_hash.startswith("sha256:")
    assert verifier not in token.verifier_hash
    assert codec.matches(verifier, token.verifier_hash)
    assert not codec.matches("A" * 43, token.verifier_hash)


def test_malformed_tokens_are_rejected() -> None:
    codec = TokenCodec(TOKEN_HASH_KEY)
    assert codec.parse("not-a-token", TokenType.ACCESS) is None
    assert codec.parse("eom_at_selector.verifier", TokenType.ACCESS) is None


def test_token_key_minimum_length() -> None:
    try:
        TokenCodec("short")
    except ValueError as exc:
        assert "32 bytes" in str(exc)
    else:
        raise AssertionError("short HMAC key was accepted")


class TokenMutationSession(SyntheticSession):
    """Source SQL/row simulation only, not actual transaction or concurrency evidence."""

    def __init__(self) -> None:
        super().__init__()
        self.tokens = [self.token]
        self.events: list[object] = []
        self.credential = OperatorCredentialRecord(
            operator_credential_id="credential_" + "e" * 32,
            operator_id=self.operator.operator_id,
            password_hash="synthetic-old",
            password_algorithm="argon2id",
            password_version=1,
            must_change_password=False,
            password_changed_at=self.api_session.authenticated_at,
        )

    def scalar(self, query: Any) -> Any:
        model = query.column_descriptions[0]["entity"]
        if model is ApiTokenRecord:
            self.order.append("ApiTokenRecord")
            self.queries.append(query)
            parameters = query.compile().params
            return next(
                (
                    row
                    for row in self.tokens
                    if (
                        row.selector == parameters.get("selector_1")
                        or row.api_token_id == parameters.get("api_token_id_1")
                    )
                ),
                None,
            )
        if model is OperatorCredentialRecord:
            self.order.append("OperatorCredentialRecord")
            self.queries.append(query)
            return self.credential
        if model is OperatorEventRecord:
            return 1
        return super().scalar(query)

    def execute(self, query: Any) -> Any:
        self.queries.append(query)
        values = query.compile().params
        self.order.append("UPDATE_" + query.table.name)
        rows = self.tokens if query.table.name == "api_tokens" else [self.api_session]
        for row in rows:
            if (
                values.get("token_type_1") is not None
                and getattr(row, "token_type", None) != values["token_type_1"]
            ):
                continue
            if (
                query.table.name == "api_sessions"
                and values.get("api_session_id_1") == row.api_session_id
            ):
                continue
            row.revoked_at = values["revoked_at"]
        return type("SourceResult", (), {"rowcount": len(rows)})()

    def add_all(self, rows: list[ApiTokenRecord]) -> None:
        self.tokens.extend(rows)

    def add(self, row: object) -> None:
        self.events.append(row)

    def flush(self) -> None:
        pass


def test_legacy_access_keeps_activity_semantics_and_capture_uses_same_hmac_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, _capture = verified_capture(monkeypatch)
    service = SessionTokenService(source.codec)
    now = datetime.now(UTC)
    authentication = service.authenticate_access(cast(Session, source), source.raw_token, now=now)
    assert authentication.operator.operator_id == source.operator.operator_id
    assert source.api_session.last_seen_at == source.token.last_used_at == now
    assert source.api_session.idle_expires_at == min(
        now + timedelta(seconds=service.policy.session_idle_seconds),
        source.api_session.absolute_expires_at,
    )
    matches = source.codec.matches
    observed: list[str] = []

    def actual_matches(verifier: str, expected: str) -> bool:
        observed.append(expected)
        return matches(verifier, expected)

    monkeypatch.setattr(source.codec, "matches", actual_matches)
    assert (
        service.capture_access(cast(Session, source), source.raw_token).operator_id
        == source.operator.operator_id
    )
    assert observed == [source.token.verifier_hash]


@pytest.mark.parametrize(
    "fault,code",
    [
        ("token_revoked", IdentityErrorCode.AUTH_TOKEN_INVALID),
        ("token_expired", IdentityErrorCode.AUTH_TOKEN_EXPIRED),
        ("session_revoked", IdentityErrorCode.AUTH_SESSION_REVOKED),
        ("session_expired", IdentityErrorCode.AUTH_SESSION_REVOKED),
        ("operator_disabled", IdentityErrorCode.AUTH_SESSION_REVOKED),
    ],
)
def test_legacy_access_denials_keep_exact_errors(
    monkeypatch: pytest.MonkeyPatch, fault: str, code: IdentityErrorCode
) -> None:
    source, _capture = verified_capture(monkeypatch)
    now = datetime.now(UTC)
    if fault == "token_revoked":
        source.token.revoked_at = now
    elif fault == "token_expired":
        source.token.expires_at = now
    elif fault == "session_revoked":
        source.api_session.revoked_at = now
    elif fault == "session_expired":
        source.api_session.idle_expires_at = now
    else:
        source.operator.status = "DISABLED"
    with pytest.raises(IdentityError) as failure:
        SessionTokenService(source.codec).authenticate_access(
            cast(Session, source), source.raw_token, now=now
        )
    assert failure.value.code is code


def test_legacy_refresh_locks_distinct_refresh_then_session_before_access_revoke(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = TokenMutationSession()
    verified_capture(monkeypatch, source)
    refresh = source.codec.issue(TokenType.REFRESH)
    refresh_row = ApiTokenRecord(
        api_token_id="apitoken_" + "d" * 32,
        api_session_id=source.api_session.api_session_id,
        token_type="REFRESH",
        selector=refresh.selector,
        verifier_hash=refresh.verifier_hash,
        issued_at=source.token.issued_at,
        expires_at=source.api_session.absolute_expires_at,
        revoked_at=None,
        consumed_at=None,
    )
    source.tokens.append(refresh_row)
    outcome = SessionTokenService(source.codec).rotate_refresh(cast(Session, source), refresh.raw)
    assert outcome.pair is not None and outcome.error is None
    assert source.order[:3] == ["ApiTokenRecord", "ApiSessionRecord", "UPDATE_api_tokens"]
    assert source.queries[0].compile().params == {"selector_1": refresh.selector}
    assert source.queries[0]._for_update_arg is not None
    assert refresh_row.consumed_at is not None and source.token.revoked_at is not None
    assert (
        refresh_row.replaced_by_token_id is not None and source.api_session.refresh_generation == 2
    )
    reused = SessionTokenService(source.codec).rotate_refresh(cast(Session, source), refresh.raw)
    assert reused.error is IdentityErrorCode.AUTH_REFRESH_TOKEN_REUSED and reused.pair is None
