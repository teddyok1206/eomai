#!/usr/bin/env bash
set -euo pipefail

REPOSITORY=/home/eom/EOM
UNIT_ROOT=/etc/systemd/system
LIBEXEC_ROOT=/usr/local/libexec
POLKIT_ROOT=/etc/polkit-1/rules.d
APPARMOR_SOURCE="${REPOSITORY}/infra/apparmor/eom-codex-bwrap"
APPARMOR_TARGET=/etc/apparmor.d/eom-codex-bwrap
APPARMOR_PARSER=/usr/sbin/apparmor_parser
CODEX_BWRAP=/usr/local/lib/node_modules/@openai/codex/node_modules/@openai/codex-linux-x64/vendor/x86_64-unknown-linux-musl/codex-resources/bwrap
SERVICE=eom-workflow-runner.service
RELEASE_ROOT=/var/lib/eom-worker-runtime-deployments
PYTHON=/srv/eom/conda/envs/eom-api/bin/python
STOPPED=0

fail() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

require_regular() {
  local path="$1" metadata="$2"
  [[ -f "${path}" && ! -L "${path}" && "$(stat -c '%U:%G:%a' "${path}")" == "${metadata}" ]] || \
    fail "runtime artifact metadata mismatch: ${path}"
}

recover() {
  local status=$?
  trap - ERR
  if [[ ${STOPPED} -eq 1 ]]; then
    systemctl start "${SERVICE}" || true
  fi
  exit "${status}"
}
trap recover ERR

