"""Strict Application API configuration and secrets."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


class SettingsError(RuntimeError):
    pass


class StrictSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ServerSettings(StrictSettings):
    host: str = "127.0.0.1"
    port: int = Field(default=8765, ge=1, le=65535)
    workers: int = Field(default=1, ge=1, le=4)
    request_body_limit_bytes: int = Field(default=1_048_576, ge=1024, le=1_048_576)
    docs_enabled: bool = False

    @field_validator("host")
    @classmethod
    def loopback_only(cls, value: str) -> str:
        if value not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("Application API V0 must bind to loopback")
        return value


class SecuritySettings(StrictSettings):
    allowed_hosts: tuple[str, ...] = ("127.0.0.1", "localhost")

    @field_validator("allowed_hosts")
    @classmethod
    def explicit_hosts(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or "*" in value:
            raise ValueError("allowed hosts must be an explicit non-empty allowlist")
        return value


class AuthSettings(StrictSettings):
    access_token_seconds: int = Field(default=1800, ge=60)
    refresh_token_seconds: int = Field(default=2_592_000, ge=300)
    session_absolute_seconds: int = Field(default=2_592_000, ge=300)
    session_idle_seconds: int = Field(default=604_800, ge=60)
    fresh_auth_seconds: int = Field(default=900, ge=60)
    login_failure_limit: int = Field(default=5, ge=1, le=100)
    login_failure_window_seconds: int = Field(default=900, ge=60)
    lock_seconds: int = Field(default=900, ge=60)


class RateLimitSettings(StrictSettings):
    general_per_minute: int = Field(default=300, ge=1)
    expensive_per_minute: int = Field(default=60, ge=1)
    login_global_per_minute: int = Field(default=10, ge=1)
    login_username_per_window: int = Field(default=5, ge=1)
    refresh_per_minute: int = Field(default=10, ge=1)
    maximum_buckets: int = Field(default=10_000, ge=100, le=100_000)


class PaginationSettings(StrictSettings):
    default_limit: int = Field(default=50, ge=1, le=200)
    maximum_limit: int = Field(default=200, ge=1, le=200)


class OpenApiSettings(StrictSettings):
    version: str = Field(default="1", pattern=r"^1$")


class ApiSettings(StrictSettings):
    schema_version: int = Field(default=1, ge=1, le=1)
    server: ServerSettings = ServerSettings()
    security: SecuritySettings = SecuritySettings()
    auth: AuthSettings = AuthSettings()
    rate_limit: RateLimitSettings = RateLimitSettings()
    pagination: PaginationSettings = PaginationSettings()
    openapi: OpenApiSettings = OpenApiSettings()


class ApiSecrets(StrictSettings):
    database_url: SecretStr
    token_hash_key: SecretStr
    fingerprint_key: SecretStr

    @field_validator("token_hash_key", "fingerprint_key")
    @classmethod
    def strong_hmac_key(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value().encode("utf-8")) < 32:
            raise ValueError("HMAC keys must contain at least 32 bytes")
        if "placeholder" in value.get_secret_value().casefold():
            raise ValueError("placeholder HMAC keys are not allowed")
        return value

    @field_validator("database_url")
    @classmethod
    def runtime_database_url(cls, value: SecretStr) -> SecretStr:
        raw = value.get_secret_value()
        if not raw.startswith(("postgresql://", "postgresql+psycopg://")):
            raise ValueError("Application API requires a PostgreSQL database URL")
        if "placeholder" in raw.casefold():
            raise ValueError("placeholder database URLs are not allowed")
        return value


def load_settings(path: Path | None = None) -> ApiSettings:
    actual = path or Path(os.environ.get("EOM_API_CONFIG", "/etc/eom-api/api.yaml"))
    try:
        raw = yaml.safe_load(actual.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise SettingsError("cannot load Application API configuration") from exc
    if not isinstance(raw, dict):
        raise SettingsError("Application API configuration must be a mapping")
    return ApiSettings.model_validate(raw)


def load_secrets() -> ApiSecrets:
    required = {
        "database_url": os.environ.get("EOM_API_DATABASE_URL"),
        "token_hash_key": os.environ.get("EOM_API_TOKEN_HASH_KEY"),
        "fingerprint_key": os.environ.get("EOM_API_FINGERPRINT_KEY"),
    }
    if any(not value for value in required.values()):
        raise SettingsError("Application API secrets are incomplete")
    return ApiSecrets.model_validate(required)
