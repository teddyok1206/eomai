"""Validated configuration and secret loading without value disclosure."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from eom_observe.errors import ObserveError, ObserveErrorCode

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG_PATH = Path("/etc/eom/observe.yaml")
DEFAULT_SECRET_PATH = Path("/etc/eom/secrets/observe.env")


class StrictSettingsModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ServerSettings(StrictSettingsModel):
    host: str = "127.0.0.1"
    port: int = Field(default=8780, ge=1, le=65535)
    root_path: str = "/observe"
    poll_interval_ms: int = Field(default=1000, ge=250, le=60000)
    heartbeat_seconds: int = Field(default=15, ge=5, le=120)
    max_stream_clients: int = Field(default=5, ge=1, le=50)

    @field_validator("host")
    @classmethod
    def loopback_only(cls, value: str) -> str:
        if value != "127.0.0.1":
            raise ValueError("observability server must bind to 127.0.0.1")
        return value

    @field_validator("port")
    @classmethod
    def reserved_port(cls, value: int) -> int:
        if value != 8780:
            raise ValueError("observability server port must be 8780")
        return value

    @field_validator("root_path")
    @classmethod
    def observe_namespace(cls, value: str) -> str:
        if value != "/observe":
            raise ValueError("observability root path must be /observe")
        return value


class SnapshotSettings(StrictSettingsModel):
    recent_event_limit: int = Field(default=200, ge=10, le=500)
    query_timeout_ms: int = Field(default=1500, ge=100, le=10000)
    stale_after_seconds: int = Field(default=5, ge=2, le=300)


class PrivacySettings(StrictSettingsModel):
    content_preview_mode: str = "metadata"
    max_preview_bytes: int = Field(default=65536, ge=1024, le=1048576)
    max_text_length: int = Field(default=500, ge=64, le=2000)
    expose_filesystem_paths: bool = False

    @field_validator("content_preview_mode")
    @classmethod
    def metadata_only(cls, value: str) -> str:
        if value != "metadata":
            raise ValueError("V0 permits only metadata content previews")
        return value


class AuthSettings(StrictSettingsModel):
    session_ttl_seconds: int = Field(default=28800, ge=300, le=86400)
    secure_cookie: bool = False


class UiSettings(StrictSettingsModel):
    default_timeline_limit: int = Field(default=100, ge=10, le=500)
    edge_activity_seconds: int = Field(default=4, ge=1, le=30)


class ObserveSettings(StrictSettingsModel):
    schema_version: int = 1
    server: ServerSettings
    snapshot: SnapshotSettings
    privacy: PrivacySettings
    auth: AuthSettings
    ui: UiSettings


class ObserveSecrets(StrictSettingsModel):
    database_url: str = Field(min_length=16)
    access_token_hash: str = Field(min_length=32)
    session_secret: str = Field(min_length=43)


def parse_environment_file(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ObserveError(
            ObserveErrorCode.OBSERVE_SECRET_MISSING, "secret file unavailable"
        ) from exc
    values: dict[str, str] = {}
    for line_number, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ObserveError(
                ObserveErrorCode.OBSERVE_CONFIG_INVALID,
                f"invalid secret file syntax at line {line_number}",
            )
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def load_settings(path: Path | None = None) -> ObserveSettings:
    config_path = path or Path(os.environ.get("EOM_OBSERVE_CONFIG", DEFAULT_CONFIG_PATH))
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        return ObserveSettings.model_validate(raw)
    except Exception as exc:
        raise ObserveError(
            ObserveErrorCode.OBSERVE_CONFIG_INVALID, "observability configuration is invalid"
        ) from exc


def load_secrets(path: Path | None = None) -> ObserveSecrets:
    secret_path = path or Path(os.environ.get("EOM_OBSERVE_SECRET_FILE", DEFAULT_SECRET_PATH))
    values = parse_environment_file(secret_path)
    mapped = {
        "database_url": values.get("EOM_OBSERVE_DATABASE_URL"),
        "access_token_hash": values.get("EOM_OBSERVE_ACCESS_TOKEN_HASH"),
        "session_secret": values.get("EOM_OBSERVE_SESSION_SECRET"),
    }
    try:
        return ObserveSecrets.model_validate(mapped)
    except Exception as exc:
        raise ObserveError(
            ObserveErrorCode.OBSERVE_SECRET_MISSING, "required observability secrets are missing"
        ) from exc
