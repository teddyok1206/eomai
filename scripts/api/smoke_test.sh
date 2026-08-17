#!/usr/bin/env bash
set -euo pipefail

PYTHON="${EOM_API_PYTHON:-/srv/eom/conda/envs/eom-api/bin/python}"
BASE_URL="${EOM_API_BASE_URL:-http://127.0.0.1:8765}"
HEALTH_ONLY=false

if (($# > 1)); then
  printf 'usage: %s [--health-only]\n' "$0" >&2
  exit 2
fi
if (($# == 1)); then
  [[ "$1" == "--health-only" ]] || {
    printf 'usage: %s [--health-only]\n' "$0" >&2
    exit 2
  }
  HEALTH_ONLY=true
fi

[[ "${BASE_URL}" == "http://127.0.0.1:8765" ]] || {
  printf 'Application API V0 smoke tests only accept the loopback endpoint.\n' >&2
  exit 1
}
[[ -x "${PYTHON}" ]] || {
  printf 'The isolated eom-api Python is unavailable.\n' >&2
  exit 1
}

EOM_API_HEALTH_ONLY="${HEALTH_ONLY}" "${PYTHON}" - <<'PY'
from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import httpx

base_url = "http://127.0.0.1:8765"


def quiet_transport_error(
    exception_type: type[BaseException],
    exception: BaseException,
    traceback: object,
) -> None:
    if issubclass(exception_type, httpx.HTTPError):
        print("Application API smoke transport failed.", file=sys.stderr)
        return
    sys.__excepthook__(exception_type, exception, traceback)  # type: ignore[arg-type]


sys.excepthook = quiet_transport_error


def require(response: httpx.Response, status: int, label: str) -> dict[str, object]:
    if response.status_code != status:
        raise SystemExit(f"{label} failed with HTTP {response.status_code}")
    value = response.json()
    if not isinstance(value, dict):
        raise SystemExit(f"{label} returned a non-object response")
    if response.headers.get("X-EOM-API-Version") != "1":
        raise SystemExit(f"{label} omitted the API version header")
    if "X-Request-ID" not in response.headers:
        raise SystemExit(f"{label} omitted the request ID header")
    return value


with httpx.Client(base_url=base_url, timeout=5) as client:
    live = require(client.get("/api/v1/health/live"), 200, "live")
    ready = require(client.get("/api/v1/health/ready"), 200, "ready")
    if live.get("data", {}).get("status") != "LIVE":  # type: ignore[union-attr]
        raise SystemExit("liveness state is not LIVE")
    if ready.get("data", {}).get("status") != "READY":  # type: ignore[union-attr]
        raise SystemExit("readiness state is not READY")

    if os.environ["EOM_API_HEALTH_ONLY"] == "true":
        print("Application API health smoke test passed.")
        raise SystemExit(0)

    username = os.environ.get("EOM_API_SMOKE_USERNAME")
    password_name = os.environ.get("EOM_API_SMOKE_PASSWORD_FILE")
    if not username or not password_name:
        raise SystemExit(
            "set EOM_API_SMOKE_USERNAME and EOM_API_SMOKE_PASSWORD_FILE for authenticated smoke"
        )
    password_file = Path(password_name)
    mode = stat.S_IMODE(password_file.stat().st_mode)
    if not password_file.is_file() or mode & 0o077:
        raise SystemExit("smoke password file must be a regular file with mode 0600 or stricter")
    password = password_file.read_text(encoding="utf-8").rstrip("\n")
    login = require(
        client.post(
            "/api/v1/auth/login",
            json={
                "username": username,
                "password": password,
                "client_name": "eom-api-smoke",
            },
        ),
        200,
        "login",
    )
    login_data = login.get("data")
    if not isinstance(login_data, dict):
        raise SystemExit("login data is invalid")
    access = login_data.get("access_token")
    refresh = login_data.get("refresh_token")
    if not isinstance(access, str) or not isinstance(refresh, str):
        raise SystemExit("login token pair is invalid")

    headers = {"Authorization": f"Bearer {access}"}
    require(client.get("/api/v1/auth/me", headers=headers), 200, "authenticated query")
    rotated = require(
        client.post("/api/v1/auth/refresh", json={"refresh_token": refresh}),
        200,
        "refresh",
    )
    rotated_data = rotated.get("data")
    if not isinstance(rotated_data, dict):
        raise SystemExit("refresh data is invalid")
    rotated_access = rotated_data.get("access_token")
    if not isinstance(rotated_access, str):
        raise SystemExit("rotated access token is invalid")
    rotated_headers = {"Authorization": f"Bearer {rotated_access}"}
    require(client.post("/api/v1/auth/logout", headers=rotated_headers), 200, "logout")
    revoked = client.get("/api/v1/auth/me", headers=rotated_headers)
    if revoked.status_code != 401:
        raise SystemExit("logout did not revoke the session")

print("Application API smoke test passed.")
PY
