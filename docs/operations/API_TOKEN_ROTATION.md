# API Token Rotation

Rotate `EOM_API_TOKEN_HASH_KEY` only in a planned session reset. Existing verifier HMAC values cannot
be validated with a new key, so key rotation intentionally invalidates every existing token. Stop
the API, revoke active sessions using the migration-owner operation path, replace the protected
secret, start the service, and verify login/refresh/logout. Never print either key or token.

Client refresh behavior is single-use: replace both locally held tokens atomically after a success.
Do not retry the same refresh token in parallel. Reuse is treated as possible theft and revokes the
whole session family; the client must perform password login again.
