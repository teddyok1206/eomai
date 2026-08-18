from __future__ import annotations

from pathlib import Path

import pytest
from eom_api.settings import ApiSecrets, load_settings
from pydantic import ValidationError


def test_default_config_uses_service_specific_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = Path("/etc/eom-api/api.yaml")
    seen: list[Path] = []

    def fake_read_text(path: Path, *, encoding: str) -> str:
        seen.append(path)
        assert encoding == "utf-8"
        return "schema_version: 1\n"

    monkeypatch.delenv("EOM_API_CONFIG", raising=False)
    monkeypatch.setattr(Path, "read_text", fake_read_text)

    load_settings()

    assert seen == [expected]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("database_url", "sqlite:///tmp/eom.db"),
        ("database_url", "postgresql+psycopg://placeholder.invalid/eom"),
        ("token_hash_key", "placeholder_token_hash_key_0123456789"),
        ("fingerprint_key", "placeholder_fingerprint_key_012345"),
    ],
)
def test_runtime_secrets_reject_wrong_format_or_placeholders(field: str, value: str) -> None:
    payload = {
        "database_url": "postgresql+psycopg://runtime:secret@127.0.0.1/eom",
        "token_hash_key": "TEST_ONLY_TOKEN_HASH_KEY_0123456789",
        "fingerprint_key": "TEST_ONLY_FINGERPRINT_KEY_0123456",
    }
    payload[field] = value

    with pytest.raises(ValidationError):
        ApiSecrets.model_validate(payload)
