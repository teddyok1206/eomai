"""Operational checks for the dedicated observer process and its read-only boundary."""

from __future__ import annotations

import importlib.util
import json
import pwd
import socket
import stat
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

import yaml
from eom_observe_contracts.validation import SCHEMA_FILES, schema_resource

from eom_observe.build_info import get_build_info
from eom_observe.database import build_readonly_engine
from eom_observe.repository import ObserveRepository
from eom_observe.resources import static_resource, worker_slot_resource
from eom_observe.settings import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_SECRET_PATH,
    ObserveSettings,
    load_secrets,
    load_settings,
)

SERVICE_USER = "eom-observe"
UNIT_PATH = Path("/etc/systemd/system/eom-observe.service")
SOURCE_ROOT = Path("/home/eom/EOM")


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str


def _restricted_for_service(path: Path) -> bool:
    try:
        pwd.getpwnam(SERVICE_USER)
    except KeyError:
        return False
    result = subprocess.run(
        ["runuser", "-u", SERVICE_USER, "--", "test", "-r", str(path)],
        capture_output=True,
        check=False,
        timeout=2,
    )
    return result.returncode != 0


def _inaccessible_in_service_namespace(path: Path) -> bool:
    try:
        pid_result = subprocess.run(
            ["systemctl", "show", "eom-observe.service", "--property", "MainPID", "--value"],
            capture_output=True,
            text=True,
            check=False,
            timeout=2,
        )
        pid = int(pid_result.stdout.strip())
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pid = 0
    if pid > 0:
        result = subprocess.run(
            [
                "nsenter",
                "--target",
                str(pid),
                "--mount",
                "--",
                "runuser",
                "-u",
                SERVICE_USER,
                "--",
                "test",
                "-r",
                str(path),
            ],
            capture_output=True,
            check=False,
            timeout=2,
        )
        return result.returncode != 0
    try:
        unit = UNIT_PATH.read_text(encoding="utf-8")
    except OSError:
        return False
    return f"InaccessiblePaths={path}" in unit


def _port_status(host: str, port: int) -> tuple[bool, str]:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.settimeout(0.3)
    try:
        result = probe.connect_ex((host, port))
    finally:
        probe.close()
    return True, "listening" if result == 0 else "available"


