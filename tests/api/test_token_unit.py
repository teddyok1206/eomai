from __future__ import annotations

import re

from eom_identity_service.tokens import TokenCodec, TokenType

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
