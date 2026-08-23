"""Strict EOM Scientific Studio configuration."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

DEFAULT_CONFIG_PATH = Path("/etc/eom/web-gui.yaml")


class SettingsError(RuntimeError):
    """Raised when GUI configuration is unavailable or unsafe."""


class StrictSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ServerSettings(StrictSettings):
    host: str = "127.0.0.1"
    port: int = Field(default=8790, ge=1, le=65535)
    workers: int = Field(default=1, ge=1, le=1)
    allowed_hosts: tuple[str, ...] = ("127.0.0.1", "localhost")

    @field_validator("host")
    @classmethod
    def loopback_only(cls, value: str) -> str:
        if value not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("Web GUI V0 must bind to loopback")
        return value

    @field_validator("port")
    @classmethod
    def preserve_existing_ports(cls, value: int) -> int:
        if value in {8000, 8765, 8780}:
            raise ValueError("Web GUI must not use an existing EOM or legacy port")
        return value

    @field_validator("allowed_hosts")
    @classmethod
    def explicit_hosts(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or "*" in value:
            raise ValueError("allowed hosts must be an explicit allowlist")
        return value


class UpstreamSettings(StrictSettings):
    application_api_url: str = "http://127.0.0.1:8765"
    observability_url: str = "http://127.0.0.1:8780"
    request_timeout_seconds: float = Field(default=5.0, ge=0.25, le=30.0)

    @field_validator("application_api_url", "observability_url")
    @classmethod
    def loopback_http_only(cls, value: str) -> str:
        if not value.startswith(("http://127.0.0.1:", "http://localhost:")):
            raise ValueError("V0 upstreams must use loopback HTTP")
        return value.rstrip("/")


class SessionSettings(StrictSettings):
    cookie_secure: bool = False
    ttl_seconds: int = Field(default=1800, ge=300, le=86400)
    maximum_sessions: int = Field(default=256, ge=1, le=4096)
    maximum_drafts_per_session: int = Field(default=20, ge=1, le=100)


class WebSettings(StrictSettings):
    schema_version: int = Field(default=1, ge=1, le=1)
    server: ServerSettings = ServerSettings()
    upstreams: UpstreamSettings = UpstreamSettings()
    sessions: SessionSettings = SessionSettings()


class WebSecrets(StrictSettings):
    observability_access_token: SecretStr | None = None


def load_settings(path: Path | None = None) -> WebSettings:
    actual = path or Path(os.environ.get("EOM_WEB_GUI_CONFIG", str(DEFAULT_CONFIG_PATH)))
    try:
        raw = yaml.safe_load(actual.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise SettingsError("cannot load Web GUI configuration") from exc
    if not isinstance(raw, dict):
        raise SettingsError("Web GUI configuration must be a mapping")
    return WebSettings.model_validate(raw)


def load_secrets() -> WebSecrets:
    raw = os.environ.get("EOM_WEB_OBSERVE_ACCESS_TOKEN")
    return WebSecrets(observability_access_token=SecretStr(raw) if raw else None)
