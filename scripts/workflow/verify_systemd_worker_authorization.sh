#!/usr/bin/env bash
set -euo pipefail

REPOSITORY_ROOT="/home/eom/EOM"
UNIT_ROOT="/etc/systemd/system"
HELPER_SOURCE="${REPOSITORY_ROOT}/services/orchestrator/eom_orchestrator/worker_exec.py"
HELPER_INSTALLED="/usr/local/libexec/eom-worker-exec"

fail() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

[[ "$(id -un)" == "eom" ]] || fail "authorization verification must run as eom"
[[ "$(git -C "${REPOSITORY_ROOT}" rev-parse --show-toplevel)" == "${REPOSITORY_ROOT}" ]] || \
  fail "repository root mismatch"
[[ -x "${HELPER_INSTALLED}" ]] || fail "root-installed worker executable is unavailable"
[[ "$(stat -c '%U:%G:%a' "${HELPER_INSTALLED}")" == "root:root:755" ]] || \
  fail "worker executable ownership or mode is invalid"
cmp --silent "${HELPER_SOURCE}" "${HELPER_INSTALLED}" || fail "worker executable source drift"

for slot in 01 02 03 04 05; do
  worker_source="${REPOSITORY_ROOT}/infra/systemd/eom-worker-${slot}@.service"
  worker_installed="${UNIT_ROOT}/eom-worker-${slot}@.service"
  probe_source="${REPOSITORY_ROOT}/infra/systemd/eom-worker-probe-${slot}@.service"
  probe_installed="${UNIT_ROOT}/eom-worker-probe-${slot}@.service"
  cmp --silent "${worker_source}" "${worker_installed}" || \
    fail "worker template ${slot} source drift"
  cmp --silent "${probe_source}" "${probe_installed}" || \
    fail "worker probe ${slot} source drift"
  [[ "$(stat -c '%U:%G:%a' "${worker_installed}")" == "root:root:644" ]] || \
    fail "worker template ${slot} ownership or mode is invalid"
  [[ "$(stat -c '%U:%G:%a' "${probe_installed}")" == "root:root:644" ]] || \
    fail "worker probe ${slot} ownership or mode is invalid"

  probe_id="probe_$(tr -d '-' </proc/sys/kernel/random/uuid)"
  probe_unit="eom-worker-probe-${slot}@${probe_id}.service"
  /usr/bin/systemctl --no-ask-password --wait start "${probe_unit}" || \
    fail "worker probe ${slot} was not authorized"
  if /usr/bin/systemctl is-active --quiet "${probe_unit}"; then
    fail "worker probe ${slot} left a running process"
  fi
done

negative_probe="eom-worker-probe-01@probe_0123456789abcdef0123456789abcdef.service"
if /usr/bin/systemctl --no-ask-password --wait restart "${negative_probe}"; then
  fail "restart authorization was unexpectedly granted"
fi
if /usr/bin/systemctl --no-ask-password --wait start \
  "eom-worker-probe-01@malformed.service"; then
  fail "malformed worker instance authorization was unexpectedly granted"
fi
if /usr/bin/systemd-run --no-ask-password --wait --collect \
  --uid=root --gid=root /usr/bin/true; then
  fail "arbitrary transient root unit authorization was unexpectedly granted"
fi

printf '%s\n' "fixed worker authorization probes passed; negative grants remained denied"