[[ ${EUID} -eq 0 ]] || fail "worker runtime deployment requires root"
[[ $# -eq 2 && $1 =~ ^(install|verify)$ && $2 =~ ^[0-9a-f]{40}$ ]] || \
  fail "usage: deploy_worker_runtime.sh <install|verify> COMMIT"
ACTION=$1
EXPECTED_COMMIT=$2
[[ "$(git -C "${REPOSITORY}" rev-parse HEAD)" == "${EXPECTED_COMMIT}" ]] || \
  fail "source commit mismatch"
[[ -z "$(git -C "${REPOSITORY}" status --porcelain=v1)" ]] || \
  fail "working tree is not clean"
[[ "$("${PYTHON}" -I -c 'import json; print(json.load(open("/srv/eom/conda/envs/eom-api/lib/python3.12/site-packages/eom_api/build-info.json"))["source_commit"])')" == "${EXPECTED_COMMIT}" ]] || \
  fail "installed platform release does not match source commit"

if systemctl list-units --no-legend --state=activating,active,deactivating \
  'eom-worker-*@*.service' 'eom-worker-auth-*.service' | grep -q .; then
  fail "a fixed worker unit is active"
fi

SOURCES=(
  "${APPARMOR_SOURCE}"
  "${REPOSITORY}/infra/systemd/eom-workflow-runner.service"
  "${REPOSITORY}/infra/polkit/50-eom-worker-units.rules"
  "${REPOSITORY}/services/orchestrator/eom_orchestrator/worker_exec.py"
  "${REPOSITORY}/services/orchestrator/eom_orchestrator/worker_auth_exec.py"
)
for slot in 01 02 03 04 05; do
  SOURCES+=(
    "${REPOSITORY}/infra/systemd/eom-worker-${slot}@.service"
    "${REPOSITORY}/infra/systemd/eom-worker-probe-${slot}@.service"
    "${REPOSITORY}/infra/systemd/eom-worker-auth-${slot}.service"
  )
done
for source in "${SOURCES[@]}"; do
  [[ -f "${source}" && ! -L "${source}" ]] || fail "unsafe runtime source: ${source}"
done
[[ -x "${APPARMOR_PARSER}" && ! -L "${APPARMOR_PARSER}" ]] || \
  fail "AppArmor parser is unavailable"
"${APPARMOR_PARSER}" -Q -K "${APPARMOR_SOURCE}"
require_regular "${CODEX_BWRAP}" root:root:755

if [[ ${ACTION} == install ]]; then
  systemctl stop "${SERVICE}"
  STOPPED=1
  install -o root -g root -m 0644 \
    "${APPARMOR_SOURCE}" "${APPARMOR_TARGET}"
  "${APPARMOR_PARSER}" -r -K "${APPARMOR_TARGET}"
  install -o root -g root -m 0644 \
    "${REPOSITORY}/infra/systemd/eom-workflow-runner.service" \
    "${UNIT_ROOT}/eom-workflow-runner.service"
  install -o root -g root -m 0755 \
    "${REPOSITORY}/services/orchestrator/eom_orchestrator/worker_exec.py" \
    "${LIBEXEC_ROOT}/eom-worker-exec"
  install -o root -g root -m 0755 \
    "${REPOSITORY}/services/orchestrator/eom_orchestrator/worker_auth_exec.py" \
    "${LIBEXEC_ROOT}/eom-worker-auth-status"
  install -o root -g root -m 0644 \
    "${REPOSITORY}/infra/polkit/50-eom-worker-units.rules" \
    "${POLKIT_ROOT}/50-eom-worker-units.rules"
  for slot in 01 02 03 04 05; do
    install -o root -g root -m 0644 \
      "${REPOSITORY}/infra/systemd/eom-worker-${slot}@.service" \
      "${UNIT_ROOT}/eom-worker-${slot}@.service"
    install -o root -g root -m 0644 \
      "${REPOSITORY}/infra/systemd/eom-worker-probe-${slot}@.service" \
      "${UNIT_ROOT}/eom-worker-probe-${slot}@.service"
    install -o root -g root -m 0644 \
      "${REPOSITORY}/infra/systemd/eom-worker-auth-${slot}.service" \
      "${UNIT_ROOT}/eom-worker-auth-${slot}.service"
  done
  systemctl daemon-reload
  systemctl start "${SERVICE}"
  STOPPED=0
fi

require_regular "${APPARMOR_TARGET}" root:root:644
cmp -s "${APPARMOR_SOURCE}" "${APPARMOR_TARGET}" || fail "Codex Bubblewrap profile drift"
systemd-analyze verify "${UNIT_ROOT}/eom-workflow-runner.service" \
  "${UNIT_ROOT}"/eom-worker-{01,02,03,04,05}@.service \
  "${UNIT_ROOT}"/eom-worker-probe-{01,02,03,04,05}@.service \
  "${UNIT_ROOT}"/eom-worker-auth-{01,02,03,04,05}.service

require_regular "${UNIT_ROOT}/eom-workflow-runner.service" root:root:644
cmp -s "${REPOSITORY}/infra/systemd/eom-workflow-runner.service" \
  "${UNIT_ROOT}/eom-workflow-runner.service" || fail "workflow runner unit source drift"
require_regular "${LIBEXEC_ROOT}/eom-worker-exec" root:root:755
require_regular "${LIBEXEC_ROOT}/eom-worker-auth-status" root:root:755
cmp -s "${REPOSITORY}/services/orchestrator/eom_orchestrator/worker_exec.py" \
  "${LIBEXEC_ROOT}/eom-worker-exec" || fail "worker executable source drift"
cmp -s "${REPOSITORY}/services/orchestrator/eom_orchestrator/worker_auth_exec.py" \
  "${LIBEXEC_ROOT}/eom-worker-auth-status" || fail "worker auth executable source drift"
require_regular "${POLKIT_ROOT}/50-eom-worker-units.rules" root:root:644
cmp -s "${REPOSITORY}/infra/polkit/50-eom-worker-units.rules" \
  "${POLKIT_ROOT}/50-eom-worker-units.rules" || fail "worker polkit source drift"
for slot in 01 02 03 04 05; do
  for name in "eom-worker-${slot}@.service" "eom-worker-probe-${slot}@.service" \
    "eom-worker-auth-${slot}.service"; do
    require_regular "${UNIT_ROOT}/${name}" root:root:644
    cmp -s "${REPOSITORY}/infra/systemd/${name}" "${UNIT_ROOT}/${name}" || \
      fail "worker unit ${name} source drift"
  done
done

BWRAP_SMOKE_UNIT="eom-worker-bwrap-smoke-${EXPECTED_COMMIT:0:12}"
systemd-run --quiet --wait --collect --service-type=oneshot \
  --unit="${BWRAP_SMOKE_UNIT}" \
  --uid=eom-cdx-05 --gid=eom-cdx-05 \
  --property=NoNewPrivileges=yes \
  --property=PrivateTmp=yes \
  --property=PrivateDevices=yes \
  --property=ProtectSystem=strict \
  --property=ProtectHome=read-only \
  --property=ProtectKernelTunables=yes \
  --property=ProtectKernelModules=yes \
  --property=ProtectControlGroups=yes \
  --property=RestrictSUIDSGID=yes \
  --property=LockPersonality=yes \
  --property=RestrictRealtime=yes \
  --property=CapabilityBoundingSet= \
  --property=AmbientCapabilities= \
  --property='RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6 AF_NETLINK' \
  --property=SystemCallArchitectures=native \
  --property=InaccessiblePaths=/mnt/nas \
  --property=InaccessiblePaths=/home/eom/EOM \
  --property=InaccessiblePaths=/home/eom/EOMIS \
  "${CODEX_BWRAP}" --unshare-all --die-with-parent --new-session \
    --ro-bind / / --proc /proc --dev /dev --chdir /tmp /usr/bin/true

systemctl is-active --quiet "${SERVICE}" || fail "workflow runner is not active"
systemctl is-enabled --quiet "${SERVICE}" || fail "workflow runner is not enabled"
RUNNER_ENVIRONMENT=$(systemctl show --property=Environment --value "${SERVICE}")
[[ " ${RUNNER_ENVIRONMENT} " == \
  *" EOM_STAGING_ROOT=/var/lib/eom-workflow-runner/orchestrator-staging "* ]] || \
  fail "workflow runner orchestrator staging environment mismatch"
[[ " ${RUNNER_ENVIRONMENT} " == \
  *" EOM_CATALOG_STAGING_ROOT=/var/lib/eom-workflow-runner/catalog-staging "* ]] || \
  fail "workflow runner Catalog staging environment mismatch"
[[ "$(stat -c '%U:%G:%a' /var/lib/eom-workflow-runner/orchestrator-staging)" == \
  eom-workflow-runner:eom:700 ]] || \
  fail "workflow runner orchestrator staging metadata mismatch"
for path in \
  /var/lib/eom-workflow-runner/catalog-staging \
  /var/lib/eom-workflow-runner/catalog-staging/content-packs \
  /var/lib/eom-workflow-runner/catalog-staging/registry \
  /var/lib/eom-workflow-runner/catalog-staging/workflow-prompts; do
  [[ "$(stat -c '%U:%G:%a' "${path}")" == eom-workflow-runner:eom:750 ]] || \
    fail "workflow runner private staging metadata mismatch"
done

runuser -u eom -g eom -- "${REPOSITORY}/scripts/workflow/verify_systemd_worker_authorization.sh"

DOCTOR_OUTPUT=$(mktemp /tmp/eom-workflow-runtime-doctor.XXXXXX)
chmod 0600 "${DOCTOR_OUTPUT}"
runuser -u eom-workflow-runner -g eom \
  -G eom-cdx-01 -G eom-cdx-02 -G eom-cdx-03 -G eom-cdx-04 -G eom-cdx-05 -- \
  env -i HOME=/var/lib/eom-workflow-runner USER=eom-workflow-runner \
    LOGNAME=eom-workflow-runner TZ=UTC PATH=/srv/eom/conda/envs/eom-api/bin:/usr/bin:/bin \
    EOM_POSTGRES_ENV=/etc/eom/secrets/postgres.env \
    EOM_WORKER_CONFIG=/etc/eom/worker-slots.yaml \
    EOM_WORKFLOW_DEFINITION=/etc/eom/workflows/generic-item-development.yaml \
    EOM_HUMAN_ACTOR_CONFIG=/etc/eom/human-actors.yaml \
    EOM_WORKFLOW_RUNNER_CONFIG=/etc/eom/workflow-runner.yaml \
    EOM_WORKFLOW_PROMPT_ROOT=/etc/eom/workflow-prompts \
    EOM_CODEX_CAPABILITY_POLICY=/etc/eom/codex-capabilities.yaml \
    EOM_STAGING_ROOT=/var/lib/eom-workflow-runner/orchestrator-staging \
    EOM_CATALOG_STAGING_ROOT=/var/lib/eom-workflow-runner/catalog-staging \
    "${PYTHON}" -I /srv/eom/conda/envs/eom-api/bin/eom-workflow-runner doctor \
    >"${DOCTOR_OUTPUT}"
"${PYTHON}" -I -c 'import json,sys; value=json.load(open(sys.argv[1])); assert value["passed"] is True' \
  "${DOCTOR_OUTPUT}"
rm -f "${DOCTOR_OUTPUT}"

if [[ ${ACTION} == install ]]; then
  install -d -o root -g root -m 0700 "${RELEASE_ROOT}"
  RECORD="${RELEASE_ROOT}/${EXPECTED_COMMIT}.txt"
  TEMPORARY=$(mktemp "${RELEASE_ROOT}/.${EXPECTED_COMMIT}.XXXXXX")
  chmod 0600 "${TEMPORARY}"
  {
    printf 'source_commit=%s\n' "${EXPECTED_COMMIT}"
    printf 'runner_unit_sha256=%s\n' "$(sha256sum "${UNIT_ROOT}/eom-workflow-runner.service" | cut -d' ' -f1)"
    printf 'worker_exec_sha256=%s\n' "$(sha256sum "${LIBEXEC_ROOT}/eom-worker-exec" | cut -d' ' -f1)"
    printf 'worker_auth_exec_sha256=%s\n' "$(sha256sum "${LIBEXEC_ROOT}/eom-worker-auth-status" | cut -d' ' -f1)"
    printf 'codex_bwrap_apparmor_sha256=%s\n' "$(sha256sum "${APPARMOR_TARGET}" | cut -d' ' -f1)"
    printf 'deployed_at_utc=%s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
  } >"${TEMPORARY}"
  mv -f "${TEMPORARY}" "${RECORD}"
  require_regular "${RECORD}" root:root:600
fi

printf 'worker_runtime=%s_PASS\n' "${ACTION^^}"
