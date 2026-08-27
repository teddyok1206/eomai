"""Runtime settings loaded without exposing database credentials."""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from urllib.parse import quote_plus

DEFAULT_WORKER_CONFIG = Path("/etc/eom/worker-slots.yaml")
DEFAULT_CODEX_CAPABILITY_POLICY = Path("/etc/eom/codex-capabilities.yaml")


class SettingsError(RuntimeError):
    pass


class WorkerConfigSource(StrEnum):
    OPERATOR_DEFAULT = "operator-default"
    ENVIRONMENT = "environment"
    EXPLICIT = "explicit"


def _read_secret_environment(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise SettingsError(f"cannot read database configuration: {path}") from exc

    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise SettingsError(f"invalid database configuration line {line_number}")
        key, value = line.split("=", 1)
        key = key.strip()
        if not key.replace("_", "").isalnum():
            raise SettingsError(f"invalid database configuration key at line {line_number}")
        values[key] = value.strip().strip('"').strip("'")
    return values


def database_url() -> str:
    explicit = os.environ.get("EOM_DATABASE_URL")
    if explicit:
        return explicit

    secret_path = Path(os.environ.get("EOM_POSTGRES_ENV", "/etc/eom/secrets/postgres.env"))
    values = _read_secret_environment(secret_path)
    required = ("EOM_APP_USER", "EOM_APP_PASSWORD", "POSTGRES_DB")
    missing = [key for key in required if not values.get(key)]
    if missing:
        raise SettingsError(f"database configuration is missing: {', '.join(missing)}")
    user = quote_plus(values["EOM_APP_USER"])
    password = quote_plus(values["EOM_APP_PASSWORD"])
    database = quote_plus(values["POSTGRES_DB"])
    return f"postgresql+psycopg://{user}:{password}@127.0.0.1:5432/{database}"


@dataclass(frozen=True)
class Settings:
    worker_config: Path = DEFAULT_WORKER_CONFIG
    staging_root: Path = Path("/srv/eom/staging")
    workspace_root: Path = Path("/srv/eom/workspaces")
    worker_home_root: Path = Path("/srv/eom/worker-homes")
    nas_artifact_root: Path = Path("/mnt/nas/eom/artifacts")
    codex_binary: Path = Path("/usr/local/bin/codex")
    codex_capability_policy: Path = DEFAULT_CODEX_CAPABILITY_POLICY
    worker_timeout_seconds: int = 1800
    worker_config_source: WorkerConfigSource = WorkerConfigSource.OPERATOR_DEFAULT

    @classmethod
    def from_environment(cls) -> Settings:
        configured_worker_path = os.environ.get("EOM_WORKER_CONFIG")
        worker_config = (
            Path(configured_worker_path) if configured_worker_path else DEFAULT_WORKER_CONFIG
        )
        if not worker_config.is_absolute():
            raise SettingsError("EOM_WORKER_CONFIG must be an absolute path")
        capability_policy = Path(
            os.environ.get("EOM_CODEX_CAPABILITY_POLICY", str(DEFAULT_CODEX_CAPABILITY_POLICY))
        )
        if not capability_policy.is_absolute():
            raise SettingsError("EOM_CODEX_CAPABILITY_POLICY must be an absolute path")
        return cls(
            worker_config=worker_config,
            staging_root=Path(os.environ.get("EOM_STAGING_ROOT", "/srv/eom/staging")),
            workspace_root=Path(os.environ.get("EOM_WORKSPACE_ROOT", "/srv/eom/workspaces")),
            worker_home_root=Path(os.environ.get("EOM_WORKER_HOME_ROOT", "/srv/eom/worker-homes")),
            nas_artifact_root=Path(
                os.environ.get("EOM_NAS_ARTIFACT_ROOT", "/mnt/nas/eom/artifacts")
            ),
            codex_binary=Path(os.environ.get("EOM_CODEX_BINARY", "/usr/local/bin/codex")),
            codex_capability_policy=capability_policy,
            worker_timeout_seconds=int(os.environ.get("EOM_WORKER_TIMEOUT_SECONDS", "1800")),
            worker_config_source=(
                WorkerConfigSource.ENVIRONMENT
                if configured_worker_path
                else WorkerConfigSource.OPERATOR_DEFAULT
            ),
        )
