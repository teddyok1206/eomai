#!/usr/bin/env bash
set -euo pipefail

WORKERS=(eom-cdx-01 eom-cdx-02 eom-cdx-03 eom-cdx-04 eom-cdx-05)
FAIL=0

check() {
  local status="$1"
  local message="$2"
  printf '%s %s\n' "$status" "$message"
  [[ "$status" != "FAIL" ]] || FAIL=1
}

for worker in "${WORKERS[@]}"; do
  if ! id "$worker" >/dev/null 2>&1; then
    check FAIL "$worker user missing"
    continue
  fi

  home="/srv/eom/worker-homes/$worker"
  ws="/srv/eom/workspaces/$worker"
  mode="$(stat -c '%a' "$home" 2>/dev/null || true)"
  owner="$(stat -c '%U:%G' "$home" 2>/dev/null || true)"
  ws_mode="$(stat -c '%a' "$ws" 2>/dev/null || true)"
  ws_owner="$(stat -c '%U:%G' "$ws" 2>/dev/null || true)"

  [[ "$mode" == "700" && "$owner" == "$worker:$worker" ]] && check PASS "$worker HOME isolated" || check FAIL "$worker HOME mode/owner invalid: $owner $mode"
  [[ "$ws_mode" == "770" && "$ws_owner" == "$worker:$worker" ]] && check PASS "$worker workspace mode valid" || check FAIL "$worker workspace mode/owner invalid: $ws_owner $ws_mode"

  if sudo -n -u "$worker" -H test -w "$ws"; then
    check PASS "$worker can write own workspace"
  else
    check FAIL "$worker cannot write own workspace"
  fi

  for other in "${WORKERS[@]}"; do
    [[ "$other" == "$worker" ]] && continue
    if sudo -n -u "$worker" -H test -r "/srv/eom/worker-homes/$other" 2>/dev/null; then
      check FAIL "$worker can read $other HOME"
    else
      check PASS "$worker cannot read $other HOME"
    fi
    if sudo -n -u "$worker" -H test -w "/srv/eom/workspaces/$other" 2>/dev/null; then
      check FAIL "$worker can write $other workspace"
    else
      check PASS "$worker cannot write $other workspace"
    fi
  done

  if sudo -n -u "$worker" -H test -r /root/.codex 2>/dev/null; then
    check FAIL "$worker can read /root/.codex"
  else
    check PASS "$worker cannot read /root/.codex"
  fi

  if sudo -n -u "$worker" -H sudo -n true >/dev/null 2>&1; then
    check FAIL "$worker has sudo access"
  else
    check PASS "$worker has no sudo access"
  fi

  if sudo -n -u "$worker" -H test -r /var/run/docker.sock 2>/dev/null || sudo -n -u "$worker" -H test -w /var/run/docker.sock 2>/dev/null; then
    check FAIL "$worker can access Docker socket"
  else
    check PASS "$worker cannot access Docker socket"
  fi

  if sudo -n -u "$worker" -H test -w /mnt/nas/eom 2>/dev/null; then
    check FAIL "$worker can write /mnt/nas/eom"
  else
    check PASS "$worker cannot write /mnt/nas/eom"
  fi

  if sudo -n -u "$worker" -H /usr/local/bin/codex --version >/dev/null 2>&1; then
    check PASS "$worker can execute codex"
  else
    check FAIL "$worker cannot execute codex"
  fi

  if sudo -n -u "$worker" -H /usr/local/bin/codex login status >/dev/null 2>&1; then
    check WARN "$worker login status command succeeded"
  else
    check PASS "$worker login status not authenticated or unsupported"
  fi
done

exit "$FAIL"