def run_doctor(
    config_path: Path = DEFAULT_CONFIG_PATH,
    secret_path: Path = DEFAULT_SECRET_PATH,
) -> dict[str, object]:
    checks: list[Check] = []
    settings: ObserveSettings | None = None
    secrets_config = None
    checks.append(Check("config_exists", config_path.is_file(), str(config_path)))
    try:
        settings = load_settings(config_path)
        checks.append(Check("config_schema", True, "schema_version=1"))
    except Exception:
        checks.append(Check("config_schema", False, "invalid"))
    checks.append(Check("secret_file_exists", secret_path.is_file(), str(secret_path)))
    permission_ok = False
    if secret_path.exists():
        permission_ok = stat.S_IMODE(secret_path.stat().st_mode) in {0o600, 0o640}
    checks.append(Check("secret_file_permission", permission_ok, "0600 or 0640"))
    try:
        secrets_config = load_secrets(secret_path)
        token_hash_ok = secrets_config.access_token_hash.startswith("scrypt$")
        session_ok = len(secrets_config.session_secret) >= 43
    except Exception:
        token_hash_ok = False
        session_ok = False
    checks.append(
        Check("access_token_hash", token_hash_ok, "scrypt" if token_hash_ok else "invalid")
    )
    checks.append(Check("session_secret", session_ok, "configured" if session_ok else "invalid"))
    repository = None
    if settings is not None and secrets_config is not None:
        try:
            engine = build_readonly_engine(
                secrets_config.database_url, settings.snapshot.query_timeout_ms
            )
            repository = ObserveRepository(engine, event_limit=settings.snapshot.recent_event_limit)
            connected = repository.ping()
            readonly = repository.database_is_readonly()
            insert_denied = repository.insert_is_denied()
            required = repository.required_tables()
        except Exception:
            connected = False
            readonly = False
            insert_denied = False
            required = []
        checks.append(
            Check("database_connection", connected, "connected" if connected else "failed")
        )
        checks.append(Check("database_read_only", readonly, "on" if readonly else "off"))
        checks.append(
            Check("forbidden_insert", insert_denied, "denied" if insert_denied else "allowed")
        )
        checks.append(Check("required_table_select", len(required) == 9, f"{len(required)}/9"))
        if repository is not None:
            repository.engine.dispose()
    else:
        checks.extend(
            [
                Check("database_connection", False, "not configured"),
                Check("database_read_only", False, "not configured"),
                Check("forbidden_insert", False, "not configured"),
                Check("required_table_select", False, "0/9"),
            ]
        )
    try:
        workers = yaml.safe_load(worker_slot_resource().read_text(encoding="utf-8"))["slots"]
        worker_ok = len(workers) == 6
    except Exception:
        worker_ok = False
    checks.append(Check("worker_slot_config", worker_ok, "6 slots" if worker_ok else "invalid"))
    if settings is not None:
        _, port_detail = _port_status(settings.server.host, settings.server.port)
        checks.append(Check("port_8780", True, port_detail))
        checks.append(Check("reserved_port_8000", settings.server.port != 8000, "not configured"))
        checks.append(Check("reserved_port_8765", settings.server.port != 8765, "not configured"))
    else:
        checks.extend(
            [
                Check("port_8780", False, "unknown"),
                Check("reserved_port_8000", False, "unknown"),
                Check("reserved_port_8765", False, "unknown"),
            ]
        )
    assets = (
        "index.html",
        "login.html",
        "app.js",
        "graph.js",
        "api.js",
        "state.js",
        "styles.css",
        "icons.svg",
    )
    checks.append(
        Check(
            "static_assets",
            all(static_resource(name).is_file() for name in assets),
            f"{len(assets)} required",
        )
    )
    schema_ok = True
    try:
        for filename in SCHEMA_FILES.values():
            schema = json.loads(schema_resource(filename).read_text(encoding="utf-8"))
            schema_ok = schema_ok and schema.get("$schema", "").endswith("2020-12/schema")
    except Exception:
        schema_ok = False
    checks.append(Check("api_schemas", schema_ok, f"{len(SCHEMA_FILES)} schemas"))
    try:
        service_account = pwd.getpwnam(SERVICE_USER)
        user_ok = service_account.pw_shell.endswith("nologin")
    except KeyError:
        user_ok = False
    checks.append(Check("service_user", user_ok, SERVICE_USER if user_ok else "missing"))
    checks.append(Check("systemd_unit", UNIT_PATH.is_file(), str(UNIT_PATH)))
    build_info = get_build_info()
    checks.append(
        Check(
            "release_build_info",
            build_info.is_release,
            f"package={build_info.package_version}",
        )
    )
    module = importlib.util.find_spec("eom_observe")
    module_origin = Path(module.origin).resolve() if module is not None and module.origin else None
    installed = module_origin is not None and "site-packages" in module_origin.parts
    checks.append(
        Check("non_editable_install", installed, "site-packages" if installed else "source")
    )
    checks.append(
        Check(
            "source_checkout_inaccessible",
            _inaccessible_in_service_namespace(SOURCE_ROOT),
            "denied",
        )
    )
    for name, path in (
        ("nas_inaccessible", Path("/mnt/nas")),
        ("docker_socket_inaccessible", Path("/var/run/docker.sock")),
    ):
        checks.append(Check(name, _inaccessible_in_service_namespace(path), "denied"))
    for name, path in (
        ("worker_home_inaccessible", Path("/srv/eom/worker-homes")),
        ("codex_auth_inaccessible", Path("/root/.codex")),
    ):
        checks.append(Check(name, _restricted_for_service(path), "denied"))
    result = {
        "passed": all(check.passed for check in checks),
        "checks": [asdict(check) for check in checks],
    }
    return result
