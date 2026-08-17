from __future__ import annotations

from eom_api.lifespan import build_services
from eom_api.settings import ApiSecrets, ApiSettings

TEST_TOKEN_KEY = "TEST_ONLY_API_TOKEN_HASH_KEY_0123456789"
TEST_FINGERPRINT_KEY = "TEST_ONLY_FINGERPRINT_KEY_012345678901"


def disconnected_services():  # type: ignore[no-untyped-def]
    return build_services(
        ApiSettings(),
        ApiSecrets(
            database_url="postgresql+psycopg://invalid:invalid@127.0.0.1:1/invalid",
            token_hash_key=TEST_TOKEN_KEY,
            fingerprint_key=TEST_FINGERPRINT_KEY,
        ),
    )
