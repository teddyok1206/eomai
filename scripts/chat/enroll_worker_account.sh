#!/usr/bin/env bash
set -euo pipefail
umask 077

# Interactive, operator-owned ChatGPT enrollment. Never borrow another auth cache.
REPOSITORY=/home/eom/EOM
WORKER=eom-cdx-chat
WORKER_HOME=/srv/eom/worker-homes/eom-cdx-chat
CODEX=/usr/local/bin/codex

fail() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

[[ ${EUID} -eq 0 ]] || fail "dedicated chat enrollment requires root"
[[ $# -eq 1 && $1 =~ ^[0-9a-f]{40}$ ]] || \
  fail "usage: enroll_worker_account.sh COMMIT"
[[ "$(git --no-optional-locks -C "${REPOSITORY}" rev-parse HEAD)" == "$1" ]] || \
  fail "source commit mismatch"
[[ -z "$(git --no-optional-locks -C "${REPOSITORY}" status --porcelain=v1)" ]] || \
  fail "working tree is not clean"
[[ -t 0 && -t 1 ]] || fail "enrollment requires the operator's terminal"

[[ "$(getent passwd "${WORKER}" | cut -d: -f6-7)" == \
    "${WORKER_HOME}:/usr/sbin/nologin" ]] || fail "chat account metadata mismatch"
[[ "$(id -nG "${WORKER}")" == "${WORKER}" ]] || fail "chat group boundary differs"
[[ "$(id -u "${WORKER}")" -gt 0 && "$(id -u "${WORKER}")" -lt 1000 ]] || \
  fail "chat identity is not a dedicated system account"
for private in "${WORKER_HOME}" "${WORKER_HOME}/.codex"; do
  [[ ! -L ${private} && -d ${private} && \
     "$(stat -c '%U:%G:%a' "${private}")" == "${WORKER}:${WORKER}:700" ]] || \
    fail "chat home ownership differs"
done
CHAT_CONFIG=${WORKER_HOME}/.codex/config.toml
[[ ! -L ${CHAT_CONFIG} && -f ${CHAT_CONFIG} && \
   "$(stat -c '%U:%G:%a' "${CHAT_CONFIG}")" == "root:${WORKER}:640" ]] || \
  fail "chat pinned config metadata differs"
cmp --silent "${REPOSITORY}/infra/chat/codex-config.toml" "${CHAT_CONFIG}" || \
  fail "chat pinned config bytes differ"
[[ ! -e ${WORKER_HOME}/.codex/auth.json && ! -L ${WORKER_HOME}/.codex/auth.json ]] || \
  fail "chat credentials already exist; do not replace an enrolled account"
[[ "$(stat -c '%u:%g' "${CODEX}")" == "0:0" ]] || fail "CLI owner differs"
[[ "$(stat -Lc '%u:%g:%a' "${CODEX}")" == "0:0:755" ]] || fail "CLI target differs"
CHAT_CLI_VERSION=$(/usr/sbin/runuser -u "${WORKER}" -- /usr/bin/env -i \
  HOME="${WORKER_HOME}" CODEX_HOME="${WORKER_HOME}/.codex" \
  PATH=/usr/local/bin:/usr/bin:/bin LANG=C.UTF-8 RUST_LOG=off "${CODEX}" --version)
[[ ${CHAT_CLI_VERSION} == "codex-cli 0.160.0" ]] || fail "CLI profile differs"

printf 'Complete the device sign-in in your browser. Do not share its code or credentials.\n'
# env -i strips operator/root API keys and credential-store variables. runuser
# selects only the worker's private identity; only login runs, never an inference.
exec /usr/bin/timeout --signal=TERM --kill-after=10s 15m \
  /usr/sbin/runuser -u "${WORKER}" -- /usr/bin/env -i \
  HOME="${WORKER_HOME}" CODEX_HOME="${WORKER_HOME}/.codex" \
  PATH=/usr/local/bin:/usr/bin:/bin LANG=C.UTF-8 RUST_LOG=off NO_COLOR=1 \
  "${CODEX}" -c 'forced_login_method="chatgpt"' \
  -c 'cli_auth_credentials_store="file"' -c 'analytics.enabled=false' \
  -c "log_dir=\"${WORKER_HOME}/.codex/login-logs\"" login --device-auth
