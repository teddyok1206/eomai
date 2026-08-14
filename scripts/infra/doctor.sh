#!/usr/bin/env bash
set -euo pipefail

FAIL=0

emit() {
  local status="$1"
  local message="$2"
  printf '%s %s\n' "$status" "$message"
  [[ "$status" != "FAIL" ]] || FAIL=1
}

command -v docker >/dev/null 2>&1 && emit PASS "docker executable present" || emit FAIL "docker missing"
docker compose version >/dev/null 2>&1 && emit PASS "docker compose present" || emit FAIL "docker compose missing"
systemctl is-active docker >/dev/null 2>&1 && emit PASS "docker daemon active" || emit FAIL "docker daemon not active"

if docker compose --env-file /etc/eom/secrets/postgres.env -f /home/eom/EOM/infra/compose/compose.yml ps eom-postgres >/dev/null 2>&1; then
  emit PASS "compose project reachable"
else
  emit FAIL "compose project not reachable"
fi

health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' eom-postgres 2>/dev/null || true)"
[[ "$health" == "healthy" ]] && emit PASS "postgres health healthy" || emit FAIL "postgres health=$health"

if ss -lntp | awk '$4 == "127.0.0.1:5432" {found=1} END {exit found ? 0 : 1}'; then
  emit PASS "postgres bound to 127.0.0.1:5432"
else
  emit FAIL "postgres loopback bind missing"
fi

if ss -lntp | awk '$4 ~ /0\\.0\\.0\\.0:5432|\\[::\\]:5432/ {bad=1} END {exit bad ? 0 : 1}'; then
  emit FAIL "postgres exposed on wildcard address"
else
  emit PASS "postgres not exposed on wildcard address"
fi

avail_kb="$(df -Pk /srv/eom | awk 'NR==2 {print $4}')"
(( avail_kb > 50 * 1024 * 1024 )) && emit PASS "/srv/eom free space above 50 GiB" || emit WARN "/srv/eom free space below 50 GiB"

[[ "$(stat -c '%U:%G:%a' /srv/eom)" == "root:eom:711" ]] && emit PASS "/srv/eom permission valid" || emit FAIL "/srv/eom permission invalid"
[[ "$(stat -c '%U:%G:%a' /etc/eom/secrets)" == "root:eom:750" ]] && emit PASS "/etc/eom/secrets permission valid" || emit FAIL "/etc/eom/secrets permission invalid"

findmnt -T /mnt/nas >/dev/null 2>&1 && emit PASS "NAS mounted" || emit FAIL "NAS not mounted"
[[ -d /mnt/nas/eom/artifacts ]] && emit PASS "NAS artifact root exists" || emit FAIL "NAS artifact root missing"

command -v /usr/local/bin/codex >/dev/null 2>&1 && emit PASS "codex executable present" || emit FAIL "codex missing"

for worker in eom-cdx-01 eom-cdx-02 eom-cdx-03 eom-cdx-04 eom-cdx-05; do
  id "$worker" >/dev/null 2>&1 && emit PASS "$worker exists" || emit FAIL "$worker missing"
  [[ -d "/srv/eom/worker-homes/$worker" ]] && emit PASS "$worker HOME exists" || emit FAIL "$worker HOME missing"
  [[ -d "/srv/eom/workspaces/$worker" ]] && emit PASS "$worker workspace exists" || emit FAIL "$worker workspace missing"
  if sudo -n -u "$worker" -H sudo -n true >/dev/null 2>&1; then emit FAIL "$worker sudo access"; else emit PASS "$worker no sudo"; fi
  if sudo -n -u "$worker" -H test -r /var/run/docker.sock 2>/dev/null || sudo -n -u "$worker" -H test -w /var/run/docker.sock 2>/dev/null; then emit FAIL "$worker Docker socket access"; else emit PASS "$worker no Docker socket access"; fi
  if sudo -n -u "$worker" -H test -w /mnt/nas/eom 2>/dev/null; then emit FAIL "$worker NAS write"; else emit PASS "$worker no NAS write"; fi
done

git -C /home/eom/EOM rev-parse --show-toplevel >/dev/null 2>&1 && emit PASS "new EOM Git repository present" || emit FAIL "new EOM Git repository missing"
ss -lntp | awk '$4 ~ /:8000$/ {found=1} END {exit found ? 0 : 1}' && emit PASS "existing 8000 service still listening" || emit WARN "existing 8000 service not listening"
ss -lntp | awk '$4 ~ /:8765$/ {found=1} END {exit found ? 0 : 1}' && emit WARN "8765 already in use" || emit PASS "8765 currently unused"

exit "$FAIL"
