#!/usr/bin/env bash
set -euo pipefail

SERVICE="eom-api.service"
PYTHON="/srv/eom/conda/envs/eom-api/bin/python"

if [[ "$(id -u)" -ne 0 ]]; then
  printf 'Run verify_runtime_isolation.sh as root.\n' >&2
  exit 1
fi

systemctl is-active --quiet "${SERVICE}"
systemctl is-enabled --quiet "${SERVICE}"

main_pid="$(systemctl show --property=MainPID --value "${SERVICE}")"
[[ "${main_pid}" =~ ^[1-9][0-9]*$ ]] || {
  printf 'The Application API service has no live main process.\n' >&2
  exit 1
}

mapfile -t listeners < <(ss -H -lnt 'sport = :8765')
[[ "${#listeners[@]}" -eq 1 ]] || {
  printf 'Expected exactly one listener on port 8765.\n' >&2
  exit 1
}
[[ "${listeners[0]}" == *"127.0.0.1:8765"* ]] || {
  printf 'Port 8765 is not bound exclusively to IPv4 loopback.\n' >&2
  exit 1
}

unit_paths="$(systemctl show --property=InaccessiblePaths --value "${SERVICE}")"
for path in \
  /home/eom/EOM \
  /home/eom/EOMIS \
  /root/.codex \
  /srv/eom/worker-homes \
  /mnt/nas \
  /var/run/docker.sock \
  /etc/eom/secrets/postgres.env \
  /etc/eom/secrets/dev-slack.env \
  /etc/eom/secrets/observe.env; do
  [[ " ${unit_paths} " == *" ${path} "* ]] || {
    printf 'Unit sandbox omits required inaccessible path: %s\n' "${path}" >&2
    exit 1
  }
  nsenter --target "${main_pid}" --mount -- test ! -r "${path}" || {
    printf 'Service mount namespace can read a forbidden path: %s\n' "${path}" >&2
    exit 1
  }
done

runuser -u eom-api -- env -u PYTHONPATH "${PYTHON}" - <<'PY'
import importlib.util
import site
from pathlib import Path

roots = [Path(value).resolve() for value in site.getsitepackages()]
for module in ("eom_api", "eom_api_contracts", "eom_operator_identity"):
    spec = importlib.util.find_spec(module)
    if spec is None or spec.origin is None:
        raise SystemExit(f"missing installed module: {module}")
    origin = Path(spec.origin).resolve()
    if not any(origin.is_relative_to(root) for root in roots):
        raise SystemExit(f"non-installed import: {module}")
    if str(origin).startswith("/home/eom/EOM"):
        raise SystemExit(f"source checkout import: {module}")
PY

printf 'Application API runtime isolation verified.\n'
